# -*- coding: ISO-8859-1 -*-
#
# generated by wxGlade 0.9.3 on Thu Jun 27 21:45:40 2019
#

import wx

from LaserCommandConstants import *
from icons import *

_ = wx.GetTranslation

# begin wxGlade: dependencies
# end wxGlade
MILS_IN_MM = 39.3701


class Navigation(wx.Frame):
    def __init__(self, *args, **kwds):
        # begin wxGlade: Navigation.__init__
        kwds["style"] = kwds.get("style", 0) | wx.DEFAULT_FRAME_STYLE | wx.FRAME_TOOL_WINDOW | wx.STAY_ON_TOP
        wx.Frame.__init__(self, *args, **kwds)
        self.SetSize((416, 463))
        self.spin_jog_mils = wx.SpinCtrlDouble(self, wx.ID_ANY, "394.0", min=0.0, max=10000.0)
        self.spin_jog_mm = wx.SpinCtrlDouble(self, wx.ID_ANY, "10.0", min=0.0, max=254.0)
        self.spin_jog_cm = wx.SpinCtrlDouble(self, wx.ID_ANY, "1.0", min=0.0, max=25.4)
        self.spin_jog_inch = wx.SpinCtrlDouble(self, wx.ID_ANY, "0.394", min=0.0, max=10.0)
        self.button_navigate_up_left = wx.BitmapButton(self, wx.ID_ANY, icons8_up_left_50.GetBitmap())
        self.button_navigate_up = wx.BitmapButton(self, wx.ID_ANY, icons8_up_50.GetBitmap())
        self.button_navigate_up_right = wx.BitmapButton(self, wx.ID_ANY, icons8_up_right_50.GetBitmap())
        self.button_navigate_left = wx.BitmapButton(self, wx.ID_ANY, icons8_left_50.GetBitmap())
        self.button_navigate_home = wx.BitmapButton(self, wx.ID_ANY, icons8_home_filled_50.GetBitmap())
        self.button_navigate_right = wx.BitmapButton(self, wx.ID_ANY, icons8_right_50.GetBitmap())
        self.button_navigate_down_left = wx.BitmapButton(self, wx.ID_ANY, icons8_down_left_50.GetBitmap())
        self.button_navigate_down = wx.BitmapButton(self, wx.ID_ANY, icons8_down_50.GetBitmap())
        self.button_navigate_down_right = wx.BitmapButton(self, wx.ID_ANY, icons8_down_right_50.GetBitmap())
        self.button_navigate_unlock = wx.BitmapButton(self, wx.ID_ANY, icons8_padlock_50.GetBitmap())
        self.button_navigate_lock = wx.BitmapButton(self, wx.ID_ANY, icons8_lock_50.GetBitmap())
        self.button_align_corner_top_left = wx.BitmapButton(self, wx.ID_ANY, icon_corner1.GetBitmap())
        self.button_align_drag_up = wx.BitmapButton(self, wx.ID_ANY, icons8up.GetBitmap())
        self.button_align_corner_top_right = wx.BitmapButton(self, wx.ID_ANY, icon_corner2.GetBitmap())
        self.button_align_drag_left = wx.BitmapButton(self, wx.ID_ANY, icons8_left.GetBitmap())
        self.button_align_center = wx.BitmapButton(self, wx.ID_ANY, icons8_square_border_50.GetBitmap())
        self.button_align_drag_right = wx.BitmapButton(self, wx.ID_ANY, icons8_right.GetBitmap())
        self.button_align_corner_bottom_left = wx.BitmapButton(self, wx.ID_ANY, icon_corner4.GetBitmap())
        self.button_align_drag_down = wx.BitmapButton(self, wx.ID_ANY, icons8_down.GetBitmap())
        self.button_align_corner_bottom_right = wx.BitmapButton(self, wx.ID_ANY, icon_corner3.GetBitmap())
        self.button_align_trace_hull = wx.BitmapButton(self, wx.ID_ANY, icons8_pentagon_50.GetBitmap())
        self.button_align_trace_quick = wx.BitmapButton(self, wx.ID_ANY, icons8_pentagon_square_50.GetBitmap())
        self.button_navigate_pulse = wx.BitmapButton(self, wx.ID_ANY, icons8_laser_beam_52.GetBitmap())
        self.spin_pulse_duration = wx.SpinCtrl(self, wx.ID_ANY, "50", min=1, max=1000)
        self.button_navigate_move_to = wx.BitmapButton(self, wx.ID_ANY, icons8_center_of_gravity_50.GetBitmap())
        self.text_position_x = wx.TextCtrl(self, wx.ID_ANY, "0")
        self.text_position_y = wx.TextCtrl(self, wx.ID_ANY, "0")

        self.__set_properties()
        self.__do_layout()

        self.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_spin_jog_distance, self.spin_jog_mils)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_spin_jog_distance, self.spin_jog_mils)
        self.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_spin_jog_distance, self.spin_jog_mm)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_spin_jog_distance, self.spin_jog_mm)
        self.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_spin_jog_distance, self.spin_jog_cm)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_spin_jog_distance, self.spin_jog_cm)
        self.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_spin_jog_distance, self.spin_jog_inch)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_spin_jog_distance, self.spin_jog_inch)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_home, self.button_navigate_home)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_UL, self.button_navigate_up_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_U, self.button_navigate_up)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_UR, self.button_navigate_up_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_L, self.button_navigate_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_R, self.button_navigate_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_DL, self.button_navigate_down_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_D, self.button_navigate_down)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_DR, self.button_navigate_down_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_unlock, self.button_navigate_unlock)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_lock, self.button_navigate_lock)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_corner_TL, self.button_align_corner_top_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_drag_up, self.button_align_drag_up)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_corner_TR, self.button_align_corner_top_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_drag_left, self.button_align_drag_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_center, self.button_align_center)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_drag_right, self.button_align_drag_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_corner_BL, self.button_align_corner_bottom_left)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_drag_down, self.button_align_drag_down)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_corner_BR, self.button_align_corner_bottom_right)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_trace_hull, self.button_align_trace_hull)
        self.Bind(wx.EVT_BUTTON, self.on_button_align_trace_quick, self.button_align_trace_quick)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_pulse, self.button_navigate_pulse)
        self.Bind(wx.EVT_SPINCTRL, self.on_spin_pulse_duration, self.spin_pulse_duration)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_spin_pulse_duration, self.spin_pulse_duration)
        self.Bind(wx.EVT_BUTTON, self.on_button_navigate_move_to, self.button_navigate_move_to)
        # end wxGlade
        self.Bind(wx.EVT_CLOSE, self.on_close, self)
        self.kernel = None
        self.device = None
        self.elements = None
        self.bounds = None
        self.design_locked = False
        self.drag_ready(False)
        self.select_ready(False)

    def on_close(self, event):
        self.kernel.mark_window_closed("Navigation")
        self.kernel.unlisten("selected_elements", self.on_selected_elements_change)
        self.kernel.unlisten("selected_bounds", self.on_selected_bounds_change)
        event.Skip()  # Call destroy.

    def __set_properties(self):
        # begin wxGlade: Navigation.__set_properties
        self.SetTitle(_("Navigation"))
        self.spin_jog_mils.SetMinSize((80, 23))
        self.spin_jog_mils.SetToolTip(_("Set Jog Distance in mils (1/1000th of an inch)"))
        self.spin_jog_mm.SetMinSize((80, 23))
        self.spin_jog_mm.SetToolTip(_("Set Jog Distance in mm"))
        self.spin_jog_cm.SetMinSize((80, 23))
        self.spin_jog_cm.SetToolTip(_("Set Jog Distance in cm"))
        self.spin_jog_inch.SetMinSize((80, 23))
        self.spin_jog_inch.SetToolTip(_("Set Jog Distance in inch"))
        self.button_navigate_up_left.SetToolTip(_("Move laser diagonally in the up and left direction"))
        self.button_navigate_up_left.SetSize(self.button_navigate_up_left.GetBestSize())
        self.button_navigate_up.SetToolTip(_("Move laser in the up direction"))
        self.button_navigate_up.SetSize(self.button_navigate_up.GetBestSize())
        self.button_navigate_up_right.SetToolTip(_("Move laser diagonally in the up and right direction"))
        self.button_navigate_up_right.SetSize(self.button_navigate_up_right.GetBestSize())
        self.button_navigate_left.SetToolTip(_("Move laser in the left direction"))
        self.button_navigate_left.SetSize(self.button_navigate_left.GetBestSize())
        self.button_navigate_home.SetSize(self.button_navigate_home.GetBestSize())
        self.button_navigate_right.SetToolTip(_("Move laser in the right direction"))
        self.button_navigate_right.SetSize(self.button_navigate_right.GetBestSize())
        self.button_navigate_down_left.SetToolTip(_("Move laser diagonally in the down and left direction"))
        self.button_navigate_down_left.SetSize(self.button_navigate_down_left.GetBestSize())
        self.button_navigate_down.SetToolTip(_("Move laser in the down direction"))
        self.button_navigate_down.SetSize(self.button_navigate_down.GetBestSize())
        self.button_navigate_down_right.SetToolTip(_("Move laser diagonally in the down and right direction"))
        self.button_navigate_down_right.SetSize(self.button_navigate_down_right.GetBestSize())
        self.button_navigate_unlock.SetToolTip(_("Unlock the laser rail"))
        self.button_navigate_unlock.SetSize(self.button_navigate_unlock.GetBestSize())
        self.button_navigate_lock.SetToolTip(_("Lock the laser rail"))
        self.button_navigate_lock.SetSize(self.button_navigate_lock.GetBestSize())
        self.button_align_corner_top_left.SetToolTip(_("Align laser with the upper left corner of the selection"))
        self.button_align_corner_top_left.SetSize(self.button_align_corner_top_left.GetBestSize())
        self.button_align_drag_up.SetSize(self.button_align_drag_up.GetBestSize())
        self.button_align_corner_top_right.SetToolTip(_("Align laser with the upper right corner of the selection"))
        self.button_align_corner_top_right.SetSize(self.button_align_corner_top_right.GetBestSize())
        self.button_align_drag_left.SetSize(self.button_align_drag_left.GetBestSize())
        self.button_align_center.SetToolTip(_("Align laser with the center of the selection"))
        self.button_align_center.SetSize(self.button_align_center.GetBestSize())
        self.button_align_drag_right.SetSize(self.button_align_drag_right.GetBestSize())
        self.button_align_corner_bottom_left.SetToolTip(_("Align laser with the lower left corner of the selection"))
        self.button_align_corner_bottom_left.SetSize(self.button_align_corner_bottom_left.GetBestSize())
        self.button_align_drag_down.SetSize(self.button_align_drag_down.GetBestSize())
        self.button_align_corner_bottom_right.SetToolTip(_("Align laser with the lower right corner of the selection"))
        self.button_align_corner_bottom_right.SetSize(self.button_align_corner_bottom_right.GetBestSize())
        self.button_align_trace_hull.SetToolTip(_("Perform a convex hull trace of the selection"))
        self.button_align_trace_hull.SetSize(self.button_align_trace_hull.GetBestSize())
        self.button_align_trace_quick.SetToolTip(_("Perform a simple trace of the selection"))
        self.button_align_trace_quick.SetSize(self.button_align_trace_quick.GetBestSize())
        self.button_navigate_pulse.SetToolTip(_("Fire a short laser pulse"))
        self.button_navigate_pulse.SetSize(self.button_navigate_pulse.GetBestSize())
        self.spin_pulse_duration.SetMinSize((80, 23))
        self.spin_pulse_duration.SetToolTip(_("Set the duration of the laser pulse"))
        self.button_navigate_move_to.SetToolTip(_("Move to the set position"))
        self.button_navigate_move_to.SetSize(self.button_navigate_move_to.GetBestSize())
        self.text_position_x.SetToolTip(_("Set X value for the Move To"))
        self.text_position_y.SetToolTip(_("Set Y value for the Move To"))
        # end wxGlade

    def __do_layout(self):
        # begin wxGlade: Navigation.__do_layout
        sizer_1 = wx.BoxSizer(wx.VERTICAL)
        sizer_16 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_12 = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, _("Move To")), wx.HORIZONTAL)
        sizer_13 = wx.BoxSizer(wx.VERTICAL)
        sizer_15 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_14 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_5 = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, _("Short Pulse")), wx.HORIZONTAL)
        sizer_11 = wx.BoxSizer(wx.HORIZONTAL)
        grid_sizer_4 = wx.FlexGridSizer(4, 3, 0, 0)
        grid_sizer_3 = wx.FlexGridSizer(4, 3, 0, 0)
        sizer_6 = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, _("Jog Distance")), wx.HORIZONTAL)
        sizer_10 = wx.BoxSizer(wx.VERTICAL)
        sizer_9 = wx.BoxSizer(wx.VERTICAL)
        sizer_8 = wx.BoxSizer(wx.VERTICAL)
        sizer_7 = wx.BoxSizer(wx.VERTICAL)
        sizer_7.Add(self.spin_jog_mils, 0, 0, 0)
        label_5 = wx.StaticText(self, wx.ID_ANY, _("mils"))
        sizer_7.Add(label_5, 0, 0, 0)
        sizer_6.Add(sizer_7, 0, wx.EXPAND, 0)
        sizer_8.Add(self.spin_jog_mm, 0, 0, 0)
        label_6 = wx.StaticText(self, wx.ID_ANY, _(" mm"))
        sizer_8.Add(label_6, 0, 0, 0)
        sizer_6.Add(sizer_8, 0, wx.EXPAND, 0)
        sizer_9.Add(self.spin_jog_cm, 0, 0, 0)
        label_7 = wx.StaticText(self, wx.ID_ANY, _("cm"))
        sizer_9.Add(label_7, 0, 0, 0)
        sizer_6.Add(sizer_9, 0, wx.EXPAND, 0)
        sizer_10.Add(self.spin_jog_inch, 0, 0, 0)
        label_8 = wx.StaticText(self, wx.ID_ANY, _("inch"))
        sizer_10.Add(label_8, 0, 0, 0)
        sizer_6.Add(sizer_10, 0, wx.EXPAND, 0)
        sizer_1.Add(sizer_6, 0, wx.EXPAND, 0)
        grid_sizer_3.Add(self.button_navigate_up_left, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_up, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_up_right, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_left, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_home, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_right, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_down_left, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_down, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_down_right, 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_unlock, 0, 0, 0)
        grid_sizer_3.Add((0, 0), 0, 0, 0)
        grid_sizer_3.Add(self.button_navigate_lock, 0, 0, 0)
        sizer_11.Add(grid_sizer_3, 1, wx.EXPAND, 0)
        grid_sizer_4.Add(self.button_align_corner_top_left, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_drag_up, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_corner_top_right, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_drag_left, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_center, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_drag_right, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_corner_bottom_left, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_drag_down, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_corner_bottom_right, 0, 0, 0)
        grid_sizer_4.Add((0, 0), 0, 0, 0)
        grid_sizer_4.Add(self.button_align_trace_hull, 0, 0, 0)
        grid_sizer_4.Add(self.button_align_trace_quick, 0, 0, 0)
        sizer_11.Add(grid_sizer_4, 1, wx.EXPAND, 0)
        sizer_1.Add(sizer_11, 0, wx.EXPAND, 0)
        sizer_5.Add(self.button_navigate_pulse, 0, 0, 0)
        sizer_5.Add(self.spin_pulse_duration, 0, 0, 0)
        label_4 = wx.StaticText(self, wx.ID_ANY, _(" ms"))
        sizer_5.Add(label_4, 0, 0, 0)
        sizer_16.Add(sizer_5, 0, wx.EXPAND, 0)
        sizer_12.Add(self.button_navigate_move_to, 0, 0, 0)
        label_9 = wx.StaticText(self, wx.ID_ANY, _("X:"))
        sizer_14.Add(label_9, 0, 0, 0)
        sizer_14.Add(self.text_position_x, 0, 0, 0)
        sizer_13.Add(sizer_14, 0, wx.EXPAND, 0)
        label_10 = wx.StaticText(self, wx.ID_ANY, _("Y:"))
        sizer_15.Add(label_10, 0, 0, 0)
        sizer_15.Add(self.text_position_y, 0, 0, 0)
        sizer_13.Add(sizer_15, 0, wx.EXPAND, 0)
        sizer_12.Add(sizer_13, 0, wx.EXPAND, 0)
        sizer_16.Add(sizer_12, 0, wx.EXPAND, 0)
        sizer_1.Add(sizer_16, 1, wx.EXPAND, 0)
        self.SetSizer(sizer_1)
        self.Layout()
        # end wxGlade

    def set_kernel(self, kernel):
        self.kernel = kernel
        self.device = kernel.device
        if self.device is None:
            for attr in dir(self):
                value = getattr(self, attr)
                if isinstance(value, wx.Control):
                    value.Enable(False)
            dlg = wx.MessageDialog(None, _("You do not have a selected device."),
                                   _("No Device Selected."), wx.OK | wx.ICON_WARNING)
            dlg.ShowModal()
            dlg.Destroy()
        else:
            self.device.setting(float, "navigate_jog", self.spin_jog_mils.GetValue())
            self.device.setting(float, "navigate_pulse", self.spin_pulse_duration.GetValue())
            self.spin_pulse_duration.SetValue(self.device.navigate_pulse)
            self.set_jog_distances(self.device.navigate_jog)
        self.kernel.listen("selected_elements", self.on_selected_elements_change)
        self.kernel.listen("selected_bounds", self.on_selected_bounds_change)

    def on_selected_elements_change(self, *args):
        self.elements = args[0]
        self.select_ready(self.elements is not None and len(self.elements) != 0)

    def on_selected_bounds_change(self, *args):
        self.bounds = args[0]

    def drag_ready(self, v):
        self.design_locked = v
        self.button_align_drag_down.Enable(v)
        self.button_align_drag_up.Enable(v)
        self.button_align_drag_right.Enable(v)
        self.button_align_drag_left.Enable(v)

    def select_ready(self, v):
        self.button_align_center.Enable(v)
        self.button_align_corner_top_left.Enable(v)
        self.button_align_corner_top_right.Enable(v)
        self.button_align_corner_bottom_left.Enable(v)
        self.button_align_corner_bottom_right.Enable(v)
        self.button_align_trace_hull.Enable(False)
        self.button_align_trace_quick.Enable(False)

    def set_jog_distances(self, jog_mils):
        self.spin_jog_mils.SetValue(jog_mils)
        self.spin_jog_mm.SetValue(jog_mils / MILS_IN_MM)
        self.spin_jog_cm.SetValue(jog_mils / (MILS_IN_MM * 10.0))
        self.spin_jog_inch.SetValue(jog_mils / 1000.0)

    def on_spin_jog_distance(self, event):  # wxGlade: Navigation.<event_handler>
        if event.Id == self.spin_jog_mils.Id:
            self.device.navigate_jog = float(self.spin_jog_mils.GetValue())
        elif event.Id == self.spin_jog_mm.Id:
            self.device.navigate_jog = float(self.spin_jog_mm.GetValue() * MILS_IN_MM)
        elif event.Id == self.spin_jog_cm.Id:
            self.device.navigate_jog = float(self.spin_jog_cm.GetValue() * MILS_IN_MM * 10.0)
        else:
            self.device.navigate_jog = float(self.spin_jog_inch.GetValue() * 1000.0)
        self.set_jog_distances(int(self.device.navigate_jog))

    def on_button_navigate_home(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.home()
        self.drag_ready(False)

    def on_button_navigate_UL(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(-self.device.navigate_jog, -self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_U(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(0, -self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_UR(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(self.device.navigate_jog, -self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_L(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(-self.device.navigate_jog, 0)
        self.drag_ready(False)

    def on_button_navigate_R(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(self.device.navigate_jog, 0)
        self.drag_ready(False)

    def on_button_navigate_DL(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(-self.device.navigate_jog, self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_D(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(0, self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_DR(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.move_relative(self.device.navigate_jog, self.device.navigate_jog)
        self.drag_ready(False)

    def on_button_navigate_unlock(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.unlock_rail()

    def on_button_navigate_lock(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.interpreter.lock_rail()

    def on_button_align_center(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.bounds
        if bbox is None:
            return
        self.device.interpreter.move_absolute((bbox[0] + bbox[2]) / 2.0, (bbox[3] + bbox[1]) / 2.0)
        self.drag_ready(True)

    def on_button_align_corner_TL(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.bounds
        if bbox is None:
            return
        self.device.interpreter.move_absolute(bbox[0], bbox[1])
        self.drag_ready(True)

    def on_button_align_corner_TR(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.bounds
        if bbox is None:
            return
        self.device.interpreter.move_absolute(bbox[2], bbox[1])
        self.drag_ready(True)

    def on_button_align_corner_BL(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.bounds
        if bbox is None:
            return
        self.device.interpreter.move_absolute(bbox[0], bbox[3])

        self.drag_ready(True)

    def on_button_align_corner_BR(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.bounds
        if bbox is None:
            return
        self.device.interpreter.move_absolute(bbox[2], bbox[3])
        self.drag_ready(True)

    def drag_relative(self, dx, dy):
        if self.elements is not None:
            self.kernel.root.move_selected(dx, dy)
        self.device.interpreter.move_relative(dx,dy)

    def on_button_align_drag_down(self, event):  # wxGlade: Navigation.<event_handler>
        self.drag_relative(0, self.device.navigate_jog)

    def on_button_align_drag_right(self, event):  # wxGlade: Navigation.<event_handler>
        self.drag_relative(self.device.navigate_jog, 0)

    def on_button_align_drag_up(self, event):  # wxGlade: Navigation.<event_handler>
        self.drag_relative(0, -self.device.navigate_jog)

    def on_button_align_drag_left(self, event):  # wxGlade: Navigation.<event_handler>
        self.drag_relative(-self.device.navigate_jog, 0)

    def on_button_align_trace_hull(self, event):  # wxGlade: Navigation.<event_handler>
        elements = self.elements
        self.drag_ready(True)

    def on_button_align_trace_quick(self, event):  # wxGlade: Navigation.<event_handler>
        bbox = self.kernel.last_signal('selected_bounds')
        if bbox is None:
            return
        self.drag_ready(True)

    def on_button_navigate_pulse(self, event):  # wxGlade: Navigation.<event_handler>
        value = self.spin_pulse_duration.GetValue()
        value = value / 1000.0

        def timed_fire():
            yield COMMAND_WAIT_BUFFER_EMPTY
            yield COMMAND_LASER_ON
            yield COMMAND_WAIT, value
            yield COMMAND_LASER_OFF

        self.device.send_job(timed_fire)

    def on_spin_pulse_duration(self, event):  # wxGlade: Navigation.<event_handler>
        self.device.navigate_pulse = self.spin_pulse_duration.GetValue()

    def on_button_navigate_move_to(self, event):  # wxGlade: Navigation.<event_handler>
        try:
            x = self.text_position_x
            y = self.text_position_y
            self.device.interpreter.move_absolute(x, y)
        except ValueError:
            return
