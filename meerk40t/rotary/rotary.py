from math import pi

from meerk40t.core.units import Length
from meerk40t.kernel import lookup_listener, signal_listener
from meerk40t.svgelements import Matrix


def plugin(service, lifecycle=None):
    if lifecycle == "plugins":
        from .gui import gui

        return [gui.plugin]
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
        service.add_service_delegate(Rotary(service, 0))


class Rotary:
    """
    Rotary Service provides rotary information about the selected rotary you intend to use.
    """

    def __init__(self, service, index=0, *args, **kwargs):
        self.index = index
        self.service = service
        self.service.rotary = self

        # Per-driver feature matrix.
        #  - supports_substitute: the driver can engage rotary by view-level
        #    rescaling of an existing axis (typically Y).
        #  - supports_dedicated: the driver implements rotary_move_* methods
        #    against a separate motor (e.g. galvo aux, GRBL Z/A).
        #  - axis_user_selectable: the driver lets the user pick which motor
        #    connector the rotary is wired to (currently GRBL only).
        driver_name = type(service).__name__.lower()
        if "balor" in driver_name:
            # Fiber/galvo: no X/Y stepper to remap; only the aux axis is
            # meaningful as a rotary.
            supports_substitute = False
            supports_dedicated = True
            axis_user_selectable = False
        elif "grbl" in driver_name:
            # GRBL: either swap Y with the rotary stepper, or wire it to a
            # dedicated stepper (Z/A/B/C). User chooses.
            supports_substitute = True
            supports_dedicated = True
            axis_user_selectable = True
        else:
            # Lihuiyu / Moshi / Newly: no aux axis in the driver, only
            # view-substitution is meaningful.
            supports_substitute = True
            supports_dedicated = False
            axis_user_selectable = False

        multi_mode = supports_substitute and supports_dedicated
        mode_default = "substitute" if supports_substitute else "dedicated"

        # Stash feature-matrix on the service so the GUI panel can inspect it
        # to decide which subsheets to display.
        service._rotary_supports_substitute = supports_substitute
        service._rotary_supports_dedicated = supports_dedicated
        service._rotary_multi_mode = multi_mode

        # If the device's persisted rotary_mode falls outside what this
        # driver supports (e.g. an old config that named a mode this driver
        # doesn't expose), pin it to a supported value before registration
        # so downstream checks don't see a stale state.
        existing_mode = getattr(service, "rotary_mode", None)
        if existing_mode is not None:
            if (existing_mode == "substitute" and not supports_substitute) or (
                existing_mode == "dedicated" and not supports_dedicated
            ):
                service.rotary_mode = mode_default

        _ = service._

        # The settings are split into three sheets so the GUI can show or
        # hide whole groups (rather than just enable/disable, which is all
        # ChoicePropertyPanel's `conditional` key supports). Each setting is
        # registered in exactly one sheet so attribute creation isn't doubled.
        common_choices = []
        substitute_choices = []
        dedicated_choices = []

        common_choices.append(
            {
                "attr": "rotary_active",
                "object": service,
                "default": False,
                "type": bool,
                "label": _("Rotary-Mode active"),
                "tip": _("Is the rotary mode active for this device"),
                "signals": "device;modified",
            }
        )

        if multi_mode:
            common_choices.append(
                {
                    "attr": "rotary_mode",
                    "object": service,
                    "default": mode_default,
                    "type": str,
                    "style": "combosmall",
                    "choices": ("substitute", "dedicated"),
                    "label": _("Rotary Mode"),
                    "tip": _(
                        "substitute: rotary replaces an existing motion axis "
                        "(geometry is rescaled at the view layer). "
                        "dedicated: rotary is a separate motor advanced "
                        "explicitly between strips; requires driver support."
                    ),
                    "signals": "device;modified",
                }
            )

        # ----- Substitute-mode settings (view-layer rescale) -----
        if supports_substitute:
            substitute_choices.extend(
                [
                    {
                        "attr": "rotary_scale_x",
                        "object": service,
                        "default": 1.0,
                        "type": float,
                        "label": _("X-Scale"),
                        "tip": _("Scale that needs to be applied to the X-Axis"),
                        "subsection": _("Scale"),
                    },
                    {
                        "attr": "rotary_scale_y",
                        "object": service,
                        "default": 1.0,
                        "type": float,
                        "label": _("Y-Scale"),
                        "tip": _("Scale that needs to be applied to the Y-Axis"),
                        "subsection": _("Scale"),
                    },
                    {
                        "attr": "rotary_flip_x",
                        "object": service,
                        "default": False,
                        "type": bool,
                        "label": _("Mirror X"),
                        "tip": _("Mirror the elements on the X-Axis"),
                        "subsection": _("Mirror Output"),
                    },
                    {
                        "attr": "rotary_flip_y",
                        "object": service,
                        "default": False,
                        "type": bool,
                        "label": _("Mirror Y"),
                        "tip": _("Mirror the elements on the Y-Axis"),
                        "subsection": _("Mirror Output"),
                    },
                ]
            )

        # ----- Dedicated-mode settings (hardware rotary motor) -----
        dedicated_chuck_choices = []
        dedicated_roller_choices = []
        if supports_dedicated:
            dedicated_choices.append(
                {
                    "attr": "rotary_type",
                    "object": service,
                    "default": "chuck",
                    "type": str,
                    "style": "combosmall",
                    "choices": ("chuck", "roller"),
                    "label": _("Rotary Type"),
                    "tip": _(
                        "chuck: motor is rigidly coupled to the object "
                        "(one motor rotation = one object rotation). "
                        "roller: motor turns rollers that spin the object via "
                        "friction (one motor rotation = one roller rotation)."
                    ),
                    "signals": "device;modified",
                }
            )
            dedicated_choices.append(
                {
                    "attr": "rotary_steps_per_rotation",
                    "object": service,
                    "default": 12800,
                    "type": int,
                    "label": _("Steps/Rotation"),
                    "tip": _(
                        "Motor steps required to complete one full rotation "
                        "of the rotary axis (chuck) or of the driven roller "
                        "(roller). Calibration: set so the Test button "
                        "completes exactly one revolution and returns."
                    ),
                }
            )
            # The two diameter fields live in their own sub-sheets so the
            # container panel can Show/Hide them based on rotary_type. Only
            # the active rotary type's diameter is meaningful for arc-length
            # math.
            dedicated_chuck_choices.append(
                {
                    "attr": "rotary_object_diameter",
                    "object": service,
                    "default": "50mm",
                    "type": Length,
                    "label": _("Object Diameter"),
                    "tip": _(
                        "Diameter of the object mounted in the chuck. Used "
                        "to convert design-space distances (mm) into arc "
                        "length on the object surface."
                    ),
                    "nonzero": True,
                }
            )
            dedicated_roller_choices.append(
                {
                    "attr": "rotary_roller_diameter",
                    "object": service,
                    "default": "30mm",
                    "type": Length,
                    "label": _("Roller Diameter"),
                    "tip": _(
                        "Diameter of the driven roller. Used to convert "
                        "design-space distances (mm) into motor steps: one "
                        "roller rotation moves the object surface by the "
                        "roller's circumference, regardless of object size."
                    ),
                    "nonzero": True,
                }
            )
            dedicated_choices.extend(
                [
                    {
                        "attr": "rotary_min_speed",
                        "object": service,
                        "default": 100,
                        "type": int,
                        "label": _("Min Speed"),
                        "tip": _("Minimum rotary motor speed (pulses/second)."),
                        "subsection": _("Motion"),
                    },
                    {
                        "attr": "rotary_max_speed",
                        "object": service,
                        "default": 5000,
                        "type": int,
                        "label": _("Max Speed"),
                        "tip": _("Maximum rotary motor speed (pulses/second)."),
                        "subsection": _("Motion"),
                    },
                    {
                        "attr": "rotary_accel_time",
                        "object": service,
                        "default": 100,
                        "type": int,
                        "label": _("Accel Time"),
                        "tip": _("Acceleration time in milliseconds."),
                        "subsection": _("Motion"),
                    },
                ]
            )
            if axis_user_selectable:
                dedicated_choices.append(
                    {
                        "attr": "rotary_axis_letter",
                        "object": service,
                        "default": "Z",
                        "type": str,
                        "style": "combosmall",
                        "choices": ("Y", "Z", "A", "B", "C"),
                        "label": _("Axis"),
                        "tip": _(
                            "Which motor axis drives the rotary. Note: Y is "
                            "typically used in 'substitute' mode; choose Z, A, "
                            "B, or C here only if the rotary has its own stepper."
                        ),
                    }
                )

        # suppress_home is mode-agnostic; lives at the bottom of the common
        # sheet so it's always visible (gated to active state via the
        # framework's enable conditional — disabled is fine for one checkbox).
        common_choices.append(
            {
                "attr": "suppress_home",
                "object": service,
                "default": False,
                "type": bool,
                "label": _("Ignore Home"),
                "tip": _("Ignore Home-Command"),
                "conditional": (service, "rotary_active"),
            }
        )

        service.register_choices("rotary_common", common_choices)
        if substitute_choices:
            service.register_choices("rotary_substitute", substitute_choices)
        if dedicated_choices:
            service.register_choices("rotary_dedicated", dedicated_choices)
        if dedicated_chuck_choices:
            service.register_choices(
                "rotary_dedicated_chuck", dedicated_chuck_choices
            )
        if dedicated_roller_choices:
            service.register_choices(
                "rotary_dedicated_roller", dedicated_roller_choices
            )

        @service.console_command(
            "rotary",
            help=_("Rotary base command"),
            output_type="rotary",
        )
        def rotary(command, channel, _, data=None, **kwargs):
            channel(
                f"Rotary {self.index} set to scale: {service.rotary_scale_x}, scale:{service.rotary_scale_y}"
            )
            return "rotary", None

        @service.console_command(
            "rotaryscale", help=_("Rotary Scale selected elements")
        )
        def apply_rotary_scale(*args, **kwargs):
            sx = service.rotary_scale_x
            sy = service.rotary_scale_y
            x, y = service.device.current
            matrix = Matrix(f"scale({sx}, {sy}, {x}, {y})")
            for node in service.elements.elems():
                if hasattr(node, "rotary_scale"):
                    # This element is already scaled
                    return
                try:
                    node.rotary_scale = sx, sy
                    node.matrix *= matrix
                    node.modified()
                except AttributeError:
                    pass

        # ------------------------------------------------------------------
        # Driver-agnostic rotary motion commands.
        #
        # These dispatch through `hasattr` checks to optional methods on
        # `service.driver` (rotary_move_to, rotary_move_relative,
        # rotary_position, rotary_wait, rotary_set_origin,
        # rotary_capabilities). Drivers without hardware rotary support are
        # told so and the commands no-op gracefully.
        # ------------------------------------------------------------------

        def _require_driver_method(method_name, channel):
            driver = getattr(service, "driver", None)
            if driver is None or not hasattr(driver, method_name):
                channel(
                    _("Rotary motion not supported by this device's driver.")
                )
                return None
            # Drivers that advertise capabilities use that as the truth:
            # a None return means the driver is currently configured for a
            # mode that doesn't accept rotary motor commands (e.g. balor
            # left in 'substitute' mode). Drivers without capabilities()
            # are assumed always-on for back-compat.
            if hasattr(driver, "rotary_capabilities"):
                if driver.rotary_capabilities() is None:
                    channel(
                        _(
                            "Rotary is not in dedicated-axis mode; set "
                            "rotary_mode to 'dedicated' before using motor commands."
                        )
                    )
                    return None
            return driver

        def _parse_rotary_distance(text, channel):
            """
            Parse a rotary distance into motor steps using the active
            service's calibration settings.

            Accepted forms (case-insensitive):
              * raw integer / negative integer  → motor steps as-is
              * trailing 'steps'                → motor steps
              * trailing 'r' or 'rev'           → revolutions
              * trailing 'deg' or '°'           → degrees
              * any other Length string         → arc length on object surface
            """
            if text is None:
                channel(_("Distance required."))
                return None
            raw = str(text).strip().lower()
            if not raw:
                channel(_("Distance required."))
                return None
            spr = getattr(service, "rotary_steps_per_rotation", 12800) or 1

            try:
                # Pure integer (possibly signed) → motor steps.
                return int(raw)
            except ValueError:
                pass

            for suffix in ("steps", "step"):
                if raw.endswith(suffix):
                    try:
                        return int(float(raw[: -len(suffix)].strip()))
                    except ValueError:
                        channel(_("Invalid step count: %s") % text)
                        return None
            for suffix in ("rev", "r"):
                if raw.endswith(suffix):
                    try:
                        return int(round(float(raw[: -len(suffix)].strip()) * spr))
                    except ValueError:
                        channel(_("Invalid revolutions: %s") % text)
                        return None
            for suffix in ("deg", "°"):
                if raw.endswith(suffix):
                    try:
                        return int(
                            round(float(raw[: -len(suffix)].strip()) / 360.0 * spr)
                        )
                    except ValueError:
                        channel(_("Invalid degrees: %s") % text)
                        return None

            # Length: convert arc length along object surface to steps.
            #
            # Which diameter we use depends on the rotary type:
            #  - chuck: motor drives the object directly. One motor rotation
            #    moves the object surface by the object's circumference.
            #  - roller: motor drives the rollers; the object rides on them.
            #    One motor rotation moves the contact point by the *roller's*
            #    circumference (and the object surface tracks that, slip-free).
            try:
                length_mm = Length(text).mm
            except Exception:
                channel(_("Unable to parse rotary distance: %s") % text)
                return None
            rtype = getattr(service, "rotary_type", "chuck")
            if rtype == "roller":
                diameter_attr = "rotary_roller_diameter"
                missing_msg = _(
                    "Rotary roller diameter is not set; cannot convert arc length."
                )
                invalid_msg = _("Rotary roller diameter must be greater than zero.")
            else:
                diameter_attr = "rotary_object_diameter"
                missing_msg = _(
                    "Rotary object diameter is not set; cannot convert arc length."
                )
                invalid_msg = _("Rotary object diameter must be greater than zero.")
            diameter_value = getattr(service, diameter_attr, None)
            if diameter_value is None:
                channel(missing_msg)
                return None
            try:
                diameter_mm = Length(diameter_value).mm
            except Exception:
                channel(missing_msg)
                return None
            if diameter_mm <= 0:
                channel(invalid_msg)
                return None
            circumference_mm = diameter_mm * pi
            return int(round(length_mm / circumference_mm * spr))

        def _steps_to_degrees(steps):
            spr = getattr(service, "rotary_steps_per_rotation", 12800) or 1
            return steps * 360.0 / spr

        @service.console_command(
            "rotary_capabilities",
            help=_("Report rotary capabilities advertised by the active driver."),
        )
        def rotary_capabilities(command, channel, _, **kwargs):
            driver = getattr(service, "driver", None)
            if driver is None or not hasattr(driver, "rotary_capabilities"):
                channel(_("This driver does not advertise rotary support."))
                return
            caps = driver.rotary_capabilities()
            if not caps:
                channel(_("Driver reports no rotary capabilities."))
                return
            channel(_("Rotary capabilities:"))
            for key, value in caps.items():
                channel(f"  {key}: {value}")

        @service.console_argument(
            "delta",
            type=str,
            help=_(
                "Distance to advance (e.g. 5mm, 0.25r, 90deg, or raw step count)."
            ),
        )
        @service.console_option(
            "speed", "s", type=int, help=_("Maximum motor speed override.")
        )
        @service.console_command(
            "rotary_jog",
            help=_("Advance the rotary by a relative amount."),
        )
        def rotary_jog(
            command, channel, _, delta=None, speed=None, **kwargs
        ):
            driver = _require_driver_method("rotary_move_relative", channel)
            if driver is None:
                return
            steps = _parse_rotary_distance(delta, channel)
            if steps is None:
                return
            driver.rotary_move_relative(steps, speed=speed)
            if hasattr(driver, "rotary_wait"):
                driver.rotary_wait()
            channel(
                _("Rotary advanced by {steps} steps (~{deg:.2f}°).").format(
                    steps=steps, deg=_steps_to_degrees(steps)
                )
            )

        @service.console_argument(
            "position",
            type=str,
            help=_("Absolute target (same units as rotary_jog)."),
        )
        @service.console_option(
            "speed", "s", type=int, help=_("Maximum motor speed override.")
        )
        @service.console_command(
            "rotary_to",
            help=_("Move the rotary to an absolute position."),
        )
        def rotary_to(
            command, channel, _, position=None, speed=None, **kwargs
        ):
            driver = _require_driver_method("rotary_move_to", channel)
            if driver is None:
                return
            steps = _parse_rotary_distance(position, channel)
            if steps is None:
                return
            driver.rotary_move_to(steps, speed=speed)
            if hasattr(driver, "rotary_wait"):
                driver.rotary_wait()
            channel(
                _("Rotary moved to {steps} steps (~{deg:.2f}°).").format(
                    steps=steps, deg=_steps_to_degrees(steps)
                )
            )

        @service.console_command(
            "rotary_pos",
            help=_("Print the current rotary axis position."),
        )
        def rotary_pos(command, channel, _, **kwargs):
            driver = _require_driver_method("rotary_position", channel)
            if driver is None:
                return
            current = driver.rotary_position()
            if current is None:
                channel(_("Rotary position unavailable (not connected?)."))
                return
            channel(
                _("Rotary position: {steps} steps (~{deg:.2f}°).").format(
                    steps=current, deg=_steps_to_degrees(current)
                )
            )

        @service.console_command(
            "rotary_zero",
            help=_(
                "Set the current rotary position as the origin (driver-dependent)."
            ),
        )
        def rotary_zero(command, channel, _, **kwargs):
            driver = _require_driver_method("rotary_set_origin", channel)
            if driver is None:
                return
            driver.rotary_set_origin()
            channel(_("Rotary origin set."))

        @service.console_command(
            "rotary_test",
            help=_(
                "Calibration test: rotate one full revolution then return to start."
            ),
        )
        def rotary_test(command, channel, _, **kwargs):
            driver = _require_driver_method("rotary_move_relative", channel)
            if driver is None:
                return
            spr = getattr(service, "rotary_steps_per_rotation", 12800)
            channel(
                _(
                    "Rotary test: rotating +{n} steps (one revolution) then back."
                ).format(n=spr)
            )
            driver.rotary_move_relative(spr)
            if hasattr(driver, "rotary_wait"):
                driver.rotary_wait()
            driver.rotary_move_relative(-spr)
            if hasattr(driver, "rotary_wait"):
                driver.rotary_wait()
            channel(_("Rotary test complete."))

    # These convenience accessors are called by other parts of the codebase
    # (drivers, GUI). They must tolerate missing attributes because, for any
    # given driver, only one mode's settings get registered — the other
    # mode's settings (rotary_scale_*, rotary_flip_*, etc.) never become
    # attributes on the service. They also have to tolerate evaluation
    # during the kernel's _lookup_attach pass, which does getattr() on
    # every property on the object.

    @property
    def scale_x(self):
        return getattr(self.service, "rotary_scale_x", 1.0)

    @property
    def scale_y(self):
        return getattr(self.service, "rotary_scale_y", 1.0)

    @property
    def active(self):
        return getattr(self.service, "rotary_active", False)

    @property
    def flip_x(self):
        return getattr(self.service, "rotary_flip_x", False)

    @property
    def flip_y(self):
        return getattr(self.service, "rotary_flip_y", False)

    @property
    def suppress_home(self):
        return getattr(self.service, "suppress_home", False)

    @lookup_listener("service/device/active")
    @signal_listener("rotary_scale_x")
    @signal_listener("rotary_scale_y")
    @signal_listener("rotary_active")
    @signal_listener("rotary_flip_x")
    @signal_listener("rotary_flip_y")
    def rotary_settings_changed(self, origin=None, *args):
        """
        Rotary settings were changed. We force the current device to realize

        @param origin:
        @param args:
        @return:
        """
        if origin is not None and origin != self.service.path:
            return
        device = self.service.device
        device.realize()

    @signal_listener("view;realized")
    def realize(self, origin=None, *args):
        """
        Realization of current device requires that device to be additionally updated with rotary
        @param origin:
        @param args:
        @return:
        """
        if not self.service.rotary_active:
            return
        # View-substitution rotary rescales the device view so geometry maps
        # onto the cylinder. Dedicated-axis rotary moves a separate motor
        # between strips, leaving the view untouched.
        if getattr(self.service, "rotary_mode", "substitute") != "substitute":
            return
        device = self.service.device
        device.view.scale(self.service.rotary_scale_x, self.service.rotary_scale_y)
        if self.service.rotary_flip_x:
            device.view.flip_x()
        if self.service.rotary_flip_y:
            device.view.flip_y()

    def service_detach(self, *args, **kwargs):
        pass

    def service_attach(self, *args, **kwargs):
        pass

    def shutdown(self, *args, **kwargs):
        pass
