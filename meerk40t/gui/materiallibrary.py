"""meerk40t.gui.materiallibrary
---------------------------------

New Material Library window — work-in-progress replacement for the
existing materialmanager.py.

Layout::

    +-------------------------------------------------------+
    | Library: [ ▾ ]            Search: [_______________]   |
    +-------------------------------------------------------+
    |  Tree (full height)   |  Header (selected item)       |
    |  - Category           |  -----                        |
    |    - Material         |  Operations table             |
    |      - Thickness      |                               |
    +-------------------------------------------------------+
    |  [+ New ▾]  [Copy ▾]  [Delete]                        |
    +-------------------------------------------------------+

Right-click actions, drag-and-drop, and search are added in later phases.
The data model and persistence live in ``core/elements/material_library.py``;
this file is GUI-only.
"""

import os

import wx

from meerk40t.core.elements.material_library import (
    KIND_CATEGORY,
    KIND_MATERIAL,
    KIND_THICKNESS,
    VALID_OP_TYPES,
    Category,
    MaterialEffect,
    MaterialEntry,
    MaterialOperation,
    ThicknessEntry,
    clone_node,
    discover_effect_types,
    find_or_create_uncategorized,
    find_parent,
    get_effect_schema,
    make_unique_name,
    match_op_against_query,
    move_node,
    normalize_passes_setting,
    parse_library_file,
    parse_search_query,
    save_library_to_file,
    short_effect_name,
    wrap_for_export,
)
from meerk40t.gui.icons import (
    icon_edit,
    icon_library,
    icon_trash,
    icons8_caret_down,
    icons8_caret_up,
)
from meerk40t.gui.mwindow import MWindow
from meerk40t.gui.wxutils import (
    EditableListCtrl,
    StaticBoxSizer,
    TextCtrl,
    dip_size,
    wxButton,
    wxComboBox,
    wxStaticText,
    wxTreeCtrl,
)

_ = wx.GetTranslation

# KIND_* constants are imported from material_library and shared between the
# data layer (move/can-move validation) and this UI module.


class MaterialLibraryPanel(wx.Panel):
    """Browser for matlib libraries.

    NB: this is a plain wx.Panel, not a ScrolledPanel. The splitter and the
    operations listctrl manage their own scrolling internally; making the
    whole panel scroll would let the inner widgets push the top library
    combo (and other always-visible widgets) off-screen when the dialog
    is resized.
    """

    def __init__(self, *args, context=None, **kwds):
        kwds["style"] = kwds.get("style", 0) | wx.TAB_TRAVERSAL
        wx.Panel.__init__(self, *args, **kwds)
        self.context = context
        self.context.themes.set_window_colors(self)
        self.parent_panel = None

        self._current_library = None  # Library object currently selected

        self._build_ui()
        self._bind_events()
        self.refresh_libraries()

    # -- service convenience -------------------------------------------------

    @property
    def service(self):
        # The matlib service is registered at kernel scope; access via root.
        return self.context.kernel.matlib

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # Top row: library actions button + library picker + search
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_library_menu = wx.BitmapButton(
            self,
            wx.ID_ANY,
            icon_library.GetBitmap(resize=20),
            style=wx.BU_EXACTFIT,
        )
        self.btn_library_menu.SetToolTip(
            _("Library actions (new, rename, delete, export, import)")
        )
        top.Add(self.btn_library_menu, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.combo_library = wxComboBox(
            self, wx.ID_ANY, choices=[], style=wx.CB_READONLY
        )
        top.Add(self.combo_library, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        top.Add(
            wxStaticText(self, wx.ID_ANY, _("Search:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.text_search = TextCtrl(self, wx.ID_ANY, "")
        self.text_search.SetToolTip(
            _(
                "Filter the tree. Free text matches anywhere (category /"
                " material / thickness / op label / power / speed / freq /"
                " effects). Add field:value to scope: "
                "category:wood material:plywood thickness:3mm op:cut "
                "id:c1 label:through power:800 speed:10 freq:20 effect:hatch"
            )
        )
        top.Add(self.text_search, 1, wx.ALIGN_CENTER_VERTICAL)
        self.btn_search_helper = wxButton(self, wx.ID_ANY, _("Filter…"))
        self.btn_search_helper.SetToolTip(
            _("Open a form to build a search without remembering the syntax")
        )
        top.Add(self.btn_search_helper, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 6)

        # Library summary line — clickable, opens Library Properties dialog.
        self.lbl_library_summary = wxStaticText(self, wx.ID_ANY, "")
        self.lbl_library_summary.SetToolTip(
            _("Click to edit library properties")
        )
        # Muted color so it reads as informational.
        try:
            fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
            self.lbl_library_summary.SetForegroundColour(fg)
        except Exception:
            pass
        self.lbl_library_summary.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        outer.Add(
            self.lbl_library_summary,
            0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6,
        )

        # Main area: tree on the left, details panel on the right
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetMinimumPaneSize(180)

        # Left: tree
        self.tree_library = wxTreeCtrl(
            splitter,
            wx.ID_ANY,
            style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE,
        )

        # Right: details panel (header + ops list)
        right_panel = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        header_box = StaticBoxSizer(
            right_panel, wx.ID_ANY, _("Details"), wx.VERTICAL
        )
        self.lbl_header = wxStaticText(right_panel, wx.ID_ANY, "")
        self.lbl_subheader = wxStaticText(right_panel, wx.ID_ANY, "")
        self.txt_notes = TextCtrl(
            right_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE,
        )
        header_box.Add(self.lbl_header, 0, wx.EXPAND | wx.ALL, 4)
        header_box.Add(self.lbl_subheader, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        header_box.Add(
            wxStaticText(right_panel, wx.ID_ANY, _("Notes:")),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            4,
        )
        header_box.Add(self.txt_notes, 1, wx.EXPAND | wx.ALL, 4)
        right_sizer.Add(header_box, 0, wx.EXPAND | wx.ALL, 4)

        ops_box = StaticBoxSizer(
            right_panel, wx.ID_ANY, _("Operations"), wx.VERTICAL
        )
        self.list_ops = EditableListCtrl(
            right_panel,
            wx.ID_ANY,
            # Multi-select enabled: shift-click for range, ctrl-click to
            # toggle. Most actions still operate on a single row; the
            # right-click menu reduces to Push/Remove when multiple are
            # selected.
            style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES,
            context=self.context,
            list_name="material_library_ops",
        )
        # Center numeric / status columns; leave free-text columns left-aligned.
        # Icon-button columns (Up/Down/Edit/Remove) have empty headers.
        # Op column shows short op-type names (e.g. "raster" not "op raster").
        cc = wx.LIST_FORMAT_CENTER
        self.list_ops.InsertColumn(0, _("Op"), width=80)
        self.list_ops.InsertColumn(1, _("ID"), width=60)
        self.list_ops.InsertColumn(2, _("Label"), width=140)
        self.list_ops.InsertColumn(3, _("Power"), format=cc, width=80)
        self.list_ops.InsertColumn(4, _("Speed"), format=cc, width=110)
        self.list_ops.InsertColumn(5, _("Passes"), format=cc, width=70)
        self.list_ops.InsertColumn(6, _("Freq."), format=cc, width=70)
        self.list_ops.InsertColumn(7, _("Effects"), width=130)
        self.list_ops.InsertColumn(8, "", format=cc, width=40)
        self.list_ops.InsertColumn(9, "", format=cc, width=40)
        self.list_ops.InsertColumn(10, "", format=cc, width=50)
        self.list_ops.InsertColumn(11, "", format=cc, width=60)
        # The base wxListCtrl auto-stretches its last column on resize but
        # never shrinks it back, which would push the right pane wider than
        # its sash and squeeze the tree off the left. Disable the auto-grow
        # so columns stay at their declared widths; the listctrl will scroll
        # horizontally when the pane is narrower than the total column width.
        self.list_ops.adjust_last_column = lambda *a, **kw: False
        # And don't let the listctrl dictate the right pane's minimum width.
        self.list_ops.SetMinSize((150, -1))
        # Remember the "normal" widths of the optional columns so we can
        # hide and restore them per library setting.
        self._OP_COL_FREQ = 6
        self._OP_COL_EFFECTS = 7
        self._OP_COL_UP = 8
        self._OP_COL_DOWN = 9
        self._OP_COL_EDIT = 10
        self._OP_COL_REMOVE = 11
        self._op_col_widths = {
            self._OP_COL_FREQ: 70,
        }
        # Make each row tall enough for the in-place edit TextCtrl to fit.
        # Image-list bitmap height drives the row height. We use square
        # bitmaps so we can also render a pencil icon in the Edit column.
        _probe = wx.TextCtrl(right_panel)
        self._ops_row_h = max(_probe.GetBestSize().GetHeight(), 24)
        _probe.Destroy()
        self._ops_row_imagelist = wx.ImageList(
            self._ops_row_h, self._ops_row_h
        )
        # Index 0: fully-transparent slot used as the column-0 row "image"
        # purely so wxListCtrl honors the image-list height for every row.
        transparent = wx.Bitmap.FromRGBA(
            self._ops_row_h, self._ops_row_h, 0, 0, 0, 0
        )
        self._ops_row_imageidx = self._ops_row_imagelist.Add(transparent)
        # Index 1: pencil — shown in the Edit column.
        self._ops_edit_iconidx = self._ops_row_imagelist.Add(
            icon_edit.GetBitmap(resize=self._ops_row_h)
        )
        # Index 2: caret up — shown in the Up column when applicable.
        self._ops_up_iconidx = self._ops_row_imagelist.Add(
            icons8_caret_up.GetBitmap(resize=self._ops_row_h)
        )
        # Index 3: caret down — shown in the Down column when applicable.
        self._ops_down_iconidx = self._ops_row_imagelist.Add(
            icons8_caret_down.GetBitmap(resize=self._ops_row_h)
        )
        # Index 4: trash — shown in the Remove column.
        self._ops_trash_iconidx = self._ops_row_imagelist.Add(
            icon_trash.GetBitmap(resize=self._ops_row_h)
        )
        self.list_ops.SetImageList(
            self._ops_row_imagelist, wx.IMAGE_LIST_SMALL
        )
        ops_box.Add(self.list_ops, 1, wx.EXPAND | wx.ALL, 4)
        right_sizer.Add(ops_box, 1, wx.EXPAND | wx.ALL, 4)

        # Op-action toolbar — Remove/Up/Down were retired in favor of the
        # per-row icons; Push/Pull move ops between the library and the
        # document's operations branch.
        op_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_op_add = wxButton(
            right_panel, wx.ID_ANY, _("+ Add Operation ▾")
        )
        self.btn_op_add.SetToolTip(_("Add a new operation (choose type)"))
        op_actions.Add(self.btn_op_add, 0, wx.RIGHT, 4)

        self.btn_op_push = wxButton(
            right_panel, wx.ID_ANY, _("⬆ Push ▾")
        )
        self.btn_op_push.SetToolTip(
            _("Send these operations to the document's operations branch")
        )
        op_actions.Add(self.btn_op_push, 0, wx.RIGHT, 4)

        self.btn_op_pull = wxButton(
            right_panel, wx.ID_ANY, _("⬇ Pull ▾")
        )
        self.btn_op_pull.SetToolTip(
            _("Bring the document's current operations into this library entry")
        )
        op_actions.Add(self.btn_op_pull, 0, wx.RIGHT, 4)
        right_sizer.Add(op_actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(self.tree_library, right_panel, 280)
        outer.Add(splitter, 1, wx.EXPAND | wx.ALL, 4)

        # Bottom toolbar
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_new = wxButton(self, wx.ID_ANY, _("+ New ▾"))
        self.btn_new.SetToolTip(_("Create a new library, category, material, or thickness"))
        self.btn_copy = wxButton(self, wx.ID_ANY, _("Copy ▾"))
        self.btn_copy.SetToolTip(_("Duplicate the selected item or copy it to another library"))
        self.btn_delete = wxButton(self, wx.ID_ANY, _("Delete"))
        self.btn_delete.SetToolTip(_("Delete the selected item"))
        bottom.Add(self.btn_new, 0, wx.RIGHT, 4)
        bottom.Add(self.btn_copy, 0, wx.RIGHT, 4)
        bottom.Add(self.btn_delete, 0, wx.RIGHT, 4)
        outer.Add(bottom, 0, wx.EXPAND | wx.ALL, 6)

        self.SetSizer(outer)

    def _bind_events(self):
        self.btn_library_menu.Bind(wx.EVT_BUTTON, self.on_library_menu_clicked)
        self.combo_library.Bind(wx.EVT_COMBOBOX, self.on_library_chosen)
        self.lbl_library_summary.Bind(
            wx.EVT_LEFT_DOWN, lambda e: self._edit_library_properties()
        )
        self.text_search.Bind(wx.EVT_TEXT, self.on_search_changed)
        self.btn_search_helper.Bind(
            wx.EVT_BUTTON, self.on_search_helper_clicked
        )
        self.tree_library.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_selection)
        self.tree_library.Bind(
            wx.EVT_TREE_ITEM_RIGHT_CLICK, self.on_tree_right_click
        )
        self.tree_library.Bind(wx.EVT_TREE_BEGIN_DRAG, self.on_tree_begin_drag)
        self.tree_library.Bind(wx.EVT_TREE_END_DRAG, self.on_tree_end_drag)
        self.btn_new.Bind(wx.EVT_BUTTON, self.on_new_clicked)
        self.btn_copy.Bind(wx.EVT_BUTTON, self.on_copy_clicked)
        self.btn_delete.Bind(wx.EVT_BUTTON, self.on_delete_clicked)
        # Right-pane editing (Phase 7)
        self.txt_notes.Bind(wx.EVT_TEXT, self.on_notes_text_changed)
        self.txt_notes.Bind(wx.EVT_KILL_FOCUS, self.on_notes_kill_focus)
        self.list_ops.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_op_edit_end)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_op_right_click)
        # Click on the Effects cell pops a menu instead of opening an editor.
        self.list_ops.Bind(wx.EVT_LEFT_DOWN, self.on_op_left_down)
        self.list_ops.Bind(
            wx.EVT_LIST_BEGIN_LABEL_EDIT, self.on_op_begin_edit
        )
        self.list_ops.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_op_row_selection)
        self.list_ops.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_op_row_selection)
        self.btn_op_add.Bind(wx.EVT_BUTTON, self.on_op_add_clicked)
        self.btn_op_push.Bind(wx.EVT_BUTTON, self.on_op_push_clicked)
        self.btn_op_pull.Bind(wx.EVT_BUTTON, self.on_op_pull_clicked)
        self._drag_data = None
        self._editing_target = None

    # -- population ----------------------------------------------------------

    def refresh_libraries(self, select_name=None):
        """Reload library list from the service into the dropdown.

        If ``select_name`` is given and exists, select that library;
        otherwise keep the previous selection or default to the first.
        """
        prev_name = self.combo_library.GetStringSelection()
        names = self.service.library_names() if self.service else []
        self.combo_library.Clear()
        for n in names:
            self.combo_library.Append(n)
        self._resize_combo_to_names(names)
        target = (
            select_name if select_name in names
            else (prev_name if prev_name in names
                  else (names[0] if names else None))
        )
        if target:
            self.combo_library.SetStringSelection(target)
            self._current_library = self.service.get_library(target)
        else:
            self._current_library = None
        self._populate_tree()
        self._clear_details()
        self._update_button_state()
        self._refresh_library_summary()
        self._apply_op_column_visibility()

    def _refresh_library_summary(self):
        """Update the muted summary label under the library combo."""
        lib = self._current_library
        self.lbl_library_summary.SetLabel(self._format_library_summary(lib))
        # Re-layout in case the label changed enough to need it.
        self.Layout()

    # Display labels for the library-level unit choices.
    _POWER_UNIT_DISPLAY = {"percent": "%", "ppi": "PPI"}
    _SPEED_UNIT_DISPLAY = {"mm/s": "mm/s", "mm/min": "mm/min"}

    # Power and speed are stored as PPI / (mm/s) internally and on disk,
    # always. The library's power_unit / speed_unit choices only affect how
    # the values are displayed and parsed in the matlib UI.

    def _power_to_display(self, value):
        if value is None or value == "":
            return ""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        lib = self._current_library
        if lib is not None and lib.power_unit == "percent":
            v = v / 10.0
        return f"{v:g}"

    def _power_from_display(self, text):
        """Parse user-entered text into the stored PPI float, clamped to
        the internal 0..1000 range. Percent inputs of 0..100 land naturally
        in range; values outside it are silently clamped so we never write
        an out-of-range PPI to the library file."""
        t = text.strip()
        if t.endswith("%"):
            t = t[:-1].strip()
        v = float(t)
        lib = self._current_library
        if lib is not None and lib.power_unit == "percent":
            v = v * 10.0
        return max(0.0, min(1000.0, v))

    def _speed_to_display(self, value):
        if value is None or value == "":
            return ""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        lib = self._current_library
        if lib is not None and lib.speed_unit == "mm/min":
            v = v * 60.0
        return f"{v:g}"

    def _speed_from_display(self, text):
        """Parse user-entered text into the stored mm/s float."""
        v = float(text.strip())
        lib = self._current_library
        if lib is not None and lib.speed_unit == "mm/min":
            v = v / 60.0
        return v

    def _apply_op_column_visibility(self):
        """Show/hide optional ops columns based on the current library's
        driver, and tag the Power/Speed headers with the library's chosen
        units."""
        lib = self._current_library
        show_freq = bool(lib and lib.driver == "balor")
        self.list_ops.SetColumnWidth(
            self._OP_COL_FREQ,
            self._op_col_widths[self._OP_COL_FREQ] if show_freq else 0,
        )
        # Power / Speed headers: append the unit when the library has set one.
        # Columns: 0 Op, 1 ID, 2 Label, 3 Power, 4 Speed.
        power_unit = self._POWER_UNIT_DISPLAY.get(
            lib.power_unit, ""
        ) if lib else ""
        speed_unit = self._SPEED_UNIT_DISPLAY.get(
            lib.speed_unit, ""
        ) if lib else ""
        self._set_column_label(
            3, _("Power") + (f" ({power_unit})" if power_unit else "")
        )
        self._set_column_label(
            4, _("Speed") + (f" ({speed_unit})" if speed_unit else "")
        )

    def _set_column_label(self, col, label):
        item = self.list_ops.GetColumn(col)
        item.SetText(label)
        self.list_ops.SetColumn(col, item)

    @staticmethod
    def _format_library_summary(lib) -> str:
        if lib is None:
            return ""
        bits = []
        # Known source keys get pretty labels; free-typed values display as-is.
        src_disp = {
            "co2": "CO2", "fiber": "Fiber", "uv": "UV",
            "diode": "Diode", "green": "Green",
        }.get(lib.source, lib.source)
        if src_disp and lib.wattage:
            bits.append(f"{src_disp} {lib.wattage:g}W")
        elif src_disp:
            bits.append(src_disp)
        elif lib.wattage:
            bits.append(f"{lib.wattage:g}W")
        if lib.motion:
            bits.append(lib.motion)
        if lib.lens:
            bits.append(lib.lens)
        if not bits:
            return _("click to set library properties")
        return " · ".join(bits)

    def _resize_combo_to_names(self, names):
        """Size the library combo to fit the widest name, within sane bounds."""
        min_width = 160
        max_width = 420
        # The dropdown arrow + cell padding eats more horizontal space than
        # GetTextExtent reports — especially on GTK. ~60px clears it.
        chrome = 60
        if names:
            dc = wx.ClientDC(self.combo_library)
            dc.SetFont(self.combo_library.GetFont())
            widest = max(dc.GetTextExtent(n)[0] for n in names)
            width = widest + chrome
        else:
            width = min_width
        width = max(min_width, min(width, max_width))
        self.combo_library.SetMinSize((width, -1))
        self.Layout()

    def _populate_tree(self):
        tree = self.tree_library
        tree.DeleteAllItems()
        root = tree.AddRoot("ROOT")
        lib = self._current_library
        if lib is None:
            return
        # match_set is None when no search query is active (show all).
        # Otherwise it's a set of id(obj) for items that should be visible.
        match_set = self._build_match_set()
        for cat in lib.categories:
            self._add_category_to_tree(root, cat, match_set)
        tree.ExpandAll()

    def _add_category_to_tree(self, parent_item, cat, match_set=None):
        if match_set is not None and id(cat) not in match_set:
            return
        item = self.tree_library.AppendItem(parent_item, cat.name)
        self.tree_library.SetItemBold(item, True)
        self.tree_library.SetItemData(item, (KIND_CATEGORY, cat))
        for sub in cat.categories:
            self._add_category_to_tree(item, sub, match_set)
        for mat in cat.materials:
            self._add_material_to_tree(item, mat, match_set)

    def _add_material_to_tree(self, parent_item, mat, match_set=None):
        if match_set is not None and id(mat) not in match_set:
            return
        item = self.tree_library.AppendItem(parent_item, mat.name or _("(unnamed)"))
        self.tree_library.SetItemData(item, (KIND_MATERIAL, mat))
        for thk in mat.thicknesses:
            if match_set is not None and id(thk) not in match_set:
                continue
            label = thk.value or _("(no thickness)")
            sub = self.tree_library.AppendItem(item, label)
            self.tree_library.SetItemData(sub, (KIND_THICKNESS, thk))

    # -- Search / filter ----------------------------------------------------

    def on_search_helper_clicked(self, event):
        """Open the search-builder dialog. On OK, the dialog returns a
        composed query string which we drop into the search field — the
        existing EVT_TEXT handler re-filters the tree."""
        dlg = SearchHelperDialog(self, self.text_search.GetValue())
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.text_search.SetValue(dlg.get_query())
                # SetValue fires EVT_TEXT so the tree refreshes itself.
        finally:
            dlg.Destroy()

    def on_search_changed(self, event):
        # Capture the previously-selected object so we can either reselect
        # it (if still visible after filtering) or clear the right pane
        # (if the search hid it). _editing_target is (kind, obj) or None.
        prev_target = self._editing_target
        self._populate_tree()
        if prev_target is not None:
            prev_obj = prev_target[1]
            tree_item = self._find_tree_item(prev_obj)
            if tree_item is not None:
                # SelectItem fires EVT_TREE_SEL_CHANGED, which re-runs
                # _show_* and resets _editing_target via the existing path.
                self.tree_library.SelectItem(tree_item)
                self.tree_library.EnsureVisible(tree_item)
            else:
                # Previously-selected item is filtered out — clear the
                # stale details so the right pane reflects the (empty)
                # current selection.
                self._clear_details()
        event.Skip()

    def _build_match_set(self):
        """Return a set of ``id(obj)`` for items that should be shown given
        the current search query, or ``None`` if no query is active.

        Strategy: walk every op-bearing leaf (Material w/o thicknesses,
        or each Thickness). If a leaf matches the query, the leaf AND
        every ancestor up to and including the top category get added
        to the set so the tree structure stays navigable.
        """
        raw = self.text_search.GetValue() if self.text_search else ""
        free, fields = parse_search_query(raw)
        if not free and not fields:
            return None
        lib = self._current_library
        matched = set()
        if lib is None:
            return matched
        for cat in lib.categories:
            self._scan_category_for_query(cat, [], free, fields, matched)
        return matched

    def _scan_category_for_query(
        self, cat, ancestors, free, fields, matched
    ):
        new_ancestors = ancestors + [cat]
        # Recurse into sub-categories first.
        for sub in cat.categories:
            self._scan_category_for_query(
                sub, new_ancestors, free, fields, matched
            )
        # Then each material.
        for mat in cat.materials:
            if mat.thicknesses:
                for thk in mat.thicknesses:
                    if self._leaf_matches_query(
                        new_ancestors, mat, thk, thk.operations, free, fields
                    ):
                        matched.add(id(thk))
                        matched.add(id(mat))
                        for a in new_ancestors:
                            matched.add(id(a))
            else:
                # Material is itself the op-bearing leaf.
                if self._leaf_matches_query(
                    new_ancestors, mat, None, mat.operations, free, fields
                ):
                    matched.add(id(mat))
                    for a in new_ancestors:
                        matched.add(id(a))

    @staticmethod
    def _leaf_matches_query(
        cat_ancestors, mat, thk, ops, free, fields
    ):
        cat_path = " > ".join(c.name for c in cat_ancestors).lower()
        cat_last = (cat_ancestors[-1].name if cat_ancestors else "").lower()
        mat_name = (mat.name or "").lower()
        thk_value = (thk.value or "").lower() if thk is not None else ""

        # Path-scope filters. These must all match the leaf's location.
        cf = fields.get("category")
        if cf and cf not in cat_last and cf not in cat_path:
            return False
        mf = fields.get("material")
        if mf and mf not in mat_name:
            return False
        tf = fields.get("thickness")
        if tf and tf not in thk_value:
            return False

        # Op-scope and free-text: if any of these are present, at least one
        # op in this leaf must satisfy them. If the leaf has no ops, we
        # fall back to matching free text against the path alone.
        op_relevant_fields = {
            k: v for k, v in fields.items()
            if k not in ("category", "material", "thickness")
        }
        if not free and not op_relevant_fields:
            return True  # scope-only query and all scopes passed
        if ops:
            for op in ops:
                if match_op_against_query(
                    op, cat_path, mat_name, thk_value, free, op_relevant_fields
                ):
                    return True
            return False
        # No ops on this leaf — match free text against path only, and
        # only if no op-specific field filters were given (those can't
        # match without ops).
        if op_relevant_fields:
            return False
        if free:
            haystack = f"{cat_path} {mat_name} {thk_value}"
            return all(t in haystack for t in free)
        return True

    # -- selection handling --------------------------------------------------

    def on_library_chosen(self, event):
        name = self.combo_library.GetStringSelection()
        self._current_library = self.service.get_library(name) if name else None
        self._populate_tree()
        self._clear_details()
        self._update_button_state()
        self._refresh_library_summary()
        self._apply_op_column_visibility()

    # -- Library actions menu (icon button next to the dropdown) ------------

    def on_library_menu_clicked(self, event):
        has_lib = self._current_library is not None
        menu = wx.Menu()

        new_item = menu.Append(wx.ID_ANY, _("New Library..."))
        self.Bind(wx.EVT_MENU, lambda e: self._new_library(), new_item)

        rename_item = menu.Append(wx.ID_ANY, _("Rename Library..."))
        rename_item.Enable(has_lib)
        self.Bind(wx.EVT_MENU, lambda e: self._rename_library(), rename_item)

        props_item = menu.Append(wx.ID_ANY, _("Library Properties..."))
        props_item.Enable(has_lib)
        self.Bind(
            wx.EVT_MENU, lambda e: self._edit_library_properties(), props_item
        )

        delete_item = menu.Append(wx.ID_ANY, _("Delete Library..."))
        delete_item.Enable(has_lib)
        self.Bind(wx.EVT_MENU, lambda e: self._delete_library(), delete_item)

        menu.AppendSeparator()

        export_item = menu.Append(wx.ID_ANY, _("Export Library..."))
        export_item.Enable(has_lib)
        self.Bind(wx.EVT_MENU, lambda e: self._export_library(), export_item)

        import_item = menu.Append(wx.ID_ANY, _("Import Library..."))
        self.Bind(wx.EVT_MENU, lambda e: self._import_library(), import_item)

        self.PopupMenu(menu, self._below(self.btn_library_menu))
        menu.Destroy()

    def _rename_library(self):
        if self._current_library is None:
            return
        current = self._current_library.name
        new = self._prompt_text(_("Rename Library"), _("New name:"), current)
        if new is None:
            return
        new = new.strip()
        if not new or new == current:
            return
        try:
            self.service.rename_library(current, new)
        except ValueError as exc:
            wx.MessageBox(
                str(exc), _("Rename failed"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return
        self.refresh_libraries(select_name=new)

    def _delete_library(self):
        if self._current_library is None:
            return
        name = self._current_library.name
        msg = _(
            "Delete library '{name}'? "
            "This removes the file and cannot be undone."
        ).format(name=name)
        with wx.MessageDialog(
            self, msg, _("Delete library"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return
        self.service.delete_library(name)
        self.refresh_libraries()

    def _export_library(self):
        if self._current_library is None:
            return
        name = self._current_library.name
        with wx.FileDialog(
            self,
            message=_("Export Library to .meerlib"),
            defaultFile=f"{name}.meerlib",
            wildcard=_("MeerK40t Library (*.meerlib)|*.meerlib"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            self.service.export_library(name, path)
        except Exception as exc:
            wx.MessageBox(
                str(exc), _("Export failed"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return
        wx.MessageBox(
            _("Exported to {path}").format(path=path),
            _("Exported"),
            wx.OK | wx.ICON_INFORMATION, self,
        )

    # File-dialog wildcard for all supported import formats.
    _IMPORT_WILDCARD = (
        "All Supported|"
        "*.meerlib;*.clb;*.lib;*.ini;*.cfg|"
        "MeerK40t Library (*.meerlib)|*.meerlib|"
        "LightBurn Library (*.clb)|*.clb|"
        "EzCad Library (*.lib;*.ini)|*.lib;*.ini|"
        "Legacy MeerK40t (*.cfg)|*.cfg|"
        "All Files (*.*)|*.*"
    )

    def _import_library(self):
        with wx.FileDialog(
            self,
            message=_("Import library"),
            wildcard=self._IMPORT_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        # Parse first so we can show a meaningful name in the next prompt
        # and bail early on bad files.
        try:
            parsed = parse_library_file(path)
        except Exception as exc:
            wx.MessageBox(
                _("Could not read library:\n{exc}").format(exc=exc),
                _("Import failed"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return

        # Ask the user how to land it. If no current library, only "as new"
        # is available.
        current = self._current_library
        if current is None:
            self._do_import_as_new(parsed, path)
            return

        choices = [
            _("Import as new library"),
            _("Import into '{name}'").format(name=current.name),
        ]
        with wx.SingleChoiceDialog(
            self,
            _(
                "Found {n} categor{ies} in '{src}'.\n"
                "How would you like to import?"
            ).format(
                n=len(parsed.categories),
                ies=("ies" if len(parsed.categories) != 1 else "y"),
                src=os.path.basename(path),
            ),
            _("Import library"),
            choices,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            sel = dlg.GetSelection()

        if sel == 0:
            self._do_import_as_new(parsed, path)
        else:
            try:
                self.service.merge_library_into(parsed, current)
            except Exception as exc:
                wx.MessageBox(
                    _("Merge failed:\n{exc}").format(exc=exc),
                    _("Import failed"),
                    wx.OK | wx.ICON_ERROR, self,
                )
                return
            self.refresh_libraries(select_name=current.name)

    def _do_import_as_new(self, parsed_lib, source_path):
        """Register a freshly-parsed library as a new library on disk,
        with name-collision handling delegated to the service."""
        if not parsed_lib.name:
            parsed_lib.name = os.path.splitext(
                os.path.basename(source_path)
            )[0]
        try:
            lib = self.service.add_imported_library(parsed_lib)
        except Exception as exc:
            wx.MessageBox(
                _("Import failed:\n{exc}").format(exc=exc),
                _("Import failed"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return
        self.refresh_libraries(select_name=lib.name)

    def _driver_choices(self):
        """Return [(label, key), ...] for the Driver dropdown.

        Sourced from kernel-registered laser providers (see provider/friendly).
        The displayed label is the provider key itself (e.g. 'lhystudios',
        'grbl'), which is also what we store. First entry is always
        ('(unspecified)', '')."""
        choices = [(_("(unspecified)"), "")]
        try:
            providers = list(self.context.kernel.find("provider/friendly"))
        except Exception:
            providers = []
        # kernel.find yields (value, full_path, last_segment); the
        # registered value is itself (friendly_name, sort_order).
        providers.sort(key=lambda e: e[0][1])
        for _info, _full_path, key in providers:
            choices.append((key, key))
        return choices

    # Fixed-choice options for library metadata fields.
    # Motion and Source allow free text in addition to these suggestions.
    _MOTION_CHOICES = (
        ("gantry", "Gantry"),
        ("galvo", "Galvo"),
    )
    _SOURCE_CHOICES = (
        ("co2", "CO2"),
        ("fiber", "Fiber"),
        ("uv", "UV"),
        ("diode", "Diode"),
        ("green", "Green"),
    )
    # Power unit is read-only choice: only PPI and % are supported by the
    # eventual op-loading path.
    _POWER_UNIT_CHOICES = (
        ("", "(unspecified)"),
        ("ppi", "PPI"),
        ("percent", "Percent (%)"),
    )
    _SPEED_UNIT_CHOICES = (
        ("", "(unspecified)"),
        ("mm/s", "mm/s"),
        ("mm/min", "mm/min"),
    )

    def _edit_library_properties(self):
        lib = self._current_library
        if lib is None:
            return

        dlg = wx.Dialog(self, title=_("Library Properties"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        grid.AddGrowableCol(1, 1)

        def _row(label, control):
            grid.Add(
                wxStaticText(dlg, wx.ID_ANY, label),
                0, wx.ALIGN_CENTER_VERTICAL,
            )
            grid.Add(control, 1, wx.EXPAND)

        def _make_locked_combo(choices, current_value):
            """Read-only combo. choices: tuple of (key, label)."""
            combo = wxComboBox(
                dlg, wx.ID_ANY,
                choices=[c[1] for c in choices],
                style=wx.CB_READONLY,
            )
            idx = 0
            for i, (key, _label) in enumerate(choices):
                if key == current_value:
                    idx = i
                    break
            combo.SetSelection(idx)
            return combo

        def _make_freetext_combo(choices, current_value):
            """Editable combo: dropdown suggestions plus arbitrary typing."""
            combo = wxComboBox(
                dlg, wx.ID_ANY,
                choices=[c[1] for c in choices],
                style=wx.CB_DROPDOWN,
            )
            # If the current value matches a known key, select that entry by
            # label; otherwise show the raw value as typed text.
            matched = False
            for i, (key, label) in enumerate(choices):
                if key == current_value:
                    combo.SetSelection(i)
                    matched = True
                    break
            if not matched:
                combo.SetValue(current_value or "")
            return combo

        def _read_freetext_combo(combo, choices):
            text = combo.GetValue().strip()
            if not text:
                return ""
            # Match against display label or key (case-insensitive).
            for key, label in choices:
                if text == label or text.lower() == key.lower():
                    return key
            return text

        _row(_("Name:"), wxStaticText(dlg, wx.ID_ANY, lib.name))

        desc_ctrl = TextCtrl(dlg, wx.ID_ANY, lib.description or "")
        _row(_("Description:"), desc_ctrl)

        # Driver — drives which driver-specific tabs become available in
        # operation editing. Independent of "Default for device" below.
        driver_choices = self._driver_choices()
        driver_combo = wxComboBox(
            dlg, wx.ID_ANY,
            choices=[c[0] for c in driver_choices],
            style=wx.CB_READONLY,
        )
        driver_idx = 0
        for i, (_label, key) in enumerate(driver_choices):
            if key == lib.driver:
                driver_idx = i
                break
        driver_combo.SetSelection(driver_idx)
        _row(_("Driver:"), driver_combo)

        motion_combo = _make_freetext_combo(self._MOTION_CHOICES, lib.motion)
        _row(_("Motion system:"), motion_combo)

        source_combo = _make_freetext_combo(self._SOURCE_CHOICES, lib.source)
        _row(_("Source:"), source_combo)

        watt_ctrl = TextCtrl(
            dlg, wx.ID_ANY,
            f"{lib.wattage:g}" if lib.wattage else "",
        )
        _row(_("Wattage (W):"), watt_ctrl)

        lens_ctrl = TextCtrl(dlg, wx.ID_ANY, lib.lens or "")
        _row(_("Lens:"), lens_ctrl)

        power_unit_combo = _make_locked_combo(
            self._POWER_UNIT_CHOICES, lib.power_unit
        )
        _row(_("Power unit:"), power_unit_combo)

        speed_unit_combo = _make_locked_combo(
            self._SPEED_UNIT_CHOICES, lib.speed_unit
        )
        _row(_("Speed unit:"), speed_unit_combo)

        # "Default for device" — stored in each device's own config, not the
        # library. Picking a device sets that device's default_matlib to this
        # library's name; picking (none) clears any device pointing to it.
        devices = list(self.context.kernel.services("device") or [])
        for d in devices:
            # idempotently declare the setting so it exists
            d.setting(str, "default_matlib", "")
        dev_choices = [(_("(none)"), None)] + [
            (getattr(d, "label", None) or getattr(d, "path", str(d)), d)
            for d in devices
        ]
        default_dev_combo = wxComboBox(
            dlg, wx.ID_ANY,
            choices=[c[0] for c in dev_choices],
            style=wx.CB_READONLY,
        )
        # Preselect the first device whose default_matlib points at us.
        cur_dev_idx = 0
        for i, (_label, d) in enumerate(dev_choices):
            if d is not None and getattr(d, "default_matlib", "") == lib.name:
                cur_dev_idx = i
                break
        default_dev_combo.SetSelection(cur_dev_idx)
        if not devices:
            default_dev_combo.Enable(False)
            default_dev_combo.SetToolTip(_("No devices configured"))
        _row(_("Default for device:"), default_dev_combo)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        btn_sizer = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        dlg.SetSizerAndFit(sizer)

        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_desc = desc_ctrl.GetValue()
            new_motion = _read_freetext_combo(motion_combo, self._MOTION_CHOICES)
            new_source = _read_freetext_combo(source_combo, self._SOURCE_CHOICES)
            try:
                new_wattage = (
                    float(watt_ctrl.GetValue()) if watt_ctrl.GetValue().strip()
                    else 0.0
                )
            except ValueError:
                wx.MessageBox(
                    _("Wattage must be a number."),
                    _("Invalid input"),
                    wx.OK | wx.ICON_ERROR, self,
                )
                return
            new_lens = lens_ctrl.GetValue().strip()
            new_pu = self._POWER_UNIT_CHOICES[
                power_unit_combo.GetSelection()
            ][0]
            new_su = self._SPEED_UNIT_CHOICES[
                speed_unit_combo.GetSelection()
            ][0]

            d_idx = driver_combo.GetSelection()
            new_driver = (
                driver_choices[d_idx][1]
                if 0 <= d_idx < len(driver_choices) else ""
            )
            updates = {
                "description": new_desc,
                "driver": new_driver,
                "motion": new_motion,
                "source": new_source,
                "wattage": new_wattage,
                "lens": new_lens,
                "power_unit": new_pu,
                "speed_unit": new_su,
            }
            changed = False
            for key, value in updates.items():
                if getattr(lib, key) != value:
                    setattr(lib, key, value)
                    changed = True
            if changed:
                self.service.save_library(lib)
                self._refresh_library_summary()
                self._apply_op_column_visibility()

            # Apply device-side "default library" change.
            new_dev_idx = default_dev_combo.GetSelection()
            new_dev = (
                dev_choices[new_dev_idx][1]
                if 0 <= new_dev_idx < len(dev_choices) else None
            )
            for d in devices:
                pointed_at_us = getattr(d, "default_matlib", "") == lib.name
                want = (d is new_dev)
                if want and not pointed_at_us:
                    d.default_matlib = lib.name
                    d.flush()
                elif pointed_at_us and not want:
                    d.default_matlib = ""
                    d.flush()
        finally:
            dlg.Destroy()

    def on_tree_selection(self, event):
        item = event.GetItem() if event else self.tree_library.GetSelection()
        if not item or not item.IsOk():
            self._clear_details()
            self._update_button_state()
            return
        data = self.tree_library.GetItemData(item)
        if not data:
            self._clear_details()
            self._update_button_state()
            return
        kind, obj = data
        if kind == KIND_CATEGORY:
            self._show_category(obj)
        elif kind == KIND_MATERIAL:
            self._show_material(obj)
        elif kind == KIND_THICKNESS:
            # Find the parent material so we can show full context.
            parent_item = self.tree_library.GetItemParent(item)
            parent_data = self.tree_library.GetItemData(parent_item)
            parent_mat = parent_data[1] if parent_data else None
            self._show_thickness(parent_mat, obj)
        self._update_button_state()

    def _clear_details(self):
        self.lbl_header.SetLabel("")
        self.lbl_subheader.SetLabel("")
        self.txt_notes.ChangeValue("")  # avoids firing a write-back event
        self.list_ops.DeleteAllItems()
        self._editing_target = None
        self._update_op_action_state()

    def _show_category(self, cat):
        self.lbl_header.SetLabel(_("Category: {name}").format(name=cat.name))
        n_sub = len(cat.categories)
        n_mat = len(cat.materials)
        self.lbl_subheader.SetLabel(
            _(
                "{n_sub} sub-categories, {n_mat} materials  —  "
                "select a material or thickness to edit operations"
            ).format(n_sub=n_sub, n_mat=n_mat)
        )
        self.txt_notes.ChangeValue(cat.notes or "")
        self.list_ops.DeleteAllItems()
        self._editing_target = (KIND_CATEGORY, cat)
        self._update_op_action_state()

    def _show_material(self, mat):
        self.lbl_header.SetLabel(_("Material: {name}").format(name=mat.name))
        if mat.thicknesses:
            self.lbl_subheader.SetLabel(
                _(
                    "{n} thicknesses  —  select a thickness to edit its operations"
                ).format(n=len(mat.thicknesses))
            )
        else:
            self.lbl_subheader.SetLabel(
                _(
                    "{n} operations  —  use + Op below to add one"
                ).format(n=len(mat.operations))
            )
        self.txt_notes.ChangeValue(mat.notes or "")
        self._fill_ops(mat.operations)
        self._editing_target = (KIND_MATERIAL, mat)
        self._update_op_action_state()

    def _show_thickness(self, mat, thk):
        mat_name = mat.name if mat is not None else ""
        self.lbl_header.SetLabel(
            _("Material: {name}").format(name=mat_name)
        )
        self.lbl_subheader.SetLabel(
            _("Thickness: {value}").format(value=thk.value)
        )
        self.txt_notes.ChangeValue(thk.notes or "")
        self._fill_ops(thk.operations)
        self._editing_target = (KIND_THICKNESS, thk)
        self._update_op_action_state()

    def _fill_ops(self, ops):
        self.list_ops.DeleteAllItems()
        last_idx = len(ops) - 1
        for i, op in enumerate(ops):
            # Col 0 holds just the Op short-name text. Row height is still
            # enforced by the image-list (icons set via SetItemColumnImage
            # on the Up/Down/Edit/Remove cells reference the same list).
            idx = self.list_ops.InsertItem(i, _short_op_type(op.type))
            self.list_ops.SetItem(idx, 1, op.id or "")
            self.list_ops.SetItem(idx, 2, op.label or "")
            settings = op.settings or {}
            self.list_ops.SetItem(
                idx, 3, self._power_to_display(settings.get("power"))
            )
            self.list_ops.SetItem(
                idx, 4, self._speed_to_display(settings.get("speed"))
            )
            self.list_ops.SetItem(idx, 5, _fmt(settings.get("passes")))
            self.list_ops.SetItem(idx, 6, _fmt(settings.get("frequency")))
            self.list_ops.SetItem(idx, 7, _summarize_effects(op.effects))
            # Up / Down icons appear only where the move is valid; the
            # icon-less cell is the user's signal that they're at a boundary.
            if i > 0:
                self.list_ops.SetItemColumnImage(
                    idx, self._OP_COL_UP, self._ops_up_iconidx
                )
            if i < last_idx:
                self.list_ops.SetItemColumnImage(
                    idx, self._OP_COL_DOWN, self._ops_down_iconidx
                )
            self.list_ops.SetItemColumnImage(
                idx, self._OP_COL_EDIT, self._ops_edit_iconidx
            )
            self.list_ops.SetItemColumnImage(
                idx, self._OP_COL_REMOVE, self._ops_trash_iconidx
            )

    # -- selection inspection ------------------------------------------------

    def _get_selection(self):
        """Return (kind, obj) for the currently selected tree item, or None."""
        item = self.tree_library.GetSelection()
        if not item or not item.IsOk():
            return None
        data = self.tree_library.GetItemData(item)
        return data  # may itself be None

    def _ancestors_of(self, item):
        """Walk up from ``item`` (exclusive of hidden root) collecting
        (kind, obj) pairs from innermost outward."""
        pairs = []
        tree = self.tree_library
        while item and item.IsOk():
            data = tree.GetItemData(item)
            if data:
                pairs.append(data)
            parent = tree.GetItemParent(item)
            # Stop at the hidden root (which has no data and may compare equal
            # to repeated GetItemParent calls).
            if not parent or not parent.IsOk() or parent == item:
                break
            item = parent
        return pairs

    def _placement_targets(self):
        """Return (target_category, target_material) for context-aware
        creation, based on the current tree selection.

        - target_category: the deepest Category ancestor (or None → library root)
        - target_material: the deepest Material ancestor (or None → no parent)
        """
        item = self.tree_library.GetSelection()
        if not item or not item.IsOk():
            return None, None
        target_cat = None
        target_mat = None
        for kind, obj in self._ancestors_of(item):
            if target_mat is None and kind == KIND_MATERIAL:
                target_mat = obj
            if target_cat is None and kind == KIND_CATEGORY:
                target_cat = obj
        return target_cat, target_mat

    def _find_tree_item(self, target_obj):
        """Locate the wxTreeItemId whose data is ``target_obj``. Returns None."""
        tree = self.tree_library
        root = tree.GetRootItem()
        if not root.IsOk():
            return None
        return self._walk_for(root, target_obj)

    def _walk_for(self, item, target_obj):
        tree = self.tree_library
        child, cookie = tree.GetFirstChild(item)
        while child.IsOk():
            data = tree.GetItemData(child)
            if data and data[1] is target_obj:
                return child
            found = self._walk_for(child, target_obj)
            if found is not None:
                return found
            child, cookie = tree.GetNextChild(item, cookie)
        return None

    # -- button enable/disable -----------------------------------------------

    def _update_button_state(self):
        has_lib = self._current_library is not None
        sel = self._get_selection()
        self.btn_new.Enable(self.service is not None)
        self.btn_copy.Enable(has_lib and sel is not None)
        self.btn_delete.Enable(has_lib and sel is not None)

    # -- New ▾ ---------------------------------------------------------------

    def on_new_clicked(self, event):
        menu = wx.Menu()

        has_lib = self._current_library is not None
        _target_cat, target_mat = self._placement_targets()

        item_cat = menu.Append(wx.ID_ANY, _("New Category..."))
        item_cat.Enable(has_lib)
        self.Bind(wx.EVT_MENU, lambda e: self._new_category(), item_cat)

        item_mat = menu.Append(wx.ID_ANY, _("New Material..."))
        item_mat.Enable(has_lib)
        self.Bind(wx.EVT_MENU, lambda e: self._new_material(), item_mat)

        item_thk = menu.Append(wx.ID_ANY, _("New Thickness..."))
        item_thk.Enable(has_lib and target_mat is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._new_thickness(), item_thk)

        self.PopupMenu(menu, self._below(self.btn_new))
        menu.Destroy()

    def _new_library(self):
        name = self._prompt_text(
            _("New Library"), _("Library name:"), _("New Library")
        )
        if not name:
            return
        unique = make_unique_name(name, self.service.library_names())
        try:
            self.service.create_library(unique)
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Cannot create"), wx.OK | wx.ICON_ERROR, self)
            return
        self.refresh_libraries(select_name=unique)

    def _new_category(self):
        if self._current_library is None:
            return
        name = self._prompt_text(
            _("New Category"), _("Category name:"), _("New Category")
        )
        if not name:
            return
        target_cat, _mat = self._placement_targets()
        container = target_cat if target_cat is not None else self._current_library
        existing = [c.name for c in container.categories]
        cat = Category(name=make_unique_name(name, existing))
        container.categories.append(cat)
        self._persist_and_select(cat)

    def _new_material(self):
        if self._current_library is None:
            return
        name = self._prompt_text(
            _("New Material"), _("Material name:"), _("New Material")
        )
        if not name:
            return
        target_cat, _mat = self._placement_targets()
        container = (
            target_cat if target_cat is not None
            else find_or_create_uncategorized(self._current_library)
        )
        existing = [m.name for m in container.materials]
        mat = MaterialEntry(name=make_unique_name(name, existing))
        container.materials.append(mat)
        self._persist_and_select(mat)

    def _new_thickness(self):
        if self._current_library is None:
            return
        _cat, target_mat = self._placement_targets()
        if target_mat is None:
            return
        value = self._prompt_text(
            _("New Thickness"), _("Thickness (e.g. 3mm):"), _("0mm")
        )
        if value is None:
            return  # user cancelled; empty value is OK
        existing = [t.value for t in target_mat.thicknesses]
        thk = ThicknessEntry(value=make_unique_name(value or "0mm", existing))
        target_mat.thicknesses.append(thk)
        self._persist_and_select(thk)

    # -- Copy ▾ --------------------------------------------------------------

    def on_copy_clicked(self, event):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        menu = wx.Menu()

        item_dup = menu.Append(wx.ID_ANY, _("Duplicate here"))
        self.Bind(wx.EVT_MENU, lambda e: self._duplicate_selected(), item_dup)

        # Copy to library submenu — only meaningful for Category & Material
        other_libs = [
            n for n in self.service.library_names()
            if n != self._current_library.name
        ]
        copy_submenu = wx.Menu()
        if kind in (KIND_CATEGORY, KIND_MATERIAL) and other_libs:
            for libname in other_libs:
                sub_item = copy_submenu.Append(wx.ID_ANY, libname)
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, n=libname: self._copy_to_library(n),
                    sub_item,
                )
            menu.AppendSubMenu(copy_submenu, _("Copy to library →"))
        else:
            placeholder = menu.AppendSubMenu(
                copy_submenu, _("Copy to library →")
            )
            placeholder.Enable(False)

        self.PopupMenu(menu, self._below(self.btn_copy))
        menu.Destroy()

    def _duplicate_selected(self):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        clone = clone_node(obj)
        if kind == KIND_CATEGORY:
            parent = find_parent(self._current_library, obj)
            if parent is None:
                return
            clone.name = make_unique_name(
                clone.name, [c.name for c in parent.categories]
            )
            idx = parent.categories.index(obj)
            parent.categories.insert(idx + 1, clone)
        elif kind == KIND_MATERIAL:
            parent = find_parent(self._current_library, obj)
            if parent is None:
                return
            clone.name = make_unique_name(
                clone.name, [m.name for m in parent.materials]
            )
            idx = parent.materials.index(obj)
            parent.materials.insert(idx + 1, clone)
        elif kind == KIND_THICKNESS:
            parent = find_parent(self._current_library, obj)
            if parent is None:
                return
            clone.value = make_unique_name(
                clone.value, [t.value for t in parent.thicknesses]
            )
            idx = parent.thicknesses.index(obj)
            parent.thicknesses.insert(idx + 1, clone)
        else:
            return
        self._persist_and_select(clone)

    def _copy_to_library(self, dest_lib_name):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        dest_lib = self.service.get_library(dest_lib_name)
        if dest_lib is None:
            return
        clone = clone_node(obj)
        if kind == KIND_CATEGORY:
            clone.name = make_unique_name(
                clone.name, [c.name for c in dest_lib.categories]
            )
            dest_lib.categories.append(clone)
        elif kind == KIND_MATERIAL:
            dest_cat = find_or_create_uncategorized(dest_lib)
            clone.name = make_unique_name(
                clone.name, [m.name for m in dest_cat.materials]
            )
            dest_cat.materials.append(clone)
        else:
            return
        self.service.save_library(dest_lib)
        wx.MessageBox(
            _("Copied to library '{name}'.").format(name=dest_lib_name),
            _("Copied"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    # -- Delete --------------------------------------------------------------

    def on_delete_clicked(self, event):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        label = getattr(obj, "name", None) or getattr(obj, "value", "")
        kind_label = {
            KIND_CATEGORY: _("category"),
            KIND_MATERIAL: _("material"),
            KIND_THICKNESS: _("thickness"),
        }.get(kind, _("item"))
        msg = _("Delete {kind} '{name}'? This cannot be undone.").format(
            kind=kind_label, name=label
        )
        with wx.MessageDialog(
            self, msg, _("Confirm delete"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return
        parent = find_parent(self._current_library, obj)
        if parent is None:
            return
        if kind == KIND_CATEGORY and obj in parent.categories:
            parent.categories.remove(obj)
        elif kind == KIND_MATERIAL and obj in parent.materials:
            parent.materials.remove(obj)
        elif kind == KIND_THICKNESS and obj in parent.thicknesses:
            parent.thicknesses.remove(obj)
        else:
            return
        self._persist_and_select(None)

    # -- right-click menu (Phase 4) -----------------------------------------

    def on_tree_right_click(self, event):
        item = event.GetItem()
        if item and item.IsOk():
            self.tree_library.SelectItem(item)
        self._show_tree_context_menu()

    def _show_tree_context_menu(self):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        menu = wx.Menu()

        # New ▸ submenu (no "Library" here — that's toolbar-only)
        new_sub = wx.Menu()
        _target_cat, target_mat = self._placement_targets()
        n_cat = new_sub.Append(wx.ID_ANY, _("Category..."))
        self.Bind(wx.EVT_MENU, lambda e: self._new_category(), n_cat)
        n_mat = new_sub.Append(wx.ID_ANY, _("Material..."))
        self.Bind(wx.EVT_MENU, lambda e: self._new_material(), n_mat)
        n_thk = new_sub.Append(wx.ID_ANY, _("Thickness..."))
        n_thk.Enable(target_mat is not None)
        self.Bind(wx.EVT_MENU, lambda e: self._new_thickness(), n_thk)
        menu.AppendSubMenu(new_sub, _("New"))

        menu.AppendSeparator()

        rename_item = menu.Append(wx.ID_ANY, _("Rename..."))
        self.Bind(wx.EVT_MENU, lambda e: self._rename_selected(), rename_item)

        dup_item = menu.Append(wx.ID_ANY, _("Duplicate"))
        self.Bind(wx.EVT_MENU, lambda e: self._duplicate_selected(), dup_item)

        # Move sub-category up to library root — drag-to-empty-space is
        # awkward in densely populated trees, so expose it explicitly here.
        if kind == KIND_CATEGORY:
            parent = find_parent(self._current_library, obj)
            if parent is not None and parent is not self._current_library:
                root_item = menu.Append(wx.ID_ANY, _("Move to library root"))
                self.Bind(
                    wx.EVT_MENU, lambda e: self._move_to_root(), root_item
                )

        # Copy to library ▸ submenu
        other_libs = [
            n for n in self.service.library_names()
            if n != self._current_library.name
        ]
        copy_sub = wx.Menu()
        if kind in (KIND_CATEGORY, KIND_MATERIAL) and other_libs:
            for libname in other_libs:
                sub_item = copy_sub.Append(wx.ID_ANY, libname)
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, n=libname: self._copy_to_library(n),
                    sub_item,
                )
            menu.AppendSubMenu(copy_sub, _("Copy to library →"))
        else:
            placeholder = menu.AppendSubMenu(
                copy_sub, _("Copy to library →")
            )
            placeholder.Enable(False)

        menu.AppendSeparator()

        export_item = menu.Append(wx.ID_ANY, _("Export..."))
        export_item.Enable(kind in (KIND_CATEGORY, KIND_MATERIAL))
        self.Bind(wx.EVT_MENU, lambda e: self._export_selected(), export_item)

        menu.AppendSeparator()

        remove_item = menu.Append(wx.ID_ANY, _("Remove..."))
        self.Bind(wx.EVT_MENU, lambda e: self.on_delete_clicked(None), remove_item)

        self.PopupMenu(menu)
        menu.Destroy()

    # -- rename / export (Phase 4) ------------------------------------------

    def _rename_selected(self):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        parent = find_parent(self._current_library, obj)
        if parent is None:
            return
        if kind == KIND_THICKNESS:
            current = obj.value
            new = self._prompt_text(
                _("Rename Thickness"), _("Thickness value:"), current
            )
            if new is None:
                return
            new = new.strip() or current
            if new == current:
                return
            existing = [t.value for t in parent.thicknesses if t is not obj]
            obj.value = make_unique_name(new, existing)
        else:
            current = obj.name
            new = self._prompt_text(_("Rename"), _("New name:"), current)
            if new is None:
                return
            new = new.strip()
            if not new or new == current:
                return
            if kind == KIND_CATEGORY:
                existing = [c.name for c in parent.categories if c is not obj]
            else:  # KIND_MATERIAL
                existing = [m.name for m in parent.materials if m is not obj]
            obj.name = make_unique_name(new, existing)
        self._persist_and_select(obj)

    def _export_selected(self):
        sel = self._get_selection()
        if sel is None:
            return
        kind, obj = sel
        if kind == KIND_THICKNESS:
            return  # not exportable on its own
        default_name = getattr(obj, "name", "export")
        with wx.FileDialog(
            self,
            message=_("Export to .meerlib"),
            defaultFile=f"{default_name}.meerlib",
            wildcard=_("MeerK40t Library (*.meerlib)|*.meerlib"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            lib = wrap_for_export(obj)
            save_library_to_file(lib, path)
        except Exception as exc:
            wx.MessageBox(
                str(exc), _("Export failed"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return
        wx.MessageBox(
            _("Exported to {path}").format(path=path),
            _("Exported"),
            wx.OK | wx.ICON_INFORMATION, self,
        )

    def _move_to_root(self):
        sel = self._get_selection()
        if sel is None or self._current_library is None:
            return
        kind, obj = sel
        if kind != KIND_CATEGORY:
            return
        if move_node(
            self._current_library, KIND_CATEGORY, obj, None, None
        ):
            self._persist_and_select(obj)

    # -- drag-and-drop (Phase 5) --------------------------------------------

    def on_tree_begin_drag(self, event):
        item = event.GetItem()
        if not item or not item.IsOk():
            return
        data = self.tree_library.GetItemData(item)
        if not data:
            return
        self._drag_data = data
        event.Allow()

    def on_tree_end_drag(self, event):
        src = self._drag_data
        self._drag_data = None
        if src is None or self._current_library is None:
            return
        dst_item = event.GetItem()
        if dst_item and dst_item.IsOk():
            dst_data = self.tree_library.GetItemData(dst_item)
        else:
            dst_data = None  # dropped on empty space → library root
        src_kind, src_obj = src
        dst_kind, dst_obj = (None, None) if dst_data is None else dst_data
        if not move_node(
            self._current_library, src_kind, src_obj, dst_kind, dst_obj
        ):
            return  # invalid move — silently rejected
        self._persist_and_select(src_obj)

    # -- right-pane editing (Phase 7) ---------------------------------------

    def _editable_ops(self):
        """Return the list of MaterialOperation objects we should edit, or None.

        A Material with thicknesses uses its thicknesses as op-bearers, so its
        own .operations list is not surfaced for editing in the UI.
        """
        if self._editing_target is None:
            return None
        kind, obj = self._editing_target
        if kind == KIND_THICKNESS:
            return obj.operations
        if kind == KIND_MATERIAL and not obj.thicknesses:
            return obj.operations
        return None

    def _selected_op_rows(self):
        """Return a list of currently-selected row indices in the ops list."""
        rows = []
        item = -1
        while True:
            item = self.list_ops.GetNextItem(
                item, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED
            )
            if item == -1:
                break
            rows.append(item)
        return rows

    def _make_single_selection(self, row):
        """Replace whatever's selected with just ``row``. Multi-select needs
        explicit deselect of others since plain Select() only adds."""
        for r in self._selected_op_rows():
            if r != row:
                self.list_ops.Select(r, on=0)
        self.list_ops.Select(row, on=1)
        self.list_ops.Focus(row)

    def _update_op_action_state(self):
        ops = self._editable_ops()
        ops_present = ops is not None
        self.btn_op_add.Enable(ops_present)
        # Push needs library ops to send. Pull writes into the library entry,
        # so the target must be op-bearing (even if currently empty).
        self.btn_op_push.Enable(ops_present and len(ops) > 0)
        self.btn_op_pull.Enable(ops_present)

        # Dynamic tooltip on the Add button so the disabled state explains itself.
        if ops_present:
            tip = _("Add a new operation (choose type)")
        elif self._editing_target is None:
            tip = _("Select a material or thickness in the tree first")
        else:
            kind, obj = self._editing_target
            if kind == KIND_CATEGORY:
                tip = _(
                    "Categories don't hold operations. "
                    "Select a material or thickness instead."
                )
            elif kind == KIND_MATERIAL and obj.thicknesses:
                tip = _(
                    "This material has thicknesses. "
                    "Select a thickness below to add operations to it."
                )
            else:
                tip = _("Operations aren't editable for this selection")
        self.btn_op_add.SetToolTip(tip)

    def on_op_row_selection(self, event):
        self._update_op_action_state()
        if event is not None:
            event.Skip()

    # Notes -----------------------------------------------------------------

    def on_notes_text_changed(self, event):
        """Update the in-memory model on every keystroke. Disk write is
        deferred to focus loss / shutdown so we don't pound the FS."""
        if self._editing_target is None:
            return
        _kind, obj = self._editing_target
        if not hasattr(obj, "notes"):
            return
        new_text = self.txt_notes.GetValue()
        if obj.notes != new_text:
            obj.notes = new_text

    def on_notes_kill_focus(self, event):
        event.Skip()
        if self._editing_target is None or self._current_library is None:
            return
        _kind, obj = self._editing_target
        if not hasattr(obj, "notes"):
            return
        # Model is already current via on_notes_text_changed; just flush.
        self.service.save_library(self._current_library)

    # Op cell editing -------------------------------------------------------

    def on_op_edit_end(self, event):
        ops = self._editable_ops()
        if ops is None:
            event.Veto()
            return
        row = event.GetIndex()
        col = event.GetColumn()
        new = event.GetLabel()
        if row < 0 or row >= len(ops):
            event.Veto()
            return
        op = ops[row]
        # Col 0 (Op) is vetoed in on_op_begin_edit; type changes go via
        # the right-click "Change type" submenu.
        if col == 1:
            op.id = new
        elif col == 2:
            op.label = new
        elif col == 3:
            try:
                op.settings["power"] = self._power_from_display(new)
            except ValueError:
                event.Veto()
                return
        elif col == 4:
            try:
                op.settings["speed"] = self._speed_from_display(new)
            except ValueError:
                event.Veto()
                return
        elif col == 5:
            try:
                op.settings["passes"] = int(new)
            except ValueError:
                event.Veto()
                return
            normalize_passes_setting(op.settings)
        elif col == 6:
            try:
                op.settings["frequency"] = float(new)
            except ValueError:
                event.Veto()
                return
        self._persist_ops_only(preserve_selection=row)

    # Add / Remove / Reorder -----------------------------------------------

    _OP_ID_PREFIX = {
        "op cut": "C",
        "op engrave": "E",
        "op raster": "R",
        "op image": "I",
        "op dots": "D",
        "op hatch": "H",
    }

    def on_op_add_clicked(self, event):
        if self._editable_ops() is None:
            return
        menu = wx.Menu()
        for t in VALID_OP_TYPES:
            item = menu.Append(wx.ID_ANY, t)
            self.Bind(
                wx.EVT_MENU, lambda e, ty=t: self._add_op_of_type(ty), item
            )
        self.PopupMenu(menu, self._below(self.btn_op_add))
        menu.Destroy()

    def _add_op_of_type(self, op_type):
        ops = self._editable_ops()
        if ops is None:
            return
        prefix = self._OP_ID_PREFIX.get(op_type, "O")
        n = sum(1 for o in ops if o.id.startswith(prefix)) + 1
        ops.append(MaterialOperation(type=op_type, id=f"{prefix}{n}", label=""))
        self._persist_ops_only(preserve_selection=len(ops) - 1)

    def on_op_remove_clicked(self, event):
        ops = self._editable_ops()
        if ops is None:
            return
        row = self.list_ops.GetFirstSelected()
        if row < 0 or row >= len(ops):
            return
        self._remove_op_with_confirm(row)

    def _remove_op_with_confirm(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        label = op.label or op.id or op.type or _("(unnamed)")
        with wx.MessageDialog(
            self,
            _("Remove operation '{label}'? This cannot be undone.").format(
                label=label
            ),
            _("Confirm remove"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return
        del ops[row]
        new_sel = min(row, len(ops) - 1)
        self._persist_ops_only(
            preserve_selection=new_sel if new_sel >= 0 else None
        )

    # Push / Pull — sync ops between the library and the document branch -----

    def on_op_push_clicked(self, event):
        if not self._editable_ops():
            return
        menu = wx.Menu()
        rep = menu.Append(wx.ID_ANY, _("Replace Document Operations"))
        self.Bind(
            wx.EVT_MENU, lambda e: self._push_to_document(replace=True), rep
        )
        app = menu.Append(wx.ID_ANY, _("Append Document Operations"))
        self.Bind(
            wx.EVT_MENU, lambda e: self._push_to_document(replace=False), app
        )
        self.PopupMenu(menu, self._below(self.btn_op_push))
        menu.Destroy()

    def on_op_pull_clicked(self, event):
        if self._editable_ops() is None:
            return
        menu = wx.Menu()
        rep = menu.Append(wx.ID_ANY, _("Replace Library Operations"))
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._pull_from_document(replace=True),
            rep,
        )
        app = menu.Append(wx.ID_ANY, _("Append Library Operations"))
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._pull_from_document(replace=False),
            app,
        )
        self.PopupMenu(menu, self._below(self.btn_op_pull))
        menu.Destroy()

    def _push_to_document(self, replace: bool):
        ops = self._editable_ops()
        if not ops:
            return
        elements = self.context.elements
        op_branch = elements.op_branch
        if replace:
            existing = list(
                c for c in op_branch.children
                if not c.type.startswith("branch")
                and not c.type.startswith("ref")
            )
            n_existing = len(existing)
            if n_existing > 0:
                with wx.MessageDialog(
                    self,
                    _(
                        "Replace the {n} document operation(s) with the "
                        "{m} operation(s) from this library entry?"
                    ).format(n=n_existing, m=len(ops)),
                    _("Confirm replace"),
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                ) as dlg:
                    if dlg.ShowModal() != wx.ID_YES:
                        return
        try:
            with elements.undoscope("Push from library"):
                if replace:
                    for child in list(op_branch.children):
                        if child.type.startswith("branch") or child.type.startswith("ref"):
                            continue
                        child.remove_node()
                for mat_op in ops:
                    self._instantiate_op_into(op_branch, mat_op)
        except AttributeError:
            # undoscope unavailable: do it without
            if replace:
                for child in list(op_branch.children):
                    if child.type.startswith("branch") or child.type.startswith("ref"):
                        continue
                    child.remove_node()
            for mat_op in ops:
                self._instantiate_op_into(op_branch, mat_op)
        elements.signal("rebuild_tree", "operations")

    def _instantiate_op_into(self, op_branch, mat_op):
        """Create a real document op node from a MaterialOperation,
        including its effect children."""
        # Defensive: ensure passes_custom mirrors passes even if the
        # library was authored before normalize_passes_setting existed.
        normalize_passes_setting(mat_op.settings)
        node = op_branch.add(type=mat_op.type, **mat_op.settings)
        try:
            node.id = mat_op.id
        except Exception:
            pass
        try:
            node.label = mat_op.label
        except Exception:
            pass
        for eff in mat_op.effects:
            try:
                node.add(type=eff.type, **eff.settings)
            except Exception:
                pass
        return node

    def _pull_from_document(self, replace: bool):
        if self._editing_target is None or self._current_library is None:
            return
        kind, target = self._editing_target
        if kind not in (KIND_MATERIAL, KIND_THICKNESS):
            return
        if kind == KIND_MATERIAL and target.thicknesses:
            return  # not op-bearing

        doc_ops = list(self.context.elements.ops())
        if not doc_ops:
            wx.MessageBox(
                _("There are no operations in the document to pull."),
                _("Nothing to pull"),
                wx.OK | wx.ICON_INFORMATION, self,
            )
            return

        if replace and target.operations:
            with wx.MessageDialog(
                self,
                _(
                    "Replace the {n} operation(s) in this library entry "
                    "with the {m} from the document?"
                ).format(n=len(target.operations), m=len(doc_ops)),
                _("Confirm replace"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            ) as dlg:
                if dlg.ShowModal() != wx.ID_YES:
                    return
            target.operations.clear()

        for node in doc_ops:
            target.operations.append(self._node_to_mat_op(node))
        self._persist_ops_only(preserve_selection=None)

    def _node_to_mat_op(self, node):
        """Convert a live document op node to a MaterialOperation."""
        settings = _scrape_op_settings(node)
        effects = []
        children = getattr(node, "children", None) or ()
        for child in children:
            child_type = getattr(child, "type", "")
            if isinstance(child_type, str) and child_type.startswith("effect "):
                effects.append(
                    MaterialEffect(
                        type=child_type,
                        settings=_scrape_op_settings(child),
                    )
                )
        return MaterialOperation(
            type=getattr(node, "type", "op cut"),
            id=getattr(node, "id", "") or "",
            label=getattr(node, "label", "") or "",
            settings=settings,
            effects=effects,
        )

    def _move_op_up(self, row):
        ops = self._editable_ops()
        if ops is None or row <= 0 or row >= len(ops):
            return
        ops[row - 1], ops[row] = ops[row], ops[row - 1]
        self._persist_ops_only(preserve_selection=row - 1)

    def _move_op_down(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops) - 1:
            return
        ops[row + 1], ops[row] = ops[row], ops[row + 1]
        self._persist_ops_only(preserve_selection=row + 1)

    # Right-click on op row -------------------------------------------------

    def on_op_right_click(self, event):
        ops = self._editable_ops()
        if ops is None:
            return
        row = event.GetIndex()
        if row < 0 or row >= len(ops):
            return
        selected = self._selected_op_rows()
        # If the right-clicked row is part of an existing multi-selection,
        # honor the multi-selection. Otherwise reduce to just this row.
        if row in selected and len(selected) > 1:
            self._show_multi_op_menu(sorted(selected))
            return
        self._make_single_selection(row)
        self._show_single_op_menu(row)

    def _show_single_op_menu(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        last_idx = len(ops) - 1
        menu = wx.Menu()

        edit_item = menu.Append(wx.ID_ANY, _("Edit Operation..."))
        self.Bind(
            wx.EVT_MENU,
            lambda e, r=row: self._open_op_editor(r),
            edit_item,
        )

        dup_item = menu.Append(wx.ID_ANY, _("Duplicate Operation"))
        self.Bind(
            wx.EVT_MENU,
            lambda e, r=row: self._duplicate_op(r),
            dup_item,
        )

        push_item = menu.Append(wx.ID_ANY, _("Push to Document"))
        push_item.SetHelp(
            _("Append this operation to the document's operations branch")
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e, r=row: self._push_subset_to_document([r]),
            push_item,
        )

        rm_item = menu.Append(wx.ID_ANY, _("Remove Operation"))
        self.Bind(wx.EVT_MENU, lambda e: self.on_op_remove_clicked(None), rm_item)

        menu.AppendSeparator()

        up_item = menu.Append(wx.ID_ANY, _("Move up"))
        up_item.Enable(row > 0)
        self.Bind(
            wx.EVT_MENU, lambda e, r=row: self._move_op_up(r), up_item
        )

        down_item = menu.Append(wx.ID_ANY, _("Move down"))
        down_item.Enable(row < last_idx)
        self.Bind(
            wx.EVT_MENU, lambda e, r=row: self._move_op_down(r), down_item
        )

        menu.AppendSeparator()

        type_sub = wx.Menu()
        for t in VALID_OP_TYPES:
            item = type_sub.Append(
                wx.ID_ANY, _short_op_type(t), kind=wx.ITEM_CHECK
            )
            item.Check(t == op.type)
            self.Bind(
                wx.EVT_MENU,
                lambda e, r=row, ty=t: self._change_op_type(r, ty),
                item,
            )
        menu.AppendSubMenu(type_sub, _("Change type"))

        self.list_ops.PopupMenu(menu)
        menu.Destroy()

    def _show_multi_op_menu(self, rows):
        """Right-click menu for multiple selected operations. Reduced to
        actions that make sense in bulk: Push (always append) and Remove."""
        menu = wx.Menu()
        push_item = menu.Append(
            wx.ID_ANY, _("Push {n} Operations to Document").format(n=len(rows))
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._push_subset_to_document(rows),
            push_item,
        )
        rm_item = menu.Append(
            wx.ID_ANY, _("Remove {n} Operations").format(n=len(rows))
        )
        self.Bind(
            wx.EVT_MENU,
            lambda e: self._remove_op_rows_with_confirm(rows),
            rm_item,
        )
        self.list_ops.PopupMenu(menu)
        menu.Destroy()

    def _push_subset_to_document(self, rows):
        """Append a subset of the library entry's ops to the document.
        Right-click Push is always 'append', never 'replace'."""
        ops_full = self._editable_ops()
        if ops_full is None:
            return
        subset = [
            ops_full[r] for r in rows if 0 <= r < len(ops_full)
        ]
        if not subset:
            return
        elements = self.context.elements
        op_branch = elements.op_branch
        try:
            with elements.undoscope("Push from library (subset)"):
                for mat_op in subset:
                    self._instantiate_op_into(op_branch, mat_op)
        except AttributeError:
            for mat_op in subset:
                self._instantiate_op_into(op_branch, mat_op)
        elements.signal("rebuild_tree", "operations")

    def _remove_op_rows_with_confirm(self, rows):
        ops = self._editable_ops()
        if ops is None:
            return
        # De-dup, drop out-of-range, sort descending so deletions don't
        # shift the indices of yet-to-be-deleted rows.
        rows = sorted(
            {r for r in rows if 0 <= r < len(ops)}, reverse=True
        )
        if not rows:
            return
        with wx.MessageDialog(
            self,
            _(
                "Remove {n} operation(s)? This cannot be undone."
            ).format(n=len(rows)),
            _("Confirm remove"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return
        for r in rows:
            del ops[r]
        self._persist_ops_only(preserve_selection=None)

    def _duplicate_op(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        clone = clone_node(ops[row])
        # Give the clone a fresh ID based on its type's prefix.
        prefix = self._OP_ID_PREFIX.get(clone.type, "O")
        n = sum(1 for o in ops if o.id.startswith(prefix)) + 1
        clone.id = f"{prefix}{n}"
        ops.insert(row + 1, clone)
        self._persist_ops_only(preserve_selection=row + 1)

    def _change_op_type(self, row, new_type):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        if op.type == new_type:
            return  # no-op
        # If we're moving from an effects-supporting type (cut/engrave)
        # to one that doesn't support effects, the existing effects can't
        # apply at the new type. Warn and clear them on confirm.
        if (
            op.effects
            and op.type in self._OPS_THAT_SUPPORT_EFFECTS
            and new_type not in self._OPS_THAT_SUPPORT_EFFECTS
        ):
            with wx.MessageDialog(
                self,
                _(
                    "Changing this operation to '{new}' will remove "
                    "its {n} effect(s). Continue?"
                ).format(
                    new=_short_op_type(new_type), n=len(op.effects)
                ),
                _("Effects will be removed"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            ) as dlg:
                if dlg.ShowModal() != wx.ID_YES:
                    return
            op.effects.clear()
        op.type = new_type
        self._persist_ops_only(preserve_selection=row)

    # Effects column — click handling + popup menu --------------------------

    def on_op_begin_edit(self, event):
        # Block in-place editing on the non-text columns. Op (col 0) is
        # also non-editable inline — type changes go through the right-
        # click menu's "Change type" submenu so we don't have to validate
        # against VALID_OP_TYPES at the cell level.
        col = event.GetColumn()
        if col in (
            0,                          # Op (use right-click → Change type)
            self._OP_COL_EFFECTS,
            self._OP_COL_UP,
            self._OP_COL_DOWN,
            self._OP_COL_EDIT,
            self._OP_COL_REMOVE,
        ):
            event.Veto()
            return
        event.Skip()

    def on_op_left_down(self, event):
        # Detect clicks on the icon columns; other clicks pass through
        # to the listctrl's normal selection behavior.
        try:
            row, _flags, col = self.list_ops.HitTestSubItem(event.GetPosition())
        except Exception:
            row, col = -1, -1
        if row >= 0:
            ops = self._editable_ops()
            if ops is not None and 0 <= row < len(ops):
                # Icon-cell actions are scoped to the clicked row, so
                # collapse the selection to just that row first.
                # Otherwise (in multi-select mode) Select() would only
                # add to the existing selection, leaving stale highlights.
                if col == self._OP_COL_EFFECTS:
                    self._make_single_selection(row)
                    self._show_effects_menu(row)
                    return
                if col == self._OP_COL_UP:
                    self._make_single_selection(row)
                    self._move_op_up(row)
                    return
                if col == self._OP_COL_DOWN:
                    self._make_single_selection(row)
                    self._move_op_down(row)
                    return
                if col == self._OP_COL_EDIT:
                    self._make_single_selection(row)
                    self._open_op_editor(row)
                    return
                if col == self._OP_COL_REMOVE:
                    self._make_single_selection(row)
                    self._remove_op_with_confirm(row)
                    return
        event.Skip()

    # Effects only attach to vector ops in meerk40t (raster/image/dots
    # rasterize the geometry themselves and aren't compatible with hatch /
    # wobble / warp wrappers).
    _OPS_THAT_SUPPORT_EFFECTS = frozenset({"op cut", "op engrave"})

    def _show_effects_menu(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        # No menu at all when the op type can't support effects AND has
        # none stored — there's nothing useful for the user to do.
        if (
            op.type not in self._OPS_THAT_SUPPORT_EFFECTS
            and not op.effects
        ):
            return
        menu = wx.Menu()
        last_idx = len(op.effects) - 1
        # One submenu per existing effect, in order.
        for eff_idx, eff in enumerate(op.effects):
            sub = wx.Menu()

            edit_item = sub.Append(wx.ID_ANY, _("Edit..."))
            self.Bind(
                wx.EVT_MENU,
                lambda e, r=row, i=eff_idx: self._edit_effect(r, i),
                edit_item,
            )

            remove_item = sub.Append(wx.ID_ANY, _("Remove"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, r=row, i=eff_idx: self._remove_effect(r, i),
                remove_item,
            )

            sub.AppendSeparator()

            up_item = sub.Append(wx.ID_ANY, _("Move up"))
            up_item.Enable(eff_idx > 0)
            self.Bind(
                wx.EVT_MENU,
                lambda e, r=row, i=eff_idx: self._move_effect(r, i, -1),
                up_item,
            )

            down_item = sub.Append(wx.ID_ANY, _("Move down"))
            down_item.Enable(eff_idx < last_idx)
            self.Bind(
                wx.EVT_MENU,
                lambda e, r=row, i=eff_idx: self._move_effect(r, i, +1),
                down_item,
            )

            menu.AppendSubMenu(sub, short_effect_name(eff.type))

        # Add Effect ▸ is only available when the op type supports effects
        # (cut / engrave). Existing effects above can still be edited /
        # removed regardless, so users can clean up after a type change.
        if op.type in self._OPS_THAT_SUPPORT_EFFECTS:
            if op.effects:
                menu.AppendSeparator()
            add_sub = wx.Menu()
            types = discover_effect_types()
            if not types:
                placeholder = add_sub.Append(wx.ID_ANY, _("(none discovered)"))
                placeholder.Enable(False)
            else:
                for t in types:
                    add_item = add_sub.Append(wx.ID_ANY, short_effect_name(t))
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, r=row, ty=t: self._add_effect(r, ty),
                        add_item,
                    )
            menu.AppendSubMenu(add_sub, _("Add effect ▸"))
        self.list_ops.PopupMenu(menu)
        menu.Destroy()

    def _move_effect(self, row, eff_idx, delta):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        new_idx = eff_idx + delta
        if new_idx < 0 or new_idx >= len(op.effects):
            return
        op.effects[eff_idx], op.effects[new_idx] = (
            op.effects[new_idx], op.effects[eff_idx]
        )
        self._persist_ops_only(preserve_selection=row)

    def _add_effect(self, row, effect_type):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        # Seed settings from the schema's defaults.
        schema = get_effect_schema(effect_type)
        seed = {f["key"]: f["default"] for f in schema}
        new_eff = MaterialEffect(type=effect_type, settings=seed)
        # Open the editor so the user can confirm/adjust before it sticks.
        edited = self._run_effect_editor(new_eff)
        if edited is None:
            return  # cancelled — don't add
        ops[row].effects.append(edited)
        self._persist_ops_only(preserve_selection=row)

    def _edit_effect(self, row, eff_idx):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        if eff_idx < 0 or eff_idx >= len(op.effects):
            return
        edited = self._run_effect_editor(op.effects[eff_idx])
        if edited is None:
            return
        op.effects[eff_idx] = edited
        self._persist_ops_only(preserve_selection=row)

    def _remove_effect(self, row, eff_idx):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        op = ops[row]
        if eff_idx < 0 or eff_idx >= len(op.effects):
            return
        with wx.MessageDialog(
            self,
            _("Remove effect '{name}'?").format(
                name=short_effect_name(op.effects[eff_idx].type)
            ),
            _("Confirm remove"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_YES:
                return
        del op.effects[eff_idx]
        self._persist_ops_only(preserve_selection=row)

    def _run_effect_editor(self, effect):
        """Show the effect-edit dialog. Returns the updated effect on OK, or
        None on cancel."""
        schema = get_effect_schema(effect.type)
        if not schema:
            # Unknown effect type — show a minimal read-only dialog so the
            # user at least sees what's stored and can cancel/remove.
            wx.MessageBox(
                _(
                    "No editor available for effect type '{type}'.\n"
                    "Stored settings: {settings}"
                ).format(type=effect.type, settings=effect.settings),
                _("Unknown effect"),
                wx.OK | wx.ICON_INFORMATION, self,
            )
            return None
        dlg = EffectEditorDialog(self, effect, schema)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return dlg.get_result()
        finally:
            dlg.Destroy()

    # Operation editor dialog (reuses meerk40t's ParameterPanel) -----------

    def _open_op_editor(self, row):
        ops = self._editable_ops()
        if ops is None or row < 0 or row >= len(ops):
            return
        mat_op = ops[row]
        lib = self._current_library
        driver = lib.driver if lib is not None else ""
        use_percent = bool(lib and lib.power_unit == "percent")
        use_mm_min = bool(lib and lib.speed_unit == "mm/min")
        dlg = OperationEditorDialog(
            self, self.context, mat_op,
            driver=driver,
            use_percent=use_percent,
            use_mm_min=use_mm_min,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            updated = dlg.get_result()
            if updated is None:
                return
            mat_op.id = updated["id"]
            mat_op.label = updated["label"]
            mat_op.settings = updated["settings"]
            normalize_passes_setting(mat_op.settings)
        finally:
            dlg.Destroy()
        # Refresh the row so power/speed/passes/etc. visibly update.
        self._persist_ops_only(preserve_selection=row)

    # Persistence helper for ops-only edits ---------------------------------

    def _persist_ops_only(self, preserve_selection=None):
        """Save current library and refresh the ops list display only.

        Avoids rebuilding the tree, which would lose tree selection.
        """
        if self._current_library is None:
            return
        self.service.save_library(self._current_library)
        ops = self._editable_ops()
        if ops is not None:
            self._fill_ops(ops)
            if preserve_selection is not None and 0 <= preserve_selection < len(ops):
                self.list_ops.Select(preserve_selection)
                self.list_ops.EnsureVisible(preserve_selection)
        self._update_op_action_state()

    # -- shared helpers ------------------------------------------------------

    def _below(self, ctrl):
        """Return a wx.Point just under the given control, in self's client
        coords. Works regardless of where ``ctrl`` lives in the widget tree
        (right_panel, the panel itself, etc.)."""
        parent = ctrl.GetParent()
        pos = parent.ClientToScreen(ctrl.GetPosition())
        pos = self.ScreenToClient(pos)
        pos.y += ctrl.GetSize().GetHeight()
        return pos

    def _prompt_text(self, title, label, default):
        with wx.TextEntryDialog(self, label, title, default) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return dlg.GetValue().strip()

    def _persist_and_select(self, item_to_select):
        if self._current_library is None:
            return
        self.service.save_library(self._current_library)
        self._populate_tree()
        if item_to_select is not None:
            tree_item = self._find_tree_item(item_to_select)
            if tree_item is not None:
                self.tree_library.SelectItem(tree_item)
                self.tree_library.EnsureVisible(tree_item)
        else:
            self._clear_details()
        self._update_button_state()

    # -- MWindow hooks -------------------------------------------------------

    def set_parent(self, par):
        self.parent_panel = par

    def pane_show(self):
        self.refresh_libraries()

    def pane_hide(self):
        pass


def _fmt(v):
    if v is None:
        return ""
    return str(v)


def _summarize_effects(effects):
    """Comma-separated short names for the Effects cell, or '' for none."""
    if not effects:
        return ""
    return ", ".join(short_effect_name(e.type) for e in effects)


def _short_op_type(full: str) -> str:
    """Strip the canonical 'op ' prefix for the display cell."""
    if isinstance(full, str) and full.startswith("op "):
        return full[3:]
    return full or ""


def _canonical_op_type(text: str) -> str:
    """Inverse of _short_op_type: accept either 'raster' or 'op raster' from
    the user and return the canonical 'op raster' for storage. Returns the
    original text if it's not recognized — caller validates."""
    if not isinstance(text, str):
        return text
    t = text.strip().lower()
    if not t:
        return t
    if t.startswith("op "):
        return t
    return f"op {t}"


class EffectEditorDialog(wx.Dialog):
    """Renders an effect's schema fields as a form. Used for both Add and Edit.

    The schema is a list of dicts: {key, label, type, default, [choices]}.
    ``type`` is one of "length", "angle", "int", "float", "bool", "choice",
    "string". Length and Angle inputs are validated against meerk40t's
    parsers; numeric fields are parsed as int/float.
    """

    def __init__(self, parent, effect, schema):
        super().__init__(
            parent,
            title=_("Edit effect: {name}").format(
                name=short_effect_name(effect.type)
            ),
        )
        self._effect_type = effect.type
        self._schema = schema
        self._field_widgets = {}  # key -> (widget, field_type)
        self._result = None

        outer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        grid.AddGrowableCol(1, 1)

        for field in schema:
            key = field["key"]
            ftype = field["type"]
            label = wxStaticText(self, wx.ID_ANY, f"{field['label']}:")
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            current = effect.settings.get(key, field.get("default"))
            widget = self._make_widget(ftype, field, current)
            self._field_widgets[key] = (widget, ftype)
            grid.Add(widget, 1, wx.EXPAND)

        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(
            btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12
        )
        self.SetSizerAndFit(outer)
        # Intercept OK so we can validate before closing.
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event):
        try:
            self._result = self._build_result()
        except ValueError as exc:
            wx.MessageBox(
                str(exc), _("Invalid value"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return  # don't close — let the user fix it
        event.Skip()  # OK; allow the dialog to close

    def _make_widget(self, ftype, field, current):
        if ftype == "bool":
            w = wx.CheckBox(self, wx.ID_ANY, "")
            w.SetValue(bool(current))
            return w
        if ftype == "choice":
            w = wxComboBox(
                self, wx.ID_ANY,
                choices=list(field["choices"]),
                style=wx.CB_READONLY,
            )
            if current in field["choices"]:
                w.SetStringSelection(current)
            elif field["choices"]:
                w.SetSelection(0)
            return w
        # text fields: length, angle, int, float, string
        w = TextCtrl(self, wx.ID_ANY, _format_field_value(current))
        return w

    def get_result(self):
        """Return the validated effect, or None if OK was never confirmed."""
        return self._result

    def _build_result(self):
        new_settings = {}
        for field in self._schema:
            key = field["key"]
            ftype = field["type"]
            widget, _ = self._field_widgets[key]
            value = self._read_widget(widget, ftype, field)
            new_settings[key] = value
        return MaterialEffect(type=self._effect_type, settings=new_settings)

    def _read_widget(self, widget, ftype, field):
        if ftype == "bool":
            return bool(widget.GetValue())
        if ftype == "choice":
            return widget.GetStringSelection() or field.get("default", "")
        text = widget.GetValue().strip()
        if ftype == "int":
            return int(text) if text else int(field.get("default", 0))
        if ftype == "float":
            return float(text) if text else float(field.get("default", 0.0))
        if ftype == "length":
            # Validate via meerk40t's Length parser but store the raw string
            # exactly as meerk40t stores it on effect nodes.
            from meerk40t.core.units import Length
            Length(text)  # raises on bad input
            return text
        if ftype == "angle":
            from meerk40t.core.units import Angle
            Angle(text)
            return text
        # string fallthrough
        return text


def _format_field_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


# ---------------------------------------------------------------------------
# Operation editor — hosts meerk40t's existing ParameterPanel on a temp node
# ---------------------------------------------------------------------------

# Map op type string → property-registration key fragment.
# (See wxmeerk40t.py: kernel.register("property/RasterOpNode/OpMain", ...))
_OP_TYPE_TO_PROPERTY_KEY = {
    "op cut":     "property/CutOpNode/OpMain",
    "op engrave": "property/EngraveOpNode/OpMain",
    "op raster":  "property/RasterOpNode/OpMain",
    "op image":   "property/ImageOpNode/OpMain",
    "op dots":    "property/DotsOpNode/OpMain",
}

# Settings-keys we deliberately DO NOT persist into a library MaterialOperation.
# These belong to a placed-node-in-the-tree, not to a recipe.
_OP_PERSIST_DENYLIST = frozenset({
    # Identity (handled as MaterialOperation top-level fields)
    "id", "label", "type", "lock",
    # Visual / per-element attributes — don't belong in a recipe
    "color", "stroke", "fill", "stroke_width", "stroke_scaled",
    "fill_color",
    # Tree / selection state
    "references", "parent", "root",
    "selected", "emphasized", "targeted", "highlighted",
    "expanded", "focus", "hidden", "lock",
    # Per-instance bookkeeping
    "implicit_passes",
})


def _is_yaml_safe(v):
    """Whether a value can be safely round-tripped via PyYAML safe_dump."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, (list, tuple)):
        return all(_is_yaml_safe(x) for x in v)
    if isinstance(v, dict):
        return all(
            isinstance(k, str) and _is_yaml_safe(val)
            for k, val in v.items()
        )
    return False


def _scrape_op_settings(node):
    """Read settings off a (temp) op node into a dict suitable for
    MaterialOperation.settings. Skips private/callable/non-serializable attrs
    and anything in :data:`_OP_PERSIST_DENYLIST`."""
    out = {}
    for attr_name in vars(node):
        if attr_name.startswith("_"):
            continue
        if attr_name in _OP_PERSIST_DENYLIST:
            continue
        value = getattr(node, attr_name, None)
        if callable(value):
            continue
        if not _is_yaml_safe(value):
            continue
        out[attr_name] = value
    return out


def _find_driver_extra_panels(context, node_class_name, driver_key):
    """Discover driver-specific property panels for an op node class.

    Drivers like balor and lihuiyu register extra property panels on
    their own device service during the service's ``added`` lifecycle, e.g.
    ``service.register("property/RasterOpNode/Balor", BalorOperationPanel)``.
    These show up as additional tabs alongside ``OpMain``.

    For the library editor we want those panels to appear based on
    ``library.driver``, regardless of which device is currently active.
    We walk every configured (available) device service and pick the ones
    whose ``registered_path`` matches the driver, then collect their
    matching registrations.

    Returns: list of ``(tab_name, panel_class, device_service)`` in
    deterministic order. ``device_service`` is the configured driver-matching
    service that registered the panel — needed so we can wrap context so
    ``.device`` resolves to *that* service, not whatever's currently active.
    Skips ``OpMain`` (the main panel is looked up via the kernel separately).
    """
    if not driver_key:
        return []
    import re as _re
    pattern = _re.compile(rf"^property/{_re.escape(node_class_name)}/(.+)$")
    found = []
    seen = set()
    kernel = context.kernel
    devices = list(kernel.services("device") or [])
    # If no real configured device matches this driver, ask the matlib
    # service for a transient instance so the driver's tabs still work.
    has_match = any(
        (getattr(d, "registered_path", "") or "").endswith(f"/{driver_key}")
        for d in devices
    )
    if not has_match:
        try:
            transient = kernel.matlib.get_transient_driver(driver_key)
        except Exception:
            transient = None
        if transient is not None:
            devices.append(transient)
    for device in devices:
        regpath = getattr(device, "registered_path", "") or ""
        if not regpath.endswith(f"/{driver_key}"):
            continue
        try:
            reg = device._registered
        except AttributeError:
            continue
        for r, cls in reg.items():
            m = pattern.match(r)
            if not m:
                continue
            tab_name = m.group(1)
            if tab_name == "OpMain":
                continue  # handled at kernel level
            if tab_name in seen:
                continue
            seen.add(tab_name)
            found.append((tab_name, cls, device))
    found.sort(key=lambda p: p[0])
    return found


class _DeviceProxy:
    """Wraps a device service so a hosted property panel sees the matlib
    library's preferred display units instead of whatever the real device
    is configured to show.

    The underlying op values are still PPI / (mm/s); only the panel's
    display/parse logic flips between PPI<->percent and mm/s<->mm/min.
    Attribute writes for fields other than the two display flags fall
    through to the wrapped device.
    """

    def __init__(self, base_device, use_percent, use_mm_min):
        object.__setattr__(self, "_base", base_device)
        object.__setattr__(
            self, "use_percent_for_power_display", bool(use_percent)
        )
        object.__setattr__(
            self, "use_mm_min_for_speed_display", bool(use_mm_min)
        )

    def __getattr__(self, name):
        # Falls through to the wrapped device for everything else.
        return getattr(self._base, name)

    def __setattr__(self, name, value):
        if name in (
            "_base",
            "use_percent_for_power_display",
            "use_mm_min_for_speed_display",
        ):
            object.__setattr__(self, name, value)
        else:
            setattr(self._base, name, value)


class _DriverContextProxy:
    """Thin wrapper that forwards attribute access to a base context except
    for ``.device``, which is pinned to a specific device service.

    Used when hosting a driver-specific property panel (e.g. Balor's) for a
    library whose driver doesn't match the currently active device. Panels
    typically read ``self.context.device.<attr>`` and would otherwise hit
    the wrong device.
    """

    def __init__(self, base, device):
        # Use object.__setattr__ to avoid recursing through __setattr__ below.
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "device", device)

    def __getattr__(self, name):
        return getattr(self._base, name)

    def __setattr__(self, name, value):
        if name in ("_base", "device"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._base, name, value)


class OperationEditorDialog(wx.Dialog):
    """Hosts meerk40t's ParameterPanel against a temporary op node populated
    from a MaterialOperation. On OK, harvests the modified attrs back into a
    fresh settings dict + id/label."""

    def __init__(
        self, parent, context, mat_op,
        driver="", use_percent=False, use_mm_min=False,
    ):
        super().__init__(
            parent,
            title=_("Edit operation: {type}").format(type=mat_op.type),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.context = context
        self._mat_op = mat_op
        self._driver = driver
        self._use_percent = use_percent
        self._use_mm_min = use_mm_min
        self._result = None
        self._temp_node = self._build_temp_node(mat_op)
        self._panels = []  # list of hosted property panels
        self._delegate_owner = None

        outer = wx.BoxSizer(wx.VERTICAL)

        if self._temp_node is None:
            outer.Add(
                wxStaticText(
                    self, wx.ID_ANY,
                    _(
                        "No editor is registered for operation type '{t}'."
                    ).format(t=mat_op.type),
                ),
                0, wx.ALL, 12,
            )
            self._notebook = None
        else:
            # Build the list of (tab_name, panel_class, panel_context) to show.
            node_class_name = type(self._temp_node).__name__
            panels_to_show = []
            main_key = _OP_TYPE_TO_PROPERTY_KEY.get(mat_op.type)
            main_cls = (
                context.kernel.lookup(main_key) if main_key else None
            )
            if main_cls is not None:
                # OpMain reads context.device.use_percent_for_power_display
                # etc. to decide units. Wrap the active device so the panel
                # sees the library's preferred display units instead.
                base_dev = getattr(context, "device", None)
                if base_dev is not None:
                    parameters_context = _DriverContextProxy(
                        context,
                        _DeviceProxy(
                            base_dev, self._use_percent, self._use_mm_min
                        ),
                    )
                else:
                    parameters_context = context
                panels_to_show.append(
                    (_("Parameters"), main_cls, parameters_context)
                )
            for tab_name, panel_cls, driver_service in _find_driver_extra_panels(
                context, node_class_name, self._driver
            ):
                # Driver-specific panels typically read self.context.device;
                # wrap context so .device points to the matching device,
                # and wrap that device so display flags follow the library.
                panel_context = _DriverContextProxy(
                    context,
                    _DeviceProxy(
                        driver_service, self._use_percent, self._use_mm_min
                    ),
                )
                panels_to_show.append((tab_name, panel_cls, panel_context))

            if not panels_to_show:
                outer.Add(
                    wxStaticText(
                        self, wx.ID_ANY,
                        _("No property panel registered for '{t}'.").format(
                            t=mat_op.type
                        ),
                    ),
                    0, wx.ALL, 12,
                )
                self._notebook = None
            else:
                self._notebook = wx.Notebook(self, wx.ID_ANY)
                outer.Add(self._notebook, 1, wx.EXPAND | wx.ALL, 6)
                try:
                    self._delegate_owner = context.kernel.matlib
                except Exception:
                    self._delegate_owner = None
                for tab_name, panel_cls, panel_context in panels_to_show:
                    self._add_panel_tab(tab_name, panel_cls, panel_context)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(
            btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8,
        )
        self.SetSizer(outer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        # Size dialog to the natural content, clamped to the screen.
        self.Layout()
        self.Fit()
        best = self.GetBestSize()
        try:
            display = wx.Display.GetFromWindow(parent)
            if display == wx.NOT_FOUND:
                display = 0
            area = wx.Display(display).GetClientArea()
            max_w = max(400, area[2] - 80)
            max_h = max(400, area[3] - 80)
        except Exception:
            max_w, max_h = 800, 900
        self.SetSize((
            max(480, min(best.width, max_w)),
            max(400, min(best.height, max_h)),
        ))
        self.SetMinSize((480, 400))
        # Defer SetupScrolling until after sizing so the natural panel size
        # drives the Fit() above (otherwise the scrolled panels would
        # report a tiny viewport min-size and shrink the dialog).
        for panel in self._panels:
            if hasattr(panel, "SetupScrolling"):
                try:
                    panel.SetupScrolling(scrollToTop=False)
                except Exception:
                    pass
        self.CentreOnParent()

    def _add_panel_tab(self, tab_name, panel_cls, panel_context=None):
        if panel_context is None:
            panel_context = self.context
        try:
            panel = panel_cls(
                self._notebook, wx.ID_ANY,
                context=panel_context, node=self._temp_node,
            )
        except Exception as exc:
            # Skip a broken panel rather than killing the whole dialog.
            placeholder = wx.Panel(self._notebook)
            sz = wx.BoxSizer(wx.VERTICAL)
            sz.Add(
                wxStaticText(
                    placeholder, wx.ID_ANY,
                    _("Failed to load this panel: {exc}").format(exc=exc),
                ),
                0, wx.ALL, 12,
            )
            placeholder.SetSizer(sz)
            self._notebook.AddPage(placeholder, tab_name)
            return
        self._notebook.AddPage(panel, tab_name)
        self._panels.append(panel)
        if self._delegate_owner is not None:
            try:
                self.context.kernel.add_delegate(panel, self._delegate_owner)
            except Exception:
                pass
        if hasattr(panel, "pane_show"):
            try:
                panel.pane_show()
            except Exception:
                pass
        if hasattr(panel, "set_widgets"):
            try:
                panel.set_widgets(self._temp_node)
            except Exception:
                pass

    def _build_temp_node(self, mat_op):
        """Instantiate a temp op node from the bootstrap registry, populated
        from this MaterialOperation. Detached (no parent in the tree)."""
        try:
            from meerk40t.core.node.bootstrap import bootstrap
        except Exception:
            return None
        cls = bootstrap.get(mat_op.type)
        if cls is None:
            return None
        # Make sure passes_custom is paired with passes>1 before we hand
        # the settings to the node — the property panel reads the flag at
        # set_widgets time, so it must already be present.
        normalize_passes_setting(mat_op.settings)
        # Pass settings via kwargs at construction time. This matches how
        # op_branch.add(type=..., **settings) works on push and ensures
        # the values land in node.settings (and __dict__ for direct
        # attribute access) before any code reads them.
        try:
            node = cls(**mat_op.settings)
        except TypeError:
            # Fall back: instantiate with no args, then setattr each key.
            try:
                node = cls()
            except Exception:
                return None
            for key, value in mat_op.settings.items():
                try:
                    setattr(node, key, value)
                except Exception:
                    pass
        # Identity (id / label aren't typically in settings; set explicitly).
        try:
            node.id = mat_op.id
        except Exception:
            pass
        try:
            node.label = mat_op.label
        except Exception:
            pass
        return node

    def _on_ok(self, event):
        if self._temp_node is None:
            event.Skip()
            return
        try:
            self._result = {
                "id": getattr(self._temp_node, "id", "") or "",
                "label": getattr(self._temp_node, "label", "") or "",
                "settings": _scrape_op_settings(self._temp_node),
            }
        except Exception as exc:
            wx.MessageBox(
                str(exc), _("Invalid value"),
                wx.OK | wx.ICON_ERROR, self,
            )
            return
        event.Skip()

    def get_result(self):
        return self._result

    def Destroy(self):
        # Give every hosted panel a chance to detach signal listeners and
        # unregister it from the kernel delegate list so handlers don't
        # keep firing for stale wx widgets after the dialog is gone.
        for panel in self._panels:
            try:
                if hasattr(panel, "pane_hide"):
                    panel.pane_hide()
            except Exception:
                pass
            if self._delegate_owner is not None:
                try:
                    self.context.kernel.remove_delegate(
                        panel, self._delegate_owner
                    )
                except Exception:
                    pass
        return super().Destroy()


class SearchHelperDialog(wx.Dialog):
    """Form-based search builder. Lets users fill in a Free Text box and
    optional scope fields (Category / Material / Thickness / Op type / ID /
    Label / Power / Speed / Frequency / Passes / Effect) without having to
    remember the ``field:value`` syntax.

    On construction the dialog parses the current search string so the form
    pre-populates with whatever is already filtered — letting the user
    refine a complex query without retyping.
    """

    _OP_TYPE_CHOICES = (
        ("", _("(any)")),
        ("cut", "cut"),
        ("engrave", "engrave"),
        ("raster", "raster"),
        ("image", "image"),
        ("dots", "dots"),
        ("hatch", "hatch"),
    )

    def __init__(self, parent, existing_query=""):
        super().__init__(parent, title=_("Filter Builder"))
        free, fields = parse_search_query(existing_query or "")
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        grid.AddGrowableCol(1, 1)

        def _row(label, ctrl):
            grid.Add(
                wxStaticText(self, wx.ID_ANY, label),
                0, wx.ALIGN_CENTER_VERTICAL,
            )
            grid.Add(ctrl, 1, wx.EXPAND)

        self.text_free = TextCtrl(self, wx.ID_ANY, " ".join(free))
        self.text_free.SetToolTip(
            _("Space-separated tokens — all must match somewhere")
        )
        _row(_("Free text:"), self.text_free)

        self.text_category = TextCtrl(self, wx.ID_ANY, fields.get("category", ""))
        _row(_("Category:"), self.text_category)

        self.text_material = TextCtrl(self, wx.ID_ANY, fields.get("material", ""))
        _row(_("Material:"), self.text_material)

        self.text_thickness = TextCtrl(self, wx.ID_ANY, fields.get("thickness", ""))
        _row(_("Thickness:"), self.text_thickness)

        # Op type — combobox to spare the user remembering names.
        self.combo_optype = wxComboBox(
            self, wx.ID_ANY,
            choices=[label for _, label in self._OP_TYPE_CHOICES],
            style=wx.CB_READONLY,
        )
        current_op = fields.get("op") or fields.get("type") or ""
        sel = 0
        for i, (key, _label) in enumerate(self._OP_TYPE_CHOICES):
            if key == current_op:
                sel = i
                break
        self.combo_optype.SetSelection(sel)
        _row(_("Op type:"), self.combo_optype)

        self.text_id = TextCtrl(self, wx.ID_ANY, fields.get("id", ""))
        _row(_("Op ID:"), self.text_id)

        self.text_label = TextCtrl(self, wx.ID_ANY, fields.get("label", ""))
        _row(_("Op label:"), self.text_label)

        self.text_power = TextCtrl(self, wx.ID_ANY, fields.get("power", ""))
        _row(_("Power:"), self.text_power)

        self.text_speed = TextCtrl(self, wx.ID_ANY, fields.get("speed", ""))
        _row(_("Speed:"), self.text_speed)

        self.text_freq = TextCtrl(
            self, wx.ID_ANY,
            fields.get("freq") or fields.get("frequency") or "",
        )
        _row(_("Frequency:"), self.text_freq)

        self.text_passes = TextCtrl(self, wx.ID_ANY, fields.get("passes", ""))
        _row(_("Passes:"), self.text_passes)

        self.text_effect = TextCtrl(self, wx.ID_ANY, fields.get("effect", ""))
        self.text_effect.SetToolTip(_("Effect type name (e.g. 'hatch')"))
        _row(_("Effect:"), self.text_effect)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(
            btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12
        )
        self.SetSizerAndFit(sizer)

    def get_query(self) -> str:
        """Compose the search-query string from the dialog's fields."""
        parts = []
        free = self.text_free.GetValue().strip()
        if free:
            parts.append(free)

        # Op type combo → short name (or empty for "any")
        sel = self.combo_optype.GetSelection()
        op_value = (
            self._OP_TYPE_CHOICES[sel][0]
            if 0 <= sel < len(self._OP_TYPE_CHOICES)
            else ""
        )

        # Build "field:value" tokens; skip empty fields.
        for field, ctrl in (
            ("category", self.text_category),
            ("material", self.text_material),
            ("thickness", self.text_thickness),
            ("id", self.text_id),
            ("label", self.text_label),
            ("power", self.text_power),
            ("speed", self.text_speed),
            ("freq", self.text_freq),
            ("passes", self.text_passes),
            ("effect", self.text_effect),
        ):
            value = ctrl.GetValue().strip()
            if not value:
                continue
            # Values with spaces would break the simple tokenizer; collapse
            # whitespace to single underscores so the user gets *something*
            # workable. They can always edit the search box directly for
            # multi-word values.
            value = "_".join(value.split())
            parts.append(f"{field}:{value}")
        if op_value:
            parts.append(f"op:{op_value}")
        return " ".join(parts)


class MaterialLibraryWindow(MWindow):
    """Top-level frame hosting the MaterialLibraryPanel."""

    def __init__(self, *args, **kwds):
        super().__init__(900, 640, *args, **kwds)
        self.panel = MaterialLibraryPanel(self, wx.ID_ANY, context=self.context)
        self.panel.set_parent(self)
        _icon = wx.NullIcon
        _icon.CopyFromBitmap(icon_library.GetBitmap())
        self.SetIcon(_icon)
        self.sizer.Add(self.panel, 1, wx.EXPAND, 0)
        self.SetTitle(_("Material Library (new)"))
        self.restore_aspect(honor_initial_values=True)

    def delegates(self):
        yield self.panel

    def window_open(self):
        self.panel.refresh_libraries()

    def window_close(self):
        pass

    @staticmethod
    def sub_register(kernel):
        kernel.register(
            "button/config/MaterialLibrary",
            {
                "label": _("Material Library (new)"),
                "icon": icon_library,
                "tip": _("Browse material libraries (work in progress)"),
                "action": lambda v: kernel.console(
                    "window toggle MaterialLibrary\n"
                ),
            },
        )

    @staticmethod
    def submenu():
        return "", "Material Library (new)", True

    @staticmethod
    def helptext():
        return _("Browse material libraries (new UI, work in progress)")
