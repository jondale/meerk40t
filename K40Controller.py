import threading
import time

import usb.core
import usb.util

STATUS_BAD_STATE = 204
STATUS_OK = 206
STATUS_PACKET_REJECTED = 207
STATUS_FINISH = 236
STATUS_BUSY = 238
STATUS_POWER = 239

STATUS_NO_DEVICE = -1


def convert_to_list_bytes(data):
    if isinstance(data, str):  # python 2
        packet = [0] * 30
        for i in range(0, 30):
            packet[i] = ord(data[i])
        return packet
    else:
        packet = [0] * 30
        for i in range(0, 30):
            packet[i] = data[i]
        return packet


crc_table = [
    0x00, 0x5E, 0xBC, 0xE2, 0x61, 0x3F, 0xDD, 0x83,
    0xC2, 0x9C, 0x7E, 0x20, 0xA3, 0xFD, 0x1F, 0x41,
    0x00, 0x9D, 0x23, 0xBE, 0x46, 0xDB, 0x65, 0xF8,
    0x8C, 0x11, 0xAF, 0x32, 0xCA, 0x57, 0xE9, 0x74]


def onewire_crc_lookup(line):
    """
    License: 2-clause "simplified" BSD license
    Copyright (C) 1992-2017 Arjen Lentz
    https://lentz.com.au/blog/calculating-crc-with-a-tiny-32-entry-lookup-table

    :param line: line to be CRC'd
    :return: 8 bit crc of line.
    """
    crc = 0
    for i in range(0, 30):
        crc = line[i] ^ crc
        crc = crc_table[crc & 0x0f] ^ crc_table[16 + ((crc >> 4) & 0x0f)]
    return crc


class ControllerQueueThread(threading.Thread):
    def __init__(self, controller):
        threading.Thread.__init__(self)
        self.controller = controller
        self.state = 1

    def run(self):
        while self.state != 0:
            self.controller.process_queue()
            time.sleep(0.1)

            while self.state > 3:
                time.sleep(1)


class K40Controller:
    def __init__(self, mock=False):
        self.status = None
        self.usb = None
        self.interface = None
        self.detached = False
        self.packet_listener = None
        self.status_listener = None
        self.wait_listener = None

        self.buffer = b''
        self.add_queue = b''
        self.thread = None
        self.packet_count = 0
        self.lock = threading.Lock()

        self.mock = mock

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __iadd__(self, other):
        self.lock.acquire()
        self.add_queue += other
        self.lock.release()
        self.consume_queue()
        return self

    def consume_queue(self):
        if self.thread is None:
            self.thread = ControllerQueueThread(self)
            self.thread.start()

    def count_packet_buffer(self):
        return int((len(self.buffer) + len(self.add_queue)) / 30.0)

    def process_queue(self):
        if self.usb is None and not self.mock:
            try:
                self.open()
            except usb.core.USBError:
                self.status = STATUS_NO_DEVICE
                if self.status_listener is not None:
                    self.status_listener(self.status)
                return
        wait_finish = False
        while True:
            if len(self.add_queue):
                self.lock.acquire()
                self.buffer += self.add_queue
                self.add_queue = b''
                self.lock.release()
            if len(self.buffer) == 0:
                break
            find = self.buffer.find('\n', 0, 30)
            if find != -1:
                length = min(30, len(self.buffer), find+1)
            else:
                length = min(30, len(self.buffer))
            packet = self.buffer[:length]
            if packet.endswith('-'):  # edge condition of "-\n" catching only the '-' exactly at 30.
                packet += self.buffer[length:length+1]
                length += 1
            if packet.endswith('\n'):
                packet = packet[:-1]
                if packet.endswith('-'):
                    packet = packet[:-1]
                    wait_finish = True
                packet += b'F' * (30 - len(packet))
            if len(packet) == 30:
                self.buffer = self.buffer[length:]
            else:
                break  # No valid packet was able to be produced.
            # try to send packet
            self.wait(STATUS_OK)
            self.send_packet(packet)
            if wait_finish:
                self.wait(STATUS_FINISH)
                wait_finish = False

    def pad_buffer(self):
        self.buffer += b'F' * (30 - (len(self.buffer) % 30))

    def open(self):
        devices = usb.core.find(idVendor=0x1A86, idProduct=0x5512, find_all=True)
        for device in devices:
            self.usb = device
            break
        if self.usb is None:
            raise usb.core.USBError('Unable to find device.')
        self.usb.set_configuration()
        self.interface = self.usb.get_active_configuration()[(0, 0)]
        try:
            if self.usb.is_kernel_driver_active(self.interface.bInterfaceNumber):
                try:
                    self.usb.detach_kernel_driver(self.interface.bInterfaceNumber)
                    self.detached = True
                except usb.core.USBError:
                    raise usb.core.USBError('Unable to detach from kernel')
        except NotImplementedError:
            pass  # Driver does not permit kernel detaching.
        usb.util.claim_interface(self.usb, self.interface)
        self.usb.ctrl_transfer(bmRequestType=64, bRequest=177, wValue=258,
                               wIndex=0, data_or_wLength=0, timeout=5000)

    def close(self):
        if self.usb is not None:
            if self.detached:
                try:
                    self.usb.attach_kernel_driver(self.interface.bInterfaceNumber)
                    self.detached = False
                except usb.core.USBError:
                    raise usb.core.USBError('Unable to reattach driver to kernel')
            usb.util.release_interface(self.usb, self.interface)
            usb.util.dispose_resources(self.usb)
            self.usb.reset()
            self.interface = None
            self.usb = None

    def send_packet(self, packet_byte_data):
        if len(packet_byte_data) != 30:
            raise usb.core.USBError('We can only send 30 byte packets.')
        data = convert_to_list_bytes(packet_byte_data)
        packet = [166] + [0] + data + [166] + [onewire_crc_lookup(data)]

        sending = True
        while sending:
            if not self.mock:
                self.usb.write(0x2, packet, 10000)  # usb.util.ENDPOINT_OUT | usb.util.ENDPOINT_TYPE_BULK
            self.packet_count += 1
            if self.packet_listener is not None:
                self.packet_listener(packet, packet_byte_data)
            self.update_status()
            if self.status[1] != STATUS_PACKET_REJECTED:
                sending = False

    def update_status(self):
        if self.mock:
            self.status = [STATUS_OK] * 6
            if self.status_listener is not None:
                self.status_listener(self.status)
        else:
            self.usb.write(0x02, [160], 10000)  # usb.util.ENDPOINT_IN | usb.util.ENDPOINT_TYPE_BULK
            self.status = self.usb.read(0x82, 6, 10000)
            if self.status_listener is not None:
                self.status_listener(self.status)

    def wait(self, value):
        i = 0
        while True:
            self.update_status()
            if self.mock:   # Mock controller
                self.status = [value] * 6
            if self.status[1] == value:
                break
            time.sleep(0.1)
            if self.wait_listener is not None:
                if self.wait_listener(i):
                    break
            i += 1