"""
Rotary control window.

A minimal driver-agnostic operator panel: position readout, jog +/-, set
origin, home (zero), and calibration test. Every action is dispatched as
a console command (`rotary_jog`, `rotary_to`, `rotary_pos`, `rotary_zero`,
`rotary_test`) so this panel works for any driver that implements the
optional `rotary_*` methods.

Threading: hardware-touching driver calls (e.g. `rotary_position`,
`rotary_move_relative`) can block the calling thread for several seconds
when the device is offline because the controller retries USB connection.
All such work is therefore dispatched to a worker thread via
`service.threaded()`; UI updates are marshalled back to the main thread
via `dispatch_to_main_thread`. The panel never touches hardware from
`__init__`, `pane_show`, or signal listeners — only from explicit user
clicks.
"""

import wx

from meerk40t.gui.icons import icon_rotary
from meerk40t.gui.mwindow import MWindow
from meerk40t.gui.wxutils import (
    StaticBoxSizer,
    dispatch_to_main_thread,
    wxButton,
    wxComboBox,
    wxStaticText,
)
from meerk40t.kernel import signal_listener

_ = wx.GetTranslation


JOG_DISTANCES = (
    "0.1mm",
    "1mm",
    "5mm",
    "10mm",
    "1deg",
    "10deg",
    "45deg",
    "90deg",
    "0.25r",
    "1r",
)


class RotaryControlPanel(wx.Panel):
    def __init__(self, *args, context=None, **kwds):
        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context  # device service
        self.context.themes.set_window_colors(self)
        self._busy = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Position readout
        pos_box = StaticBoxSizer(self, wx.ID_ANY, _("Position"), wx.HORIZONTAL)
        self.label_position = wxStaticText(self, wx.ID_ANY, _("(click Refresh)"))
        pos_box.Add(self.label_position, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        self.btn_refresh = wxButton(self, wx.ID_ANY, _("Refresh"))
        self.btn_refresh.SetToolTip(_("Query the rotary position from the device."))
        self.btn_refresh.Bind(wx.EVT_BUTTON, self.on_refresh)
        pos_box.Add(self.btn_refresh, 0, wx.ALL, 4)
        sizer.Add(pos_box, 0, wx.EXPAND | wx.ALL, 4)

        # Jog row
        jog_box = StaticBoxSizer(self, wx.ID_ANY, _("Jog"), wx.HORIZONTAL)
        self.btn_jog_neg = wxButton(self, wx.ID_ANY, _("Jog -"))
        self.btn_jog_neg.SetToolTip(
            _("Move rotary by the negative of the selected distance.")
        )
        self.btn_jog_neg.Bind(wx.EVT_BUTTON, self.on_jog_neg)
        jog_box.Add(self.btn_jog_neg, 1, wx.ALL, 4)

        self.combo_jog_distance = wxComboBox(
            self,
            wx.ID_ANY,
            value=JOG_DISTANCES[2],
            choices=list(JOG_DISTANCES),
            style=wx.CB_DROPDOWN,
        )
        self.combo_jog_distance.SetToolTip(
            _(
                "Jog distance. Accepts e.g. 5mm (arc length on object surface), "
                "90deg, 0.25r (revolutions), or a raw step count."
            )
        )
        jog_box.Add(self.combo_jog_distance, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

        self.btn_jog_pos = wxButton(self, wx.ID_ANY, _("Jog +"))
        self.btn_jog_pos.SetToolTip(_("Move rotary by the selected distance."))
        self.btn_jog_pos.Bind(wx.EVT_BUTTON, self.on_jog_pos)
        jog_box.Add(self.btn_jog_pos, 1, wx.ALL, 4)
        sizer.Add(jog_box, 0, wx.EXPAND | wx.ALL, 4)

        # Action buttons
        act_box = StaticBoxSizer(self, wx.ID_ANY, _("Actions"), wx.HORIZONTAL)
        self.btn_home = wxButton(self, wx.ID_ANY, _("Go to Zero"))
        self.btn_home.SetToolTip(_("Move rotary to absolute step position 0."))
        self.btn_home.Bind(wx.EVT_BUTTON, self.on_home)
        act_box.Add(self.btn_home, 1, wx.ALL, 4)

        self.btn_set_zero = wxButton(self, wx.ID_ANY, _("Set Zero"))
        self.btn_set_zero.SetToolTip(_("Mark the current position as the origin."))
        self.btn_set_zero.Bind(wx.EVT_BUTTON, self.on_set_zero)
        act_box.Add(self.btn_set_zero, 1, wx.ALL, 4)

        self.btn_test = wxButton(self, wx.ID_ANY, _("Test"))
        self.btn_test.SetToolTip(
            _("Rotate one full revolution forward, then return to start.")
        )
        self.btn_test.Bind(wx.EVT_BUTTON, self.on_test)
        act_box.Add(self.btn_test, 1, wx.ALL, 4)
        sizer.Add(act_box, 0, wx.EXPAND | wx.ALL, 4)

        # Status line
        self.label_status = wxStaticText(self, wx.ID_ANY, "")
        sizer.Add(self.label_status, 0, wx.ALL | wx.EXPAND, 4)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.Layout()

        # _update_availability is hasattr-only, no hardware. Safe at init.
        self._update_availability()
        # Deliberately DO NOT call hardware on __init__: that includes the
        # position query, which would block the GUI for several seconds while
        # the controller retries the USB connect.

    # --- helpers -------------------------------------------------------

    def _driver_supports_rotary(self):
        driver = getattr(self.context, "driver", None)
        if driver is None or not hasattr(driver, "rotary_move_relative"):
            return False
        # Drivers that advertise capabilities use that as the truth: a None
        # return means the driver is currently configured for a mode that
        # doesn't accept rotary motor commands (e.g. balor left in
        # 'substitute' mode). Without capabilities() we fall back to the
        # method-existence check.
        if hasattr(driver, "rotary_capabilities"):
            return driver.rotary_capabilities() is not None
        return True

    def _update_availability(self):
        supported = self._driver_supports_rotary()
        for w in (
            self.btn_jog_neg,
            self.btn_jog_pos,
            self.btn_home,
            self.btn_set_zero,
            self.btn_test,
            self.btn_refresh,
            self.combo_jog_distance,
        ):
            try:
                w.Enable(supported and not self._busy)
            except Exception:
                pass
        if not supported:
            self._set_status(self._unsupported_reason())
        elif not self._busy:
            self._set_status("")

    def _unsupported_reason(self):
        driver = getattr(self.context, "driver", None)
        if driver is None or not hasattr(driver, "rotary_move_relative"):
            return _(
                "Active device's driver does not implement rotary motion."
            )
        # Driver has the methods but capabilities returned None — it's
        # configured for substitute mode (view-scale) where the panel's
        # jog/test/position controls have no hardware effect.
        return _(
            "Rotary is configured for substitute mode; switch rotary_mode "
            "to 'dedicated' to use these controls."
        )

    def _set_status(self, text):
        try:
            self.label_status.SetLabel(text)
        except Exception:
            pass

    def _set_position_label(self, text):
        try:
            self.label_position.SetLabel(text)
        except Exception:
            pass

    def _selected_distance(self):
        text = self.combo_jog_distance.GetValue().strip()
        return text if text else "5mm"

    def _format_position(self, steps):
        spr = getattr(self.context, "rotary_steps_per_rotation", 12800) or 1
        deg = steps * 360.0 / spr
        return _("{steps} steps  (~{deg:.2f}°)").format(steps=steps, deg=deg)

    def _begin_busy(self, status_text):
        """Disable buttons and set a status message. Called on main thread."""
        self._busy = True
        self._set_status(status_text)
        self._update_availability()

    def _end_busy(self, status_text=""):
        self._busy = False
        self._set_status(status_text)
        self._update_availability()

    def _run_in_worker(self, worker_fn, status_text):
        """
        Run worker_fn() on a worker thread; UI updates inside worker_fn
        must marshal themselves back via dispatch_to_main_thread. Disables
        buttons while the worker runs.
        """
        if not self._driver_supports_rotary():
            return
        if self._busy:
            return
        self._begin_busy(status_text)
        thread_name = f"rotary_panel_{id(self)}_{status_text}"
        try:
            self.context.threaded(
                worker_fn, thread_name=thread_name, daemon=True
            )
        except Exception as exc:
            # Fall back to direct call if threaded() isn't available;
            # safer to surface the error than to silently freeze.
            self._end_busy(_("Threading error: %s") % exc)

    # --- worker functions (run off-thread) -----------------------------

    def _worker_query_position(self):
        driver = getattr(self.context, "driver", None)
        text = None
        try:
            if driver is None or not hasattr(driver, "rotary_position"):
                text = _("(no feedback)")
            else:
                steps = driver.rotary_position()
                if steps is None:
                    text = _("(not connected)")
                else:
                    text = self._format_position(steps)
        except Exception as exc:
            text = _("Error: %s") % exc
        dispatch_to_main_thread(self._on_query_done)(text)

    def _worker_console(self, command_line, follow_up_query):
        """Run a console command; optionally re-query position afterward."""
        try:
            self.context.console(command_line)
        except Exception as exc:
            dispatch_to_main_thread(self._end_busy)(_("Error: %s") % exc)
            return
        if not follow_up_query:
            dispatch_to_main_thread(self._end_busy)("")
            return
        # Query position after motion completes.
        driver = getattr(self.context, "driver", None)
        text = None
        try:
            if driver is None or not hasattr(driver, "rotary_position"):
                text = _("(no feedback)")
            else:
                steps = driver.rotary_position()
                text = (
                    _("(not connected)")
                    if steps is None
                    else self._format_position(steps)
                )
        except Exception as exc:
            text = _("Error: %s") % exc
        dispatch_to_main_thread(self._on_query_done)(text)

    # --- main-thread callbacks ----------------------------------------

    def _on_query_done(self, text):
        self._set_position_label(text)
        self._end_busy("")

    # --- handlers ------------------------------------------------------

    def on_refresh(self, _event):
        self._set_position_label(_("(querying…)"))
        self._run_in_worker(self._worker_query_position, _("Querying position…"))

    def on_jog_pos(self, _event):
        dist = self._selected_distance()
        self._run_in_worker(
            lambda: self._worker_console(f"rotary_jog {dist}\n", True),
            _("Jogging +{d}…").format(d=dist),
        )

    def on_jog_neg(self, _event):
        dist = self._selected_distance()
        # Prepend a minus sign. For pure numbers or unit strings this works;
        # for e.g. "5mm" we send "-5mm", which Length parses correctly.
        self._run_in_worker(
            lambda: self._worker_console(f"rotary_jog -{dist}\n", True),
            _("Jogging -{d}…").format(d=dist),
        )

    def on_home(self, _event):
        self._run_in_worker(
            lambda: self._worker_console("rotary_to 0\n", True),
            _("Moving to zero…"),
        )

    def on_set_zero(self, _event):
        self._run_in_worker(
            lambda: self._worker_console("rotary_zero\n", True),
            _("Setting zero…"),
        )

    def on_test(self, _event):
        self._run_in_worker(
            lambda: self._worker_console("rotary_test\n", True),
            _("Running rotary test…"),
        )

    # --- pane lifecycle ------------------------------------------------

    def pane_show(self):
        # Only do hasattr-based UI prep. No hardware calls.
        self._update_availability()

    def pane_hide(self):
        pass

    @signal_listener("device;modified")
    @signal_listener("device;connected")
    def _on_device_change(self, *_args):
        # Signal listeners fire on the main thread; keep this fast and
        # hardware-free. Position is only refreshed on explicit user action.
        self._update_availability()


class RotaryControlWindow(MWindow):
    def __init__(self, *args, **kwds):
        super().__init__(420, 240, *args, **kwds)
        self.panel = RotaryControlPanel(
            self, wx.ID_ANY, context=self.context.device
        )
        self.sizer.Add(self.panel, 1, wx.EXPAND, 0)
        self.add_module_delegate(self.panel)
        _icon = wx.NullIcon
        _icon.CopyFromBitmap(icon_rotary.GetBitmap())
        self.SetIcon(_icon)
        self.SetTitle(_("Rotary Control"))
        self.restore_aspect(honor_initial_values=True)

    def window_open(self):
        self.panel.pane_show()

    def window_close(self):
        self.panel.pane_hide()

    @staticmethod
    def submenu():
        # Hint for translation: _("Device-Settings"), _("Rotary-Control")
        return "Device-Settings", "Rotary-Control"

    @staticmethod
    def helptext():
        return _("Operate the rotary axis (jog, test, position)")
