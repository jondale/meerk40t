import wx

from meerk40t.device.gui.defaultactions import DefaultActionPanel
from meerk40t.device.gui.effectspanel import EffectsPanel
from meerk40t.device.gui.formatterpanel import FormatterPanel
from meerk40t.device.gui.warningpanel import WarningPanel
from meerk40t.gui.choicepropertypanel import ChoicePropertyPanel
from meerk40t.gui.icons import icons8_administrative_tools
from meerk40t.gui.mwindow import MWindow
from meerk40t.kernel import Job, signal_listener

_ = wx.GetTranslation


class BalorConfiguration(MWindow):
    """BalorConfiguration - User interface panel for laser cutting operations
    **Technical Purpose:**
    Provides user interface controls for balorconfiguration functionality. Integrates with lens_size, balorpin for enhanced functionality.
    **End-User Perspective:**
    This panel provides user interface controls for balorconfiguration functionality in MeerK40t."""

    def __init__(self, *args, **kwds):
        super().__init__(550, 700, *args, **kwds)
        window_context = self.context
        self.context = self.context.device
        self.SetHelpText("balorconfig")
        _icon = wx.NullIcon
        _icon.CopyFromBitmap(icons8_administrative_tools.GetBitmap())
        self.SetIcon(_icon)
        self.SetTitle(_("Balor-Configuration"))
        self._test_pin = False
        self._cor_wizard = False
        self.notebook_main = wx.aui.AuiNotebook(
            self,
            -1,
            style=wx.aui.AUI_NB_TAB_EXTERNAL_MOVE
            | wx.aui.AUI_NB_SCROLL_BUTTONS
            | wx.aui.AUI_NB_TAB_SPLIT
            | wx.aui.AUI_NB_TAB_MOVE
            | wx.aui.AUI_NB_TOP,
        )
        # ARGGH, the color setting via the ArtProvider does only work
        # if you set the tabs to the bottom! wx.aui.AUI_NB_BOTTOM
        self.window_context.themes.set_window_colors(self.notebook_main)
        bg_std = self.window_context.themes.get("win_bg")
        bg_active = self.window_context.themes.get("highlight")
        self.notebook_main.GetArtProvider().SetColour(bg_std)
        self.notebook_main.GetArtProvider().SetActiveColour(bg_active)

        self.sizer.Add(self.notebook_main, 1, wx.EXPAND, 0)
        options = (
            ("balor", "Balor"),
            ("balor-redlight", _("Redlight")),
            ("balor-global", _("Global")),
            ("balor-global-timing", _("Timings")),
            ("balor-extra", _("Extras")),
            ("balor-effects", _("Effects")),
            ("balor-defaults", _("Operation Defaults")),
        )
        self.test_bits = ""
        injector = (
            {
                "attr": "test_pin",
                "object": self,
                "default": False,
                "type": bool,
                "style": "button",
                "label": _("Test"),
                "tip": _("Turn red dot on for test purposes"),
                # Hint for translation _("Parameters")
                "section": "_10_Parameters",
                # Hint for translation _("Pin-Index")
                "subsection": "_30_Pin-Index",
            },
            {
                "attr": "test_bits",
                "object": self,
                "default": "",
                "type": str,
                "enabled": False,
                "label": _("Bits"),
                # Hint for translation _("Parameters")
                "section": "_10_Parameters",
                # Hint for translation _("Pin-Index")
                "subsection": "_30_Pin-Index",
            },
            {
                "attr": "cor_wizard",
                "object": self,
                "default": False,
                "type": bool,
                "style": "button",
                "label": _("Generate…"),
                "tip": _("Open the correction file generator wizard"),
                "section": "_00_General",
                "subsection": "Correction File",
            },
        )
        self.panels = []
        for item in options:
            section = item[0]
            pagetitle = _(item[1])
            addpanel = self.visible_choices(section)
            if addpanel:
                if item[0] == "balor":
                    injection = injector
                else:
                    injection = None
                newpanel = ChoicePropertyPanel(
                    self,
                    wx.ID_ANY,
                    context=self.context,
                    choices=section,
                    injector=injection,
                )
                self.panels.append(newpanel)
                self.notebook_main.AddPage(newpanel, pagetitle)

        # newpanel = EffectsPanel(self, id=wx.ID_ANY, context=self.context)
        # self.panels.append(newpanel)
        # self.notebook_main.AddPage(newpanel, _("Effects"))

        newpanel = WarningPanel(self, id=wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        self.notebook_main.AddPage(newpanel, _("Warning"))

        newpanel = DefaultActionPanel(self, id=wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        self.notebook_main.AddPage(newpanel, _("Default Actions"))

        newpanel = FormatterPanel(self, id=wx.ID_ANY, context=self.context)
        self.panels.append(newpanel)
        self.notebook_main.AddPage(newpanel, _("Display Options"))

        self.Layout()
        for panel in self.panels:
            self.add_module_delegate(panel)
        self.timer = Job(
            process=self.update_bit_info,
            job_name="balor-bit",
            interval=1.0,
            run_main=True,
        )
        self.restore_aspect()

    @property
    def test_pin(self):
        return self._test_pin

    @test_pin.setter
    def test_pin(self, value):
        self._test_pin = not self._test_pin
        if self._test_pin:
            self.context("red on\n")
        else:
            self.context("red off\n")

    @property
    def cor_wizard(self):
        return self._cor_wizard

    @cor_wizard.setter
    def cor_wizard(self, value):
        # Button-style choices only call setattr when the new value differs
        # from the cached one. Reset to False so the next click is always
        # detected as a transition False → True and fires the wizard.
        if value:
            self.context("window toggle CorWizard\n")
        self._cor_wizard = False

    def update_bit_info(self, *args):
        if not self.context.driver.connected:
            status = "busy"
        else:
            port_list = self.context.driver.connection.read_port()
            ports = port_list[1]
            status = ""
            line1 = ""
            line2 = ""
            for bit in range(16):
                line1 += f"{bit // 10}"
                line2 += f"{bit % 10}"
                if bool((1 << bit) & ports):
                    status += "x"
                else:
                    status += "-"
            # print (line1)
            # print (line2)
            # print (status)
        self.test_bits = status
        self.context.root.signal("test_bits", status, self)

    def window_close(self):
        for panel in self.panels:
            panel.pane_hide()
        self.context.kernel.unschedule(self.timer)

    def window_open(self):
        for panel in self.panels:
            panel.pane_show()
        self.context.kernel.schedule(self.timer)

    @signal_listener("balorpin")
    def on_pin_change(self, origina, *args):
        self.context.driver.connection.define_pins()

    @signal_listener("corfile")
    def on_corfile_changed(self, origin, *args):
        from meerk40t.balormk.controller import GalvoController

        if not self.context.corfile:
            return
        try:
            scale = GalvoController.get_scale_from_correction_file(self.context.corfile)
        except (FileNotFoundError, PermissionError, OSError):
            return
        self.context.lens_size = f"{65536.0 / scale:.03f}mm"
        self.context.signal("lens_size", self.context.lens_size, self.context)

    def window_preserve(self):
        return False

    def visible_choices(self, section):
        result = False
        devmode = self.context.root.setting(bool, "developer_mode", False)
        choices = self.context.lookup("choices", section)
        if choices is not None:
            for item in choices:
                try:
                    dummy = str(item["hidden"])
                    if dummy == "" or dummy == "0":
                        hidden = False
                    else:
                        hidden = False if devmode else True
                except KeyError:
                    hidden = False
                if not hidden:
                    result = True
                    break
        return result

    @staticmethod
    def submenu():
        # Hint for translation: _("Device-Settings"), _("Configuration")
        return "Device-Settings", "Configuration"

    @staticmethod
    def helptext():
        return _("Display and edit device configuration")

    @signal_listener("activate;device")
    def on_device_changes(self, *args):
        # Device activated, make sure we are still fine...
        if self.context.device.name != "balor":
            wx.CallAfter(self.Close)
