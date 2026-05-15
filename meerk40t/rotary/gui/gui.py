ROTARY_VIEW = False


def plugin(service, lifecycle):
    if lifecycle == "cli":
        service.set_feature("rotary")
    if lifecycle == "invalidate":
        return not service.has_feature("wx")
    if lifecycle == "service":
        # Responding to "service" makes this a service plugin for the specific services created via the provider
        # We are only a provider of lhystudios devices for now.
        return (
            "provider/device/lhystudios",
            "provider/device/grbl",
            "provider/device/balor",
            "provider/device/newly",
            "provider/device/moshi",
        )
    elif lifecycle == "added":
        from meerk40t.gui.icons import icon_rotary
        from meerk40t.rotary.gui.rotarysettings import RotarySettings

        _ = service._

        # Settings window is meaningful for every rotary-capable device, since
        # both view-substitution and dedicated-axis rotaries get configured
        # there.
        service.register("window/Rotary", RotarySettings)
        service.register(
            "button/device/Rotary",
            {
                "label": _("Rotary"),
                "icon": icon_rotary,
                "tip": _("Opens Rotary Window"),
                "action": lambda v: service.console("window toggle Rotary\n"),
            },
        )

        # The jog/control window only does anything on drivers that actually
        # implement rotary_move_* methods (currently only balor; GRBL is
        # next). Don't clutter other devices' menus with a button that would
        # always say "unsupported".
        driver_name = type(service).__name__.lower()
        if "balor" in driver_name or "grbl" in driver_name:
            from meerk40t.rotary.gui.rotarycontrol import RotaryControlWindow

            service.register("window/RotaryControl", RotaryControlWindow)
            service.register(
                "button/device/RotaryControl",
                {
                    "label": _("Rotary Jog"),
                    "icon": icon_rotary,
                    "tip": _("Opens the rotary jog/control window."),
                    "action": lambda v: service.console(
                        "window toggle RotaryControl\n"
                    ),
                },
            )

        @service.console_command("rotaryview", help=_("Rotary View of Scene"))
        def toggle_rotary_view(*args, **kwargs):
            """
            Rotary Stretch/Unstretch of Scene based on values in rotary service
            """
            global ROTARY_VIEW
            rotary = service.rotary
            if ROTARY_VIEW:
                rotary(f"scene aspect {rotary.scale_x} {rotary.scale_y}\n")
            else:
                try:
                    rotary(
                        f"scene aspect {1.0 / rotary.scale_x} {1.0 / rotary.scale_y}\n"
                    )
                except ZeroDivisionError:
                    pass
            ROTARY_VIEW = not ROTARY_VIEW
