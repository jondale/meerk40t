"""
Cor-file generator wizard for the BJJCZ/JCZ galvo controller.

Self-contained: defines its own calibration pattern, its own measurement-entry
UI, and writes a real ``.cor`` file via ``balormk.cor_writer``.

Workflow:
    1. Intro       — explain process, confirm lens size.
    2. Burn        — confirm and fire calibration pattern via the standard
                     ``service.spooler.laserjob`` path.
    3. Orientation — pick which of 4 rotations / mirrors the burn matches.
    4. Measure     — enter 12 segment lengths in the 3x3 grid layout.
    5. Save        — write .cor, assign it to the device, enable corfile.

This module never registers a console command; it only registers a window via
``service.register("window/CorWizard", ...)``, opened with the standard
``window toggle CorWizard`` machinery from the config dialog button. That keeps
console / driver code free of any GUI dependency.
"""

import os
from datetime import datetime

import wx

from meerk40t.balormk.cor_writer import (
    default_cor_directory,
    generate_table_from_9_point,
    write_cor_file,
)
from meerk40t.core.geomstr import Geomstr
from meerk40t.gui.icons import icons8_detective
from meerk40t.gui.mwindow import MWindow

_ = wx.GetTranslation


# Pattern half-span as a fraction of the galvo half-field. 0x6666 / 0x7FFF ≈
# 80% means corners sit ~10% in from the field edge, providing safety margin.
# Nominal segment length (per half edge) is lens_size_mm * BURN_HALF_SPAN.
PATTERN_HALF_SPAN_GALVO = 0x6666
GALVO_HALF_FIELD = 0x7FFF
BURN_HALF_SPAN = PATTERN_HALF_SPAN_GALVO / float(GALVO_HALF_FIELD * 2)


def nominal_segment_mm(lens_size_mm: float) -> float:
    return float(lens_size_mm) * BURN_HALF_SPAN


# Calibration pattern: outer square + center cross + orientation markers
# (square top-left, diamond bottom-right).
def calibration_geometry() -> Geomstr:
    path = Geomstr()
    m = 0x7FFF
    s = PATTERN_HALF_SPAN_GALVO

    def c(x, y):
        return complex(m + (s * x), m + (s * y))

    # Outer square (corners are the 4 corner anchors of the 3x3 grid).
    path.line(c(-1, -1), c(1, -1))
    path.line(c(1, -1), c(1, 1))
    path.line(c(1, 1), c(-1, 1))
    path.line(c(-1, 1), c(-1, -1))

    # Center cross (segments split at center so each half is measurable).
    path.line(c(-1, 0), c(0, 0))
    path.line(c(0, 0), c(1, 0))
    path.line(c(0, -1), c(0, 0))
    path.line(c(0, 0), c(0, 1))

    # Orientation marker: small filled square at TOP-LEFT (using -1, -1 in
    # screen-up-positive convention; if you're seeing it bottom-right after
    # burning, your output is mirrored — handled by the Orientation page).
    path.line(c(-0.95, -0.95), c(-0.75, -0.95))
    path.line(c(-0.75, -0.95), c(-0.75, -0.75))
    path.line(c(-0.75, -0.75), c(-0.95, -0.75))
    path.line(c(-0.95, -0.75), c(-0.95, -0.95))

    # Orientation marker: small diamond at BOTTOM-RIGHT.
    path.line(c(0.85, 0.95), c(0.95, 0.85))
    path.line(c(0.95, 0.85), c(0.85, 0.75))
    path.line(c(0.85, 0.75), c(0.75, 0.85))
    path.line(c(0.75, 0.85), c(0.85, 0.95))

    path.settings(
        0,
        {
            "power": 1000,
            "delay_laser_on": 100,
            "delay_laser_off": 100,
            "delay_laser_polygon": 100,
            "speed": 255,
            "rapid_speed": 255,
            "timing_enabled": True,
        },
    )
    return path


# Twelve measurement segments. Each entry: (label, ai_from, aj_from, ai_to, aj_to,
# axis) where axis is "x" or "y" indicating which component the measurement
# constrains. The measurement is the distance between the two anchors as
# burned.
MEASUREMENTS = [
    # Top edge: NW->N, N->NE
    ("Top edge, left half (NW→N)", -1, 1, 0, 1, "x"),
    ("Top edge, right half (N→NE)", 0, 1, 1, 1, "x"),
    # Right edge: NE->E, E->SE
    ("Right edge, top half (NE→E)", 1, 1, 1, 0, "y"),
    ("Right edge, bottom half (E→SE)", 1, 0, 1, -1, "y"),
    # Bottom edge: SE->S, S->SW
    ("Bottom edge, right half (SE→S)", 1, -1, 0, -1, "x"),
    ("Bottom edge, left half (S→SW)", 0, -1, -1, -1, "x"),
    # Left edge: SW->W, W->NW
    ("Left edge, bottom half (SW→W)", -1, -1, -1, 0, "y"),
    ("Left edge, top half (W→NW)", -1, 0, -1, 1, "y"),
    # Center horizontal: W->C, C->E
    ("Center horizontal, left half (W→C)", -1, 0, 0, 0, "x"),
    ("Center horizontal, right half (C→E)", 0, 0, 1, 0, "x"),
    # Center vertical: S->C, C->N
    ("Center vertical, bottom half (S→C)", 0, -1, 0, 0, "y"),
    ("Center vertical, top half (C→N)", 0, 0, 0, 1, "y"),
]


class _PageBase(wx.Panel):
    """Common base for wizard pages."""

    def __init__(self, parent, wizard):
        super().__init__(parent)
        self.wizard = wizard

    def on_enter(self):
        """Called when the page becomes visible. Override as needed."""

    def on_leave(self) -> bool:
        """Called before advancing. Return False to block navigation."""
        return True


class PatternPreview(wx.Panel):
    """
    Owner-drawn preview of the calibration pattern. Mirrors the geometry that
    ``calibration_geometry()`` emits so the user sees what will be burned.

    ``flip_x`` / ``flip_y`` / ``swap_xy`` apply a coordinate transform to the
    drawn pattern (used by the orientation page to show the 4 possible
    rotations / mirrors of the burn).

    Set ``annotate=True`` (the default) to print "top-left" / "bottom-right"
    labels next to the orientation markers. Off for small thumbnails where
    the labels would be illegible.

    ``selectable=True`` makes the preview clickable; clicking fires a
    ``wx.EVT_LEFT_DOWN`` that the page handler interprets as a radio-style
    selection. ``selected=True`` draws a highlighted border.
    """

    def __init__(
        self,
        parent,
        size=(260, 260),
        flip_x=False,
        flip_y=False,
        swap_xy=False,
        annotate=True,
        selectable=False,
    ):
        super().__init__(parent, size=size, style=wx.BORDER_SIMPLE)
        # Required by wx.AutoBufferedPaintDC on GTK/wxWidgets 3.2+; we paint
        # the full client area in _on_paint, so no system erase is needed.
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.flip_x = flip_x
        self.flip_y = flip_y
        self.swap_xy = swap_xy
        self.annotate = annotate
        self.selectable = selectable
        self.selected = False
        self.Bind(wx.EVT_PAINT, self._on_paint)
        if selectable:
            self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetMinSize(size)

    def set_selected(self, value: bool):
        if self.selected != value:
            self.selected = value
            self.Refresh()

    def _on_paint(self, event):
        w, h = self.GetClientSize()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()

        # Reserve a margin so the pattern doesn't touch the panel border.
        margin = 16
        size = min(w, h) - 2 * margin
        cx = w / 2
        cy = h / 2
        span = size / 2

        def p(x, y):
            if self.swap_xy:
                x, y = y, x
            if self.flip_x:
                x = -x
            if self.flip_y:
                y = -y
            return (int(round(cx + x * span)), int(round(cy + y * span)))

        pen = wx.Pen(wx.BLACK, 1)
        dc.SetPen(pen)

        # Outer square
        dc.DrawLine(*p(-1, -1), *p(1, -1))
        dc.DrawLine(*p(1, -1), *p(1, 1))
        dc.DrawLine(*p(1, 1), *p(-1, 1))
        dc.DrawLine(*p(-1, 1), *p(-1, -1))

        # Center cross
        dc.DrawLine(*p(-1, 0), *p(1, 0))
        dc.DrawLine(*p(0, -1), *p(0, 1))

        # Top-left square marker (in unflipped coordinates)
        dc.DrawLine(*p(-0.95, -0.95), *p(-0.75, -0.95))
        dc.DrawLine(*p(-0.75, -0.95), *p(-0.75, -0.75))
        dc.DrawLine(*p(-0.75, -0.75), *p(-0.95, -0.75))
        dc.DrawLine(*p(-0.95, -0.75), *p(-0.95, -0.95))

        # Bottom-right diamond marker (in unflipped coordinates)
        dc.DrawLine(*p(0.85, 0.95), *p(0.95, 0.85))
        dc.DrawLine(*p(0.95, 0.85), *p(0.85, 0.75))
        dc.DrawLine(*p(0.85, 0.75), *p(0.75, 0.85))
        dc.DrawLine(*p(0.75, 0.85), *p(0.85, 0.95))

        if self.annotate:
            font = wx.Font(
                8,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_ITALIC,
                wx.FONTWEIGHT_NORMAL,
            )
            dc.SetFont(font)
            dc.SetTextForeground(wx.Colour(0x80, 0x80, 0x80))
            label_tl = _("top-left")
            label_br = _("bottom-right")
            tw, _th = dc.GetTextExtent(label_tl)
            dc.DrawText(
                label_tl,
                int(p(-0.85, -0.65)[0] - tw / 2),
                int(p(0, -0.65)[1]),
            )
            tw, th = dc.GetTextExtent(label_br)
            dc.DrawText(
                label_br,
                int(p(0.85, 0.65)[0] - tw / 2),
                int(p(0, 0.65)[1] - th),
            )

        if self.selected:
            # Highlight the selected thumbnail with a thick blue border just
            # inside the panel edge.
            dc.SetPen(wx.Pen(wx.Colour(0x20, 0x80, 0xE0), 3))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(1, 1, w - 2, h - 2)


class IntroPage(_PageBase):
    def __init__(self, parent, wizard):
        super().__init__(parent, wizard)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=_("Correction File Generator"))
        title.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        sizer.Add(title, 0, wx.ALL, 8)
        info = wx.StaticText(
            self,
            label=_(
                "This wizard generates a .cor lens-correction file from a "
                "9-point calibration burn.\n\n"
                "You will:\n"
                "  1. Burn a calibration pattern on contrasting material.\n"
                "  2. Identify the orientation of the burned pattern.\n"
                "  3. Measure 12 segments with calipers.\n"
                "  4. Save the generated .cor file and assign it to this device.\n\n"
                "Confirm the field size below before continuing."
            ),
        )
        info.Wrap(560)
        sizer.Add(info, 0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label=_("Lens field size (mm):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.lens_ctrl = wx.TextCtrl(self, value="110", size=(80, -1))
        row.Add(self.lens_ctrl, 0, wx.ALL, 4)
        sizer.Add(row, 0, wx.ALL, 8)
        self.SetSizer(sizer)

    def on_enter(self):
        try:
            self.lens_ctrl.SetValue(str(self.wizard.service.lens_size))
        except Exception:
            pass

    def on_leave(self) -> bool:
        raw = self.lens_ctrl.GetValue().strip()
        try:
            # Accept "110", "110mm", "4.3in" — convert via Length.
            from meerk40t.core.units import Length

            ln = Length(raw)
            mm = float(ln.mm)
        except Exception:
            wx.MessageBox(
                _("Could not parse lens size — enter a value like '110mm' or '110'."),
                _("Invalid value"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return False
        if mm <= 0:
            wx.MessageBox(
                _("Lens size must be positive."),
                _("Invalid value"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return False
        self.wizard.lens_size_mm = mm
        return True


class BurnPage(_PageBase):
    def __init__(self, parent, wizard):
        super().__init__(parent, wizard)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=_("Burn Calibration Pattern"))
        title.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        sizer.Add(title, 0, wx.ALL, 8)
        info = wx.StaticText(
            self,
            label=_(
                "Place high-contrast material covering the full lens field. "
                "The pattern below is what will be burned — note the small "
                "square at top-left and diamond at bottom-right; you'll use "
                "those on the next page to identify burn orientation."
            ),
        )
        info.Wrap(560)
        sizer.Add(info, 0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.AddStretchSpacer(1)
        row.Add(PatternPreview(self), 0, wx.ALL, 8)
        row.AddStretchSpacer(1)
        sizer.Add(row, 0, wx.EXPAND)

        self.burn_btn = wx.Button(self, label=_("Burn Pattern"))
        self.burn_btn.Bind(wx.EVT_BUTTON, self.on_burn)
        sizer.Add(self.burn_btn, 0, wx.ALL, 8)

        self.status = wx.StaticText(self, label="")
        sizer.Add(self.status, 0, wx.ALL, 8)
        self.SetSizer(sizer)

    def on_burn(self, event):
        if (
            wx.MessageBox(
                _(
                    "Ready to fire the laser? Make sure the lid is closed, "
                    "the material is positioned, and the focus is set."
                ),
                _("Confirm Burn"),
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            != wx.YES
        ):
            return
        try:
            geom = calibration_geometry()
            self.wizard.service.spooler.laserjob([geom])
            self.status.SetLabel(
                _("Pattern sent to spooler. Wait for completion, then continue.")
            )
        except Exception as exc:
            self.status.SetLabel(_("Burn failed: {err}").format(err=exc))


# Four orientation choices. Each is a (label, swap_xy, flip_x, flip_y) tuple
# describing how to remap a measurement entry's (ai, aj) coordinate to the
# burned pattern's actual orientation.
ORIENTATIONS = [
    (_("Top-left square, bottom-right diamond (no flip)"), False, False, False),
    (_("Top-right square, bottom-left diamond (mirrored X)"), False, True, False),
    (_("Bottom-left square, top-right diamond (mirrored Y)"), False, False, True),
    (_("Bottom-right square, top-left diamond (rotated 180°)"), False, True, True),
]


class OrientationPage(_PageBase):
    def __init__(self, parent, wizard):
        super().__init__(parent, wizard)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=_("Identify Burn Orientation"))
        title.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        sizer.Add(title, 0, wx.ALL, 8)
        info = wx.StaticText(
            self,
            label=_(
                "Look at the burned pattern with the laser bed oriented "
                "normally. Click the thumbnail that matches what you see."
            ),
        )
        info.Wrap(560)
        sizer.Add(info, 0, wx.ALL, 8)

        # 2x2 grid of thumbnails, one per orientation.
        grid = wx.GridSizer(rows=2, cols=2, hgap=12, vgap=12)
        self.previews = []
        for idx, (label, swap, flip_x, flip_y) in enumerate(ORIENTATIONS):
            col = wx.BoxSizer(wx.VERTICAL)
            preview = PatternPreview(
                self,
                size=(140, 140),
                flip_x=flip_x,
                flip_y=flip_y,
                swap_xy=swap,
                annotate=False,
                selectable=True,
            )
            preview.Bind(wx.EVT_LEFT_DOWN, lambda e, i=idx: self._select(i))
            self.previews.append(preview)
            col.Add(preview, 0, wx.ALIGN_CENTER_HORIZONTAL)
            caption = wx.StaticText(self, label=label)
            caption.Wrap(160)
            col.Add(caption, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP, 4)
            grid.Add(col, 0, wx.ALIGN_CENTER)
        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 8)

        self.selected_index = 0
        self.previews[0].set_selected(True)
        self.SetSizer(sizer)

    def _select(self, idx):
        for i, p in enumerate(self.previews):
            p.set_selected(i == idx)
        self.selected_index = idx

    def on_leave(self) -> bool:
        _label, swap, flip_x, flip_y = ORIENTATIONS[self.selected_index]
        self.wizard.orient_swap_xy = swap
        self.wizard.orient_flip_x = flip_x
        self.wizard.orient_flip_y = flip_y
        return True


class MeasurementCanvas(wx.Panel):
    """
    Pattern preview with the 12 measurement TextCtrls overlaid at the
    midpoint of each segment. The pattern is drawn with the wizard's
    orientation flags applied so it matches the burn the user is looking at.
    """

    ENTRY_SIZE = (60, 24)

    def __init__(self, parent, wizard, size=(460, 460)):
        super().__init__(parent, size=size, style=wx.BORDER_SIMPLE)
        self.wizard = wizard
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize(size)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        # Create 12 entries as children of this panel; positioned on layout.
        self.entries = []
        for label, *_rest in MEASUREMENTS:
            entry = wx.TextCtrl(
                self, size=self.ENTRY_SIZE, style=wx.TE_CENTRE
            )
            entry.SetToolTip(label)
            self.entries.append(entry)

    def _on_size(self, event):
        self._reposition_entries()
        self.Refresh()
        event.Skip()

    def _coord_funcs(self):
        """Return (p, cx, cy, span) for the current panel size."""
        w, h = self.GetClientSize()
        margin = 36
        size = min(w, h) - 2 * margin
        cx = w / 2
        cy = h / 2
        span = size / 2

        def p(x, y):
            # Apply orientation in the same way as PatternPreview so the
            # pattern and entry positions agree.
            if self.wizard.orient_swap_xy:
                x, y = y, x
            if self.wizard.orient_flip_x:
                x = -x
            if self.wizard.orient_flip_y:
                y = -y
            return (int(round(cx + x * span)), int(round(cy + y * span)))

        return p, cx, cy, span

    def _reposition_entries(self):
        p, _cx, _cy, _span = self._coord_funcs()
        ew, eh = self.ENTRY_SIZE
        for entry, (_label, ai_from, aj_from, ai_to, aj_to, _axis) in zip(
            self.entries, MEASUREMENTS
        ):
            # MEASUREMENTS uses cartographic aj-up; pattern drawing uses
            # screen y-down. Negate aj to bridge conventions before passing
            # through p() (which applies orientation flips).
            mid_x = (ai_from + ai_to) / 2.0
            mid_y = -(aj_from + aj_to) / 2.0
            sx, sy = p(mid_x, mid_y)
            entry.SetPosition((sx - ew // 2, sy - eh // 2))

    def _on_paint(self, event):
        w, h = self.GetClientSize()
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.WHITE))
        dc.Clear()

        p, _cx, _cy, _span = self._coord_funcs()
        dc.SetPen(wx.Pen(wx.BLACK, 1))

        # Outer square
        dc.DrawLine(*p(-1, -1), *p(1, -1))
        dc.DrawLine(*p(1, -1), *p(1, 1))
        dc.DrawLine(*p(1, 1), *p(-1, 1))
        dc.DrawLine(*p(-1, 1), *p(-1, -1))
        # Center cross
        dc.DrawLine(*p(-1, 0), *p(1, 0))
        dc.DrawLine(*p(0, -1), *p(0, 1))
        # Top-left square marker (in unflipped/canonical coords)
        dc.DrawLine(*p(-0.95, -0.95), *p(-0.75, -0.95))
        dc.DrawLine(*p(-0.75, -0.95), *p(-0.75, -0.75))
        dc.DrawLine(*p(-0.75, -0.75), *p(-0.95, -0.75))
        dc.DrawLine(*p(-0.95, -0.75), *p(-0.95, -0.95))
        # Bottom-right diamond marker
        dc.DrawLine(*p(0.85, 0.95), *p(0.95, 0.85))
        dc.DrawLine(*p(0.95, 0.85), *p(0.85, 0.75))
        dc.DrawLine(*p(0.85, 0.75), *p(0.75, 0.85))
        dc.DrawLine(*p(0.75, 0.85), *p(0.85, 0.95))

    def populate_defaults(self, nominal: float):
        # Preserve any previously entered values; only fill blanks.
        text = f"{nominal:.2f}"
        for entry in self.entries:
            if not entry.GetValue().strip():
                entry.SetValue(text)
        self._reposition_entries()
        self.Refresh()

    def read_values(self):
        return [entry.GetValue().strip() for entry in self.entries]


class MeasurePage(_PageBase):
    def __init__(self, parent, wizard):
        super().__init__(parent, wizard)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=_("Enter Measurements"))
        title.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        sizer.Add(title, 0, wx.ALL, 8)
        info = wx.StaticText(
            self,
            label=_(
                "Measure each line segment of the burned pattern with calipers "
                "and type its length (mm) in the box on top of that segment. "
                "Hover for the segment name. Values much smaller or larger "
                "than nominal usually mean the wrong segment was measured."
            ),
        )
        info.Wrap(560)
        sizer.Add(info, 0, wx.ALL, 8)

        self.nominal_label = wx.StaticText(self, label="")
        sizer.Add(self.nominal_label, 0, wx.ALL, 4)

        self.canvas = MeasurementCanvas(self, wizard)
        sizer.Add(self.canvas, 1, wx.ALIGN_CENTER | wx.ALL, 8)
        self.SetSizer(sizer)

    def on_enter(self):
        nominal = nominal_segment_mm(self.wizard.lens_size_mm)
        self.nominal_label.SetLabel(
            _("Nominal segment length: {n:.2f} mm").format(n=nominal)
        )
        # Orientation may have changed since last visit; reposition + repaint.
        self.canvas.populate_defaults(nominal)

    def on_leave(self) -> bool:
        nominal = nominal_segment_mm(self.wizard.lens_size_mm)
        # Each segment measurement constrains the component of whichever
        # endpoint is *further* from the center anchor (L1 norm).
        # cor_writer.generate_table_from_9_point keys measurements by that
        # outer anchor, with (mx, my) holding the measured distances from
        # the next-inward anchor along the row / column.
        measurements = {}
        raw_values = self.canvas.read_values()
        for idx, (label, ai_from, aj_from, ai_to, aj_to, axis) in enumerate(
            MEASUREMENTS
        ):
            raw = raw_values[idx]
            try:
                val = float(raw)
            except ValueError:
                wx.MessageBox(
                    _("Could not parse value for: {label}").format(label=label),
                    _("Invalid value"),
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                return False
            from_l1 = abs(ai_from) + abs(aj_from)
            to_l1 = abs(ai_to) + abs(aj_to)
            outer = (ai_from, aj_from) if from_l1 >= to_l1 else (ai_to, aj_to)
            mx, my = measurements.get(outer, (nominal, nominal))
            if axis == "x":
                mx = val
            else:
                my = val
            measurements[outer] = (mx, my)
        # Apply orientation correction by remapping anchor keys to the
        # canonical wizard frame (top-left square / bottom-right diamond).
        remapped = {}
        for (ai, aj), val in measurements.items():
            ri = -ai if self.wizard.orient_flip_x else ai
            rj = -aj if self.wizard.orient_flip_y else aj
            if self.wizard.orient_swap_xy:
                ri, rj = rj, ri
            remapped[(ri, rj)] = val
        self.wizard.measurements = remapped
        return True


class SavePage(_PageBase):
    def __init__(self, parent, wizard):
        super().__init__(parent, wizard)
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=_("Save and Apply"))
        title.SetFont(
            wx.Font(
                14,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        sizer.Add(title, 0, wx.ALL, 8)
        info = wx.StaticText(
            self,
            label=_(
                "The .cor file will be written to the path below and then "
                "assigned to this device (corfile_enabled will be turned on)."
            ),
        )
        info.Wrap(560)
        sizer.Add(info, 0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label=_("Save to:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.path_ctrl = wx.TextCtrl(self, value="", size=(420, -1))
        row.Add(self.path_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        browse = wx.Button(self, label=_("Browse…"))
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        row.Add(browse, 0, wx.ALL, 4)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)

        self.status = wx.StaticText(self, label="")
        sizer.Add(self.status, 0, wx.ALL, 8)
        self.SetSizer(sizer)

    def on_enter(self):
        kernel = self.wizard.service.kernel
        cor_dir = default_cor_directory(kernel.os_information.get("WORKDIR", "."))
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        device_name = getattr(self.wizard.service, "label", None) or "balor"
        suggested = os.path.join(cor_dir, f"{device_name}_{stamp}.cor")
        self.path_ctrl.SetValue(suggested)

    def on_browse(self, event):
        with wx.FileDialog(
            self,
            _("Save correction file"),
            wildcard="*.cor",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=os.path.basename(self.path_ctrl.GetValue()),
            defaultDir=os.path.dirname(self.path_ctrl.GetValue()),
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.path_ctrl.SetValue(dlg.GetPath())

    def on_leave(self) -> bool:
        path = self.path_ctrl.GetValue().strip()
        if not path:
            wx.MessageBox(
                _("Choose a path before finishing."),
                _("Missing path"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return False
        try:
            table = generate_table_from_9_point(
                self.wizard.measurements,
                self.wizard.lens_size_mm,
                nominal_segment_mm=nominal_segment_mm(self.wizard.lens_size_mm),
            )
            write_cor_file(path, table, self.wizard.lens_size_mm)
        except Exception as exc:
            wx.MessageBox(
                _("Failed to write correction file:\n{err}").format(err=exc),
                _("Write failed"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return False
        # Assign to device and notify any open config panels that listen for
        # these attributes. The panel's update listener filters on
        # ``target is choice["object"]``, so the device service must be
        # passed as the third (target) argument or the refresh is dropped.
        try:
            service = self.wizard.service
            service.corfile = path
            service.corfile_enabled = True
            service.signal("corfile", path, service)
            service.signal("corfile_enabled", True, service)
        except Exception as exc:
            wx.MessageBox(
                _(
                    "File written, but assigning to device failed:\n{err}\n\n"
                    "You can manually load it from the device configuration."
                ).format(err=exc),
                _("Assignment failed"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
        self.status.SetLabel(_("Saved and applied: {p}").format(p=path))
        return True


class CorWizard(MWindow):
    """Multi-step wizard window for generating and applying a .cor file."""

    def __init__(self, *args, **kwds):
        super().__init__(640, 720, *args, **kwds)
        self.service = self.context.device
        _icon = wx.NullIcon
        _icon.CopyFromBitmap(icons8_detective.GetBitmap())
        self.SetIcon(_icon)
        self.SetTitle(_("Cor-File Generator Wizard"))

        # Wizard state
        self.lens_size_mm = 110.0
        self.orient_swap_xy = False
        self.orient_flip_x = False
        self.orient_flip_y = False
        self.measurements = {}

        # Pages
        self.book = wx.Simplebook(self)
        self.pages = [
            IntroPage(self.book, self),
            BurnPage(self.book, self),
            OrientationPage(self.book, self),
            MeasurePage(self.book, self),
            SavePage(self.book, self),
        ]
        for p in self.pages:
            self.book.AddPage(p, "")
        self.sizer.Add(self.book, 1, wx.EXPAND, 0)

        # Nav bar
        nav = wx.BoxSizer(wx.HORIZONTAL)
        self.back_btn = wx.Button(self, label=_("← Back"))
        self.back_btn.Bind(wx.EVT_BUTTON, self.on_back)
        self.next_btn = wx.Button(self, label=_("Next →"))
        self.next_btn.Bind(wx.EVT_BUTTON, self.on_next)
        cancel_btn = wx.Button(self, label=_("Cancel"))
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        nav.Add(self.back_btn, 0, wx.ALL, 4)
        nav.AddStretchSpacer(1)
        nav.Add(cancel_btn, 0, wx.ALL, 4)
        nav.Add(self.next_btn, 0, wx.ALL, 4)
        self.sizer.Add(nav, 0, wx.EXPAND, 0)

        self.current_index = 0
        self._refresh_nav()
        self.pages[0].on_enter()
        self.restore_aspect(honor_initial_values=True)

    def _refresh_nav(self):
        self.back_btn.Enable(self.current_index > 0)
        if self.current_index == len(self.pages) - 1:
            self.next_btn.SetLabel(_("Finish"))
        else:
            self.next_btn.SetLabel(_("Next →"))

    def on_back(self, event):
        if self.current_index == 0:
            return
        self.current_index -= 1
        self.book.SetSelection(self.current_index)
        self.pages[self.current_index].on_enter()
        self._refresh_nav()

    def on_next(self, event):
        if not self.pages[self.current_index].on_leave():
            return
        if self.current_index == len(self.pages) - 1:
            self.Close()
            return
        self.current_index += 1
        self.book.SetSelection(self.current_index)
        self.pages[self.current_index].on_enter()
        self._refresh_nav()

    @staticmethod
    def submenu():
        # Hint for translation: _("Device-Settings"), _("Cor-File Wizard")
        return "Device-Settings", "Cor-File Wizard"

    @staticmethod
    def helptext():
        return _("Generate a .cor lens-correction file via 9-point calibration")
