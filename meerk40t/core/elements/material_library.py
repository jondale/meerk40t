"""
Material Library — a tree of laser settings organized as:

    Library
      └── Category (nestable)
          ├── Category ...
          └── Material
              ├── Thickness (optional)
              │   └── Operation presets
              └── Operation presets (if no thicknesses)

Every material must live in a category. When the UI is asked to create
a material with no obvious category context, an ``Uncategorized``
category is created on demand.

Each library is persisted to its own YAML file under
``<safe_data_dir>/libraries/<name>.meerlib``. The directory is auto-created
on first use. Files are human-editable and version-control friendly.

This module is intentionally GUI-free: it owns the data model, persistence,
and a set of console commands. The GUI consumes the service exposed here
("matlib") and never touches files directly.
"""

import os
import re
from typing import List, Optional

from meerk40t.kernel import CommandSyntaxError, Service
from meerk40t.kernel.functions import get_safe_path

try:
    import yaml
except ImportError:  # pragma: no cover - hard dep, but degrade gracefully
    yaml = None


MEERLIB_EXTENSION = ".meerlib"
LIBRARIES_SUBDIR = "libraries"
UNCATEGORIZED_NAME = "Uncategorized"

# Tree-item kind tags, shared by UI and the move/can-move logic below.
KIND_CATEGORY = "category"
KIND_MATERIAL = "material"
KIND_THICKNESS = "thickness"

# Operation type strings preserved from the existing operation system.
VALID_OP_TYPES = (
    "op cut",
    "op engrave",
    "op raster",
    "op image",
    "op dots",
    "op hatch",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class MaterialEffect:
    """An effect attached to an operation.

    ``type`` matches the meerk40t effect node type string (e.g. "effect
    hatch", "effect wobble", "effect warp"). ``settings`` is an
    effect-type-specific dict; values are stored as strings or numbers
    exactly as meerk40t stores them on the node (e.g. ``"1mm"``,
    ``"45deg"``) and parsed at apply-time.
    """

    __slots__ = ("type", "settings")

    def __init__(
        self,
        type: str = "",
        settings: Optional[dict] = None,
    ):
        self.type = type
        self.settings = dict(settings) if settings else {}

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "settings": dict(self.settings),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialEffect":
        return cls(
            type=d.get("type", ""),
            settings=d.get("settings", {}) or {},
        )


class MaterialOperation:
    """A single operation preset (cut/engrave/raster/etc)."""

    __slots__ = ("type", "id", "label", "settings", "effects")

    def __init__(
        self,
        type: str = "op cut",
        id: str = "",
        label: str = "",
        settings: Optional[dict] = None,
        effects: Optional[List["MaterialEffect"]] = None,
    ):
        self.type = type
        self.id = id
        self.label = label
        self.settings = dict(settings) if settings else {}
        self.effects: List[MaterialEffect] = (
            list(effects) if effects else []
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "label": self.label,
            "settings": dict(self.settings),
            "effects": [e.to_dict() for e in self.effects],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialOperation":
        return cls(
            type=d.get("type", "op cut"),
            id=d.get("id", ""),
            label=d.get("label", ""),
            settings=d.get("settings", {}) or {},
            effects=[MaterialEffect.from_dict(e) for e in d.get("effects", [])],
        )


class ThicknessEntry:
    """A specific thickness variant of a material."""

    __slots__ = ("value", "notes", "operations")

    def __init__(
        self,
        value: str = "",
        notes: str = "",
        operations: Optional[List[MaterialOperation]] = None,
    ):
        self.value = value
        self.notes = notes
        self.operations: List[MaterialOperation] = list(operations) if operations else []

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "notes": self.notes,
            "operations": [op.to_dict() for op in self.operations],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ThicknessEntry":
        return cls(
            value=d.get("value", ""),
            notes=d.get("notes", ""),
            operations=[MaterialOperation.from_dict(o) for o in d.get("operations", [])],
        )


class MaterialEntry:
    """A material. May own thicknesses, or operations directly when it has none."""

    __slots__ = ("name", "notes", "color", "thicknesses", "operations")

    def __init__(
        self,
        name: str = "",
        notes: str = "",
        color: str = "",
        thicknesses: Optional[List[ThicknessEntry]] = None,
        operations: Optional[List[MaterialOperation]] = None,
    ):
        self.name = name
        self.notes = notes
        self.color = color
        self.thicknesses: List[ThicknessEntry] = (
            list(thicknesses) if thicknesses else []
        )
        self.operations: List[MaterialOperation] = (
            list(operations) if operations else []
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "notes": self.notes,
            "color": self.color,
            "thicknesses": [t.to_dict() for t in self.thicknesses],
            "operations": [op.to_dict() for op in self.operations],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialEntry":
        return cls(
            name=d.get("name", ""),
            notes=d.get("notes", ""),
            color=d.get("color", ""),
            thicknesses=[
                ThicknessEntry.from_dict(t) for t in d.get("thicknesses", [])
            ],
            operations=[MaterialOperation.from_dict(o) for o in d.get("operations", [])],
        )


class Category:
    """A folder in the tree. Nestable, holds materials and sub-categories."""

    __slots__ = ("name", "notes", "color", "categories", "materials")

    def __init__(
        self,
        name: str = "",
        notes: str = "",
        color: str = "",
        categories: Optional[List["Category"]] = None,
        materials: Optional[List[MaterialEntry]] = None,
    ):
        self.name = name
        self.notes = notes
        self.color = color
        self.categories: List[Category] = list(categories) if categories else []
        self.materials: List[MaterialEntry] = list(materials) if materials else []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "notes": self.notes,
            "color": self.color,
            "categories": [c.to_dict() for c in self.categories],
            "materials": [m.to_dict() for m in self.materials],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Category":
        return cls(
            name=d.get("name", ""),
            notes=d.get("notes", ""),
            color=d.get("color", ""),
            categories=[Category.from_dict(c) for c in d.get("categories", [])],
            materials=[MaterialEntry.from_dict(m) for m in d.get("materials", [])],
        )


class Library:
    """A whole library — corresponds to one .meerlib file.

    All materials live inside categories; libraries never hold loose materials.
    Legacy files that did so are migrated on load: loose materials are moved
    into an ``Uncategorized`` category (created if missing).

    The metadata fields (``motion`` / ``source`` / ``wattage`` / ``lens`` /
    ``power_unit`` / ``speed_unit``) describe the physical setup this
    library was tuned for. They are descriptive only; the data layer does
    no unit conversion based on them.
    """

    # Bump when the on-disk schema changes incompatibly.
    SCHEMA_VERSION = 1

    __slots__ = (
        "name",
        "description",
        "driver",
        "motion",
        "source",
        "wattage",
        "lens",
        "power_unit",
        "speed_unit",
        "categories",
        "filepath",
    )

    def __init__(
        self,
        name: str = "",
        description: str = "",
        driver: str = "",
        motion: str = "",
        source: str = "",
        wattage: float = 0.0,
        lens: str = "",
        power_unit: str = "percent",
        speed_unit: str = "mm/s",
        categories: Optional[List[Category]] = None,
        filepath: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        # Provider key (e.g. "lhystudios", "grbl", "balor"). Used to surface
        # driver-specific property panels when editing operations.
        self.driver = driver
        self.motion = motion
        self.source = source
        self.wattage = float(wattage) if wattage else 0.0
        self.lens = lens
        self.power_unit = power_unit
        self.speed_unit = speed_unit
        self.categories: List[Category] = list(categories) if categories else []
        self.filepath = filepath

    def to_dict(self) -> dict:
        return {
            "schema": self.SCHEMA_VERSION,
            "name": self.name,
            "description": self.description,
            "driver": self.driver,
            "motion": self.motion,
            "source": self.source,
            "wattage": self.wattage,
            "lens": self.lens,
            "power_unit": self.power_unit,
            "speed_unit": self.speed_unit,
            "categories": [c.to_dict() for c in self.categories],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Library":
        categories = [Category.from_dict(c) for c in d.get("categories", [])]
        legacy_loose = [
            MaterialEntry.from_dict(m) for m in d.get("materials", [])
        ]
        if legacy_loose:
            target = _find_or_make_category(categories, UNCATEGORIZED_NAME)
            target.materials.extend(legacy_loose)
        # Legacy: an earlier prototype stored the same value under
        # ``device_hint``; honor it if ``driver`` is missing.
        driver = d.get("driver")
        if not driver:
            driver = d.get("device_hint", "")
        # Note: any legacy show_frequency / show_pulse_width keys are
        # ignored — column visibility is now derived from ``driver``.
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            driver=driver,
            motion=d.get("motion", ""),
            source=d.get("source", ""),
            wattage=d.get("wattage", 0.0),
            lens=d.get("lens", ""),
            power_unit=d.get("power_unit", "percent"),
            speed_unit=d.get("speed_unit", "mm/s"),
            categories=categories,
        )


def _find_or_make_category(category_list: List[Category], name: str) -> Category:
    for c in category_list:
        if c.name == name:
            return c
    cat = Category(name=name)
    category_list.append(cat)
    return cat


def find_or_create_uncategorized(library: "Library") -> Category:
    """Return the ``Uncategorized`` category in ``library``, creating it
    (and appending to ``library.categories``) if it doesn't exist."""
    return _find_or_make_category(library.categories, UNCATEGORIZED_NAME)


# ---------------------------------------------------------------------------
# Tree helpers — used by both UI and tests
# ---------------------------------------------------------------------------


def clone_node(item):
    """Deep-clone any tree node (Category, MaterialEntry, ThicknessEntry,
    MaterialOperation, MaterialEffect) via dict round-trip."""
    if isinstance(item, Category):
        return Category.from_dict(item.to_dict())
    if isinstance(item, MaterialEntry):
        return MaterialEntry.from_dict(item.to_dict())
    if isinstance(item, ThicknessEntry):
        return ThicknessEntry.from_dict(item.to_dict())
    if isinstance(item, MaterialOperation):
        return MaterialOperation.from_dict(item.to_dict())
    if isinstance(item, MaterialEffect):
        return MaterialEffect.from_dict(item.to_dict())
    raise TypeError(f"Cannot clone node of type {type(item).__name__}")


def find_parent(library: "Library", item):
    """Return the container holding ``item`` (Library or Category or
    MaterialEntry), or None if it isn't in the library."""
    if item in library.categories:
        return library
    for cat in library.categories:
        found = _find_parent_in_category(cat, item)
        if found is not None:
            return found
    return None


def _find_parent_in_category(cat: "Category", item):
    if item in cat.categories or item in cat.materials:
        return cat
    for sub in cat.categories:
        found = _find_parent_in_category(sub, item)
        if found is not None:
            return found
    for mat in cat.materials:
        if item in mat.thicknesses:
            return mat
    return None


# ---------------------------------------------------------------------------
# Effect-type discovery and schemas
# ---------------------------------------------------------------------------


# Curated per-effect-type schemas. Each entry is a list of field descriptors:
#   {"key": <settings-dict key>, "label": <ui label>, "type": <"length" |
#    "angle" | "int" | "float" | "bool" | "choice" | "string">,
#    "default": <default value>, "choices": [...] (only for choice)}
# Field "type" maps to a UI widget in the matlib panel and to a parser at
# apply-time. Stored values are strings or numbers exactly as meerk40t stores
# them on its effect nodes.
EFFECT_SCHEMAS = {
    "effect hatch": [
        {"key": "hatch_distance", "label": "Hatch distance",
         "type": "length", "default": "1mm"},
        {"key": "hatch_angle", "label": "Hatch angle",
         "type": "angle", "default": "0deg"},
        {"key": "hatch_angle_delta", "label": "Angle delta per pass",
         "type": "angle", "default": "0deg"},
        {"key": "hatch_type", "label": "Hatch type",
         "type": "choice", "default": "scanline",
         "choices": ["scanline", "spiral"]},
        {"key": "hatch_algorithm", "label": "Algorithm",
         "type": "choice", "default": "auto",
         "choices": ["auto", "scanbeam", "direct_grid"]},
        {"key": "loops", "label": "Loops (passes)",
         "type": "int", "default": 1},
        {"key": "unidirectional", "label": "Unidirectional",
         "type": "bool", "default": False},
        {"key": "include_outlines", "label": "Include outlines",
         "type": "bool", "default": False},
    ],
    "effect wobble": [
        {"key": "wobble_radius", "label": "Wobble radius",
         "type": "length", "default": "1.5mm"},
        {"key": "wobble_interval", "label": "Interval",
         "type": "length", "default": "0.1mm"},
        {"key": "wobble_speed", "label": "Speed",
         "type": "float", "default": 50.0},
        {"key": "wobble_type", "label": "Wobble pattern",
         "type": "choice", "default": "circle",
         "choices": ["circle", "circle_right", "circle_left", "sinewave",
                     "sawtooth", "jigsaw", "gear", "slowtooth",
                     "meander_1", "meander_2", "meander_3", "dash", "tabs"]},
    ],
    # "effect warp" — uses 4 corner-point complex coordinates with 4
    # displacement vectors; defer the structured editor for v1.
}


def discover_effect_types() -> List[str]:
    """Return effect type strings we can offer in the library UI.

    Filters meerk40t's node bootstrap to ``"effect ..."`` entries that
    *also* have an entry in :data:`EFFECT_SCHEMAS` — i.e., effects we know
    how to edit. New effect types automatically surface once a schema is
    added; effects without a schema (currently 'effect warp') are hidden.
    """
    try:
        from meerk40t.core.node.bootstrap import bootstrap as _bootstrap
    except Exception:
        return []
    return sorted(
        t for t in _bootstrap
        if t.startswith("effect ") and t in EFFECT_SCHEMAS
    )


def get_effect_schema(effect_type: str) -> List[dict]:
    """Return field descriptors for an effect type.

    Curated entries are returned verbatim. Unknown types get a minimal
    generic schema (a single free-text "settings" field per existing key)
    so the editor degrades gracefully for plugin-supplied effects.
    """
    if effect_type in EFFECT_SCHEMAS:
        # Return shallow copies so callers can't mutate the canonical schema.
        return [dict(f) for f in EFFECT_SCHEMAS[effect_type]]
    return []


def short_effect_name(effect_type: str) -> str:
    """Strip the 'effect ' prefix for compact display in cells/menus."""
    if effect_type.startswith("effect "):
        return effect_type[len("effect "):]
    return effect_type


def parse_search_query(raw: str):
    """Parse a search query like ``"black material:steel"`` into:
      - ``free`` — list of lowercase substring tokens to match anywhere
      - ``fields`` — dict of scope/field filters, lowercased
        (keys: category, material, thickness, op|type, id, label,
        power, speed, freq|frequency, effect, passes)

    Empty / whitespace-only input → ``([], {})``. Tokens of the form
    ``field:value`` are treated as field filters (later occurrences of
    the same field overwrite earlier ones). Other tokens are free-text.
    """
    free, fields = [], {}
    if not raw:
        return free, fields
    for tok in raw.strip().lower().split():
        if ":" in tok:
            name, _, value = tok.partition(":")
            name = name.strip()
            value = value.strip()
            if name and value:
                fields[name] = value
                continue
        free.append(tok)
    return free, fields


def match_op_against_query(op, cat_path, mat_name, thk_value, free, fields):
    """Decide whether a single MaterialOperation, in context of its
    category path / material / thickness, matches the search query.
    Pure data-layer; testable without wx."""
    op_type = (op.type or "").lower()
    op_id = (op.id or "").lower()
    op_label = (op.label or "").lower()
    settings = op.settings or {}

    def _setting_str(key):
        v = settings.get(key)
        return "" if v is None else str(v).lower()

    # Op-specific field filters
    for fname, val in fields.items():
        if fname in ("op", "type"):
            if val not in op_type:
                return False
        elif fname == "id":
            if val not in op_id:
                return False
        elif fname == "label":
            if val not in op_label:
                return False
        elif fname == "power":
            if val not in _setting_str("power"):
                return False
        elif fname == "speed":
            if val not in _setting_str("speed"):
                return False
        elif fname in ("freq", "frequency"):
            if val not in _setting_str("frequency"):
                return False
        elif fname == "passes":
            if val not in _setting_str("passes"):
                return False
        elif fname == "effect":
            if not any(val in (e.type or "").lower() for e in op.effects):
                return False
        # category/material/thickness are path-scope and checked by caller

    if free:
        haystack_parts = [
            cat_path,
            mat_name,
            thk_value,
            op_type,
            op_id,
            op_label,
            _setting_str("power"),
            _setting_str("speed"),
            _setting_str("frequency"),
            _setting_str("passes"),
            _setting_str("pulse_width"),
            " ".join((e.type or "").lower() for e in op.effects),
        ]
        haystack = " ".join(haystack_parts)
        for t in free:
            if t not in haystack:
                return False
    return True


def normalize_passes_setting(settings: dict) -> None:
    """Ensure ``passes_custom`` mirrors ``passes`` correctly: True when
    passes > 1, removed when passes <= 1. MeerK40t op nodes only honor
    ``passes`` if ``passes_custom`` is also True, so anywhere we set or
    edit ``passes`` we need this invariant to hold.
    """
    if settings is None:
        return
    raw = settings.get("passes")
    if raw is None:
        return
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return
    if n > 1:
        settings["passes_custom"] = True
    else:
        settings.pop("passes_custom", None)


def make_unique_name(base: str, existing) -> str:
    """Return ``base``, or ``base (2)``, ``base (3)``... to avoid a collision
    with any of ``existing`` (an iterable of strings)."""
    existing = set(existing)
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def is_descendant_of(node, possible_ancestor) -> bool:
    """Return True if ``node`` is ``possible_ancestor`` itself or appears
    anywhere within its subtree. Used to prevent cycles when moving."""
    if node is possible_ancestor:
        return True
    if isinstance(possible_ancestor, Category):
        for sub in possible_ancestor.categories:
            if is_descendant_of(node, sub):
                return True
        for mat in possible_ancestor.materials:
            if node is mat:
                return True
            for thk in mat.thicknesses:
                if node is thk:
                    return True
    elif isinstance(possible_ancestor, MaterialEntry):
        for thk in possible_ancestor.thicknesses:
            if node is thk:
                return True
    return False


def wrap_for_export(item, library_name: str = "") -> "Library":
    """Wrap a single Category or MaterialEntry in a Library suitable for
    export to a .meerlib file. Thicknesses cannot be exported on their own."""
    if isinstance(item, Category):
        clone = clone_node(item)
        return Library(name=library_name or item.name, categories=[clone])
    if isinstance(item, MaterialEntry):
        clone = clone_node(item)
        wrap_cat = Category(name=UNCATEGORIZED_NAME, materials=[clone])
        return Library(name=library_name or item.name, categories=[wrap_cat])
    raise TypeError(
        f"Cannot wrap {type(item).__name__} for export"
    )


def can_move_node(
    library: "Library", src_kind: str, src_obj, dst_kind, dst_obj
) -> bool:
    """Validate a proposed drag-and-drop move within a library.

    ``dst_kind`` may be ``None`` to mean "library root" — only valid for
    moving a Category there.
    """
    if src_obj is dst_obj:
        return False
    # Cycle prevention: a Category cannot be moved into its own subtree.
    if src_kind == KIND_CATEGORY and dst_obj is not None:
        if is_descendant_of(dst_obj, src_obj):
            return False
    if src_kind == KIND_CATEGORY:
        return dst_kind in (KIND_CATEGORY, None)
    if src_kind == KIND_MATERIAL:
        return dst_kind in (KIND_CATEGORY, KIND_MATERIAL)
    if src_kind == KIND_THICKNESS:
        return dst_kind in (KIND_MATERIAL, KIND_THICKNESS)
    return False


def move_node(
    library: "Library", src_kind: str, src_obj, dst_kind, dst_obj
) -> bool:
    """Perform a drag-and-drop move. Returns True on success.

    Semantics:
      - Category dropped on Category → becomes a sub-category (appended).
      - Category dropped on library root → top-level category (appended).
      - Material dropped on Category → moved into that category (appended).
      - Material dropped on Material → inserted as next sibling.
      - Thickness dropped on Material → appended to that material.
      - Thickness dropped on Thickness → inserted as next sibling.

    Names are auto-disambiguated against new siblings.
    """
    if not can_move_node(library, src_kind, src_obj, dst_kind, dst_obj):
        return False
    src_parent = find_parent(library, src_obj)
    if src_parent is None:
        return False
    # Remove from old parent.
    if src_kind == KIND_CATEGORY:
        src_parent.categories.remove(src_obj)
    elif src_kind == KIND_MATERIAL:
        src_parent.materials.remove(src_obj)
    elif src_kind == KIND_THICKNESS:
        src_parent.thicknesses.remove(src_obj)

    # Insert at new location.
    if src_kind == KIND_CATEGORY:
        if dst_kind == KIND_CATEGORY:
            dst_obj.categories.append(src_obj)
            src_obj.name = make_unique_name(
                src_obj.name,
                [c.name for c in dst_obj.categories if c is not src_obj],
            )
        else:  # dst_kind is None → library root
            library.categories.append(src_obj)
            src_obj.name = make_unique_name(
                src_obj.name,
                [c.name for c in library.categories if c is not src_obj],
            )
    elif src_kind == KIND_MATERIAL:
        if dst_kind == KIND_CATEGORY:
            dst_obj.materials.append(src_obj)
            src_obj.name = make_unique_name(
                src_obj.name,
                [m.name for m in dst_obj.materials if m is not src_obj],
            )
        else:  # dst_kind == KIND_MATERIAL → sibling
            dst_parent = find_parent(library, dst_obj)
            idx = dst_parent.materials.index(dst_obj)
            dst_parent.materials.insert(idx + 1, src_obj)
            src_obj.name = make_unique_name(
                src_obj.name,
                [m.name for m in dst_parent.materials if m is not src_obj],
            )
    elif src_kind == KIND_THICKNESS:
        if dst_kind == KIND_MATERIAL:
            dst_obj.thicknesses.append(src_obj)
            src_obj.value = make_unique_name(
                src_obj.value,
                [t.value for t in dst_obj.thicknesses if t is not src_obj],
            )
        else:  # dst_kind == KIND_THICKNESS → sibling
            dst_parent = find_parent(library, dst_obj)
            idx = dst_parent.thicknesses.index(dst_obj)
            dst_parent.thicknesses.insert(idx + 1, src_obj)
            src_obj.value = make_unique_name(
                src_obj.value,
                [t.value for t in dst_parent.thicknesses if t is not src_obj],
            )
    return True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\- ]+")


def sanitize_library_filename(name: str) -> str:
    """Return a filesystem-safe base name (no extension) for a library name."""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip()
    cleaned = cleaned.strip(".")  # no leading/trailing dots
    return cleaned or "library"


def library_to_yaml(lib: Library) -> str:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read or write .meerlib files. "
            "Install with: pip install PyYAML"
        )
    return yaml.safe_dump(
        lib.to_dict(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def library_from_yaml(text: str, filepath: Optional[str] = None) -> Library:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read or write .meerlib files. "
            "Install with: pip install PyYAML"
        )
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Library file root must be a mapping/object")
    lib = Library.from_dict(data)
    lib.filepath = filepath
    return lib


def save_library_to_file(lib: Library, filepath: str) -> None:
    """Write library to ``filepath``. Does not mutate ``lib.filepath``."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    text = library_to_yaml(lib)
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, filepath)


def load_library_from_file(filepath: str) -> Library:
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    return library_from_yaml(text, filepath=filepath)


# ---------------------------------------------------------------------------
# Format-detecting import dispatch
# ---------------------------------------------------------------------------


def parse_library_file(filepath: str) -> Library:
    """Detect file format from extension and parse it into a Library.

    Supported:
      - ``.meerlib`` — native YAML
      - ``.clb``     — LightBurn library (XML)
      - ``.lib`` / ``.ini`` — EzCad library (INI-style)
      - ``.cfg``     — legacy MeerK40t operations.cfg

    Falls back to trying parsers in order if the extension is unknown.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == MEERLIB_EXTENSION:
        return load_library_from_file(filepath)
    if ext == ".clb":
        return parse_lightburn_library(filepath)
    if ext in (".lib", ".ini"):
        return parse_ezcad_library(filepath)
    if ext == ".cfg":
        return parse_legacy_operations_cfg(filepath)
    # Unknown extension — try each parser in order and use the first that
    # produces a non-empty library.
    for fn in (
        load_library_from_file,
        parse_lightburn_library,
        parse_ezcad_library,
        parse_legacy_operations_cfg,
    ):
        try:
            lib = fn(filepath)
            if lib.categories:
                return lib
        except Exception:
            continue
    raise ValueError(
        f"Could not determine library format for {filepath}"
    )


# ---------------------------------------------------------------------------
# LightBurn .clb parser
# ---------------------------------------------------------------------------

# LightBurn CutSetting "type" attribute → our op type string.
_LIGHTBURN_OP_TYPE = {
    "cut":   "op engrave",   # LightBurn "Cut" = vector engrave in MK
    "scan":  "op raster",
    "image": "op image",
}


def parse_lightburn_library(filepath: str) -> Library:
    """Parse a LightBurn .clb library into a Library.

    LightBurn libraries appear in two shapes:

    1. **Conventional**: each ``<Material name="Plywood">`` is a real
       material; its ``<Entry Thickness="3">`` elements are thickness
       variants; ``<CutSetting>``s are ops.

    2. **Grouped** (Thunder Laser presets, etc.): a single
       ``<Material name="100w">`` acts as a group label; each ``<Entry>``
       has ``Thickness="-1"`` and ``NoThickTitle="Acrylic"`` carries the
       real material name. ``Desc`` is the operation/preset label.

    We handle both with a single rule: for each Entry, the *real* material
    name is ``NoThickTitle`` when Thickness < 0 and the attribute is set,
    otherwise the surrounding ``<Material>`` name. Entries sharing a
    derived material name merge into one MaterialEntry.

    Mappings:
      - Library: name from root ``DisplayName`` attribute when present,
        else file basename. ``power_unit="percent"`` (LightBurn edits in %).
      - One top-level Category, named like the library.
      - ``maxPower`` (0-100) × 10 → MK PPI.
      - ``frequency`` ÷ 1000 → kHz.
      - ``numPasses`` → ``passes``.
      - ``jumpSpeed`` → ``rapid_speed`` + ``rapid_enabled=True``.
    """
    import xml.etree.ElementTree as ET

    tree = ET.parse(filepath)
    root = tree.getroot()
    if root.tag.lower() != "lightburnlibrary":
        raise ValueError(
            f"Not a LightBurn library (root tag was {root.tag})"
        )

    file_base = os.path.splitext(os.path.basename(filepath))[0]
    library_name = root.attrib.get("DisplayName") or file_base
    category = Category(name=library_name)

    # Find-or-create the MaterialEntry under our single category.
    def get_material(name: str) -> MaterialEntry:
        for m in category.materials:
            if m.name == name:
                return m
        m = MaterialEntry(name=name)
        category.materials.append(m)
        return m

    for material_node in root:
        if material_node.tag.lower() != "material":
            continue
        xml_mat_name = material_node.attrib.get("name", "Material")

        for entry_node in material_node:
            if entry_node.tag.lower() != "entry":
                continue
            thickness_raw = entry_node.attrib.get("Thickness", "")
            try:
                thk_val = float(thickness_raw)
            except (TypeError, ValueError):
                thk_val = -1
            desc = entry_node.attrib.get("Desc", "")
            no_thick_title = entry_node.attrib.get("NoThickTitle", "")

            # Derive the real material name and thickness.
            if thk_val < 0 and no_thick_title:
                mat_name = no_thick_title
                thickness_label = ""
            else:
                mat_name = xml_mat_name
                thickness_label = _format_lightburn_thickness(
                    thickness_raw, thk_val
                )

            material = get_material(mat_name)

            # Convert this entry's CutSettings into MaterialOperations.
            ops = []
            for cs_node in entry_node:
                if cs_node.tag.lower() != "cutsetting":
                    continue
                cs_type = cs_node.attrib.get("type", "Scan").lower()
                op_type = _LIGHTBURN_OP_TYPE.get(cs_type, "op engrave")
                op = _lightburn_cutsetting_to_op(cs_node, op_type, desc)
                ops.append(op)

            # Attach ops to the right home. When this entry has a real
            # thickness, append to the matching ThicknessEntry (creating
            # it if needed). Otherwise append loose to the material — or
            # fold into the last thickness if any have already been created
            # (avoids confusion: loose ops are easy to miss when a material
            # also has thicknesses).
            if thickness_label:
                existing_thk = next(
                    (t for t in material.thicknesses
                     if t.value == thickness_label),
                    None,
                )
                if existing_thk is None:
                    material.thicknesses.append(
                        ThicknessEntry(value=thickness_label, operations=ops)
                    )
                else:
                    existing_thk.operations.extend(ops)
            else:
                if material.thicknesses:
                    material.thicknesses[-1].operations.extend(ops)
                else:
                    material.operations.extend(ops)

    # Auto-assign IDs across each material/thickness so they're unique
    # per home (C1/C2/R1/...). Easier to do as a sweep at the end than
    # inline because of the find-or-create merge above.
    for material in category.materials:
        if material.operations:
            _autoassign_op_ids(material.operations)
        for thk in material.thicknesses:
            _autoassign_op_ids(thk.operations)

    return Library(
        name=library_name,
        description=(
            f"Imported from LightBurn library {os.path.basename(filepath)}"
        ),
        power_unit="percent",  # LightBurn always edits in percent
        speed_unit="mm/s",
        categories=[category],
    )


def _format_lightburn_thickness(raw: str, value: float) -> str:
    """Turn a LightBurn thickness attribute into a display label like '3mm'.
    Returns '' for invalid or "no thickness" values (Thickness < 0)."""
    if value < 0 or not raw:
        return ""
    # If the raw text already has units, keep it as-is.
    if not raw.replace(".", "", 1).replace("-", "", 1).isdigit():
        return raw
    # Strip trailing zeros: "3.0000" → "3", "1.5000" → "1.5".
    formatted = f"{value:g}"
    return f"{formatted}mm"


def _autoassign_op_ids(ops):
    """Assign C1/C2, E1/E2, R1/R2... IDs to any op missing one."""
    counters = {}
    used = {op.id for op in ops if op.id}
    for op in ops:
        if op.id:
            continue
        prefix = op.type[3].upper() if len(op.type) > 3 else "O"
        n = counters.get(prefix, 0)
        while True:
            n += 1
            candidate = f"{prefix}{n}"
            if candidate not in used:
                break
        op.id = candidate
        used.add(candidate)
        counters[prefix] = n


def _lightburn_cutsetting_to_op(cs_node, op_type, label) -> "MaterialOperation":
    op = MaterialOperation(type=op_type, label=label)
    for p in cs_node:
        tag = p.tag.lower()
        value = p.attrib.get("Value", "")
        if not value:
            continue
        try:
            v = float(value)
        except ValueError:
            continue
        if tag == "maxpower":
            op.settings["power"] = v * 10.0  # LB% → MK PPI (0-1000)
        elif tag == "speed":
            op.settings["speed"] = v
        elif tag == "numpasses":
            if v != 0:
                op.settings["passes"] = int(v)
                normalize_passes_setting(op.settings)
        elif tag == "frequency":
            op.settings["frequency"] = v / 1000.0  # Hz → kHz
        elif tag == "jumpspeed":
            if v != 0:
                op.settings["rapid_speed"] = v
                op.settings["rapid_enabled"] = True
    return op


# ---------------------------------------------------------------------------
# EzCad .lib / .ini parser
# ---------------------------------------------------------------------------


def parse_ezcad_library(filepath: str) -> Library:
    """Parse an EzCad .lib or .ini library into a Library.

    EzCad files are INI-flavored: each ``[Section]`` is one material entry;
    keys like ``markspeed``, ``powerratio``, ``freq``, ``loop``, ``jumpspeed``,
    ``qpulsewidth`` carry the settings. We map one section → one MaterialEntry
    with a single MaterialOperation (op engrave by default, since EzCad is
    fiber-only).

    Conversions:
      - ``powerratio`` (0-100) × 10 → MK PPI
      - ``markspeed`` → speed
      - ``freq`` ÷ 1000 → kHz frequency
      - ``loop`` → passes
      - ``qpulsewidth`` → pulse_width (with pulse_width_enabled=True)
      - ``jumpspeed`` → rapid_speed (with rapid_enabled=True)
      - ``starttc`` / ``laserofftc`` / ``polytc`` → delay_laser_on/off/polygon
    """
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    category = Category(name=base_name)

    current = None  # (MaterialEntry, MaterialOperation) being built
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(";") or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                # New section → new material entry.
                name = line[1:-1].strip()
                if name.startswith("F "):  # legacy "Fibre" prefix
                    name = name[2:]
                op = MaterialOperation(
                    type="op engrave", id="F1", label=name
                )
                material = MaterialEntry(name=name, operations=[op])
                category.materials.append(material)
                current = (material, op)
                continue
            if current is None:
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip()
            try:
                v = float(value)
            except ValueError:
                continue
            _, op = current
            if key == "markspeed":
                if v != 0:
                    op.settings["speed"] = v
            elif key == "powerratio":
                if v != 0:
                    op.settings["power"] = v * 10.0
            elif key == "freq":
                if v != 0:
                    op.settings["frequency"] = v / 1000.0
            elif key == "loop":
                if v != 0:
                    op.settings["passes"] = int(v)
                    normalize_passes_setting(op.settings)
            elif key == "qpulsewidth":
                if v != 0:
                    op.settings["pulse_width"] = v
                    op.settings["pulse_width_enabled"] = True
            elif key == "jumpspeed":
                if v != 0:
                    op.settings["rapid_speed"] = v
                    op.settings["rapid_enabled"] = True
            elif key == "starttc":
                if v != 0:
                    op.settings["delay_laser_on"] = v
                    op.settings["timing_enabled"] = True
            elif key == "laserofftc":
                if v != 0:
                    op.settings["delay_laser_off"] = v
                    op.settings["timing_enabled"] = True
            elif key == "polytc":
                if v != 0:
                    op.settings["delay_polygon"] = v
                    op.settings["timing_enabled"] = True

    return Library(
        name=base_name,
        description=f"Imported from EzCad library {os.path.basename(filepath)}",
        driver="balor",     # EzCad is for galvo fiber lasers
        motion="galvo",
        source="fiber",
        power_unit="percent",
        speed_unit="mm/s",
        categories=[category],
    )


# ---------------------------------------------------------------------------
# Legacy operations.cfg parser
# ---------------------------------------------------------------------------

_LASER_TYPE_LABELS = {
    0: "All Lasertypes",
    1: "CO2-Laser (K40)",
    2: "GRBL-Diode-Laser",
    3: "Fibre-Laser",
    4: "Older CO2-Laser (Moshi)",
    5: "Older CO2-Laser (NewlyDraw)",
    6: "CO2-Laser (DSP-Ruida)",
}

_OP_INFO_DENYLIST = frozenset({
    "type", "id", "label",
})


_LASER_TYPE_TO_DRIVER = {
    1: "lhystudios",
    2: "grbl",
    3: "balor",
    4: "moshi",
    5: "newly",
    6: "ruida",
}


def parse_legacy_operations_cfg(filepath: str) -> Library:
    """Parse a legacy MeerK40t operations.cfg into a Library.

    The cfg has sections like:
      ``[import_0001 info]``  — entry metadata (title/material/thickness/...)
      ``[import_0001 000000]`` — an operation (type/id/label/power/speed/...)
      ``[import_0001 000001]`` — etc.

    Legacy convention (which differs from what the field names suggest):

      - ``material`` is a **source/group** label, e.g. ``"Internet"``,
        ``"Member Added"``, ``"Custom"``. Maps to our Category.
      - ``title`` is the **actual material name**, e.g. ``"Aluminum"``,
        ``"Copper Plated PCB"``. Maps to our MaterialEntry.
      - ``thickness`` is the thickness value. Maps to our ThicknessEntry.
      - ``laser`` is the laser-type tag. When consistent across the whole
        file, it lifts to ``library.driver``.

    Entries sharing a (category, material name) collapse into one
    MaterialEntry whose ``thicknesses`` collect the per-entry variants.
    """
    import configparser

    cfg = configparser.ConfigParser(interpolation=None)
    try:
        cfg.read(filepath, encoding="utf-8")
    except UnicodeDecodeError:
        cfg.read(filepath, encoding="latin-1")

    # Group sections by their material-id prefix.
    groups = {}  # prefix -> {"info": dict|None, "ops": [(suffix, dict), ...]}
    for section in cfg.sections():
        # Suffix is the part after the last space — either "info" or six digits.
        if " " not in section:
            continue
        prefix, _, suffix = section.rpartition(" ")
        bucket = groups.setdefault(prefix, {"info": None, "ops": []})
        if suffix == "info":
            bucket["info"] = dict(cfg[section])
        else:
            bucket["ops"].append((suffix, dict(cfg[section])))

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    categories = {}  # category_name -> Category
    laser_seen = set()

    for prefix, bucket in sorted(groups.items()):
        info = bucket["info"] or {}
        title = (info.get("title") or "").strip()
        material_field = (info.get("material") or "").strip()
        thickness_value = (info.get("thickness") or "").strip()
        note = (info.get("note") or "").replace("\\n", "\n").strip()
        try:
            laser = int(info.get("laser", 0))
        except (TypeError, ValueError):
            laser = 0
        laser_seen.add(laser)

        # Material name: prefer `title` (the legacy convention's actual
        # material name); fall back to the section prefix when missing.
        if title:
            material_name = title
        else:
            material_name = material_field or prefix
            # If we just used material_field as the name, don't ALSO use
            # it as a category — would cause a category named the same as
            # its only material.
            material_field = ""

        # Category name: the `material` field (source/group label). When
        # empty, fall back to a laser-type label so entries still group
        # meaningfully. When even that is generic, fall back to filename.
        if material_field:
            category_name = material_field
        elif laser != 0:
            category_name = _LASER_TYPE_LABELS.get(
                laser, f"Laser type {laser}"
            )
        else:
            category_name = base_name

        cat = categories.get(category_name)
        if cat is None:
            cat = Category(name=category_name)
            categories[category_name] = cat

        # Find or create the MaterialEntry inside the category.
        material = next(
            (m for m in cat.materials if m.name == material_name), None
        )
        if material is None:
            material = MaterialEntry(name=material_name)
            cat.materials.append(material)
        if note:
            material.notes = (
                f"{material.notes}\n{note}" if material.notes else note
            )

        # Build the operations list from the sorted op sections.
        ops = []
        op_id_counter = {}
        for suffix, params in sorted(bucket["ops"]):
            op = _legacy_section_to_op(params, op_id_counter)
            ops.append(op)
        if thickness_value:
            material.thicknesses.append(
                ThicknessEntry(value=thickness_value, operations=ops)
            )
        else:
            # No thickness recorded — attach loose to material (or fold
            # into the last thickness if any have been created already).
            if material.thicknesses:
                material.thicknesses[-1].operations.extend(ops)
            else:
                material.operations.extend(ops)

    # Library-level driver from a consistent laser type across all entries.
    driver_key = ""
    if len(laser_seen - {0}) == 1:
        driver_key = _LASER_TYPE_TO_DRIVER.get(
            next(iter(laser_seen - {0})), ""
        )

    # Lift consistent wattage/lens from metadata to library-level.
    lib_wattage = _most_common_numeric(
        (info.get("power") for bucket in groups.values()
         for info in [bucket["info"] or {}] if info.get("power"))
    )
    lib_lens = _most_common_string(
        (info.get("lens") for bucket in groups.values()
         for info in [bucket["info"] or {}] if info.get("lens"))
    )

    cats = sorted(categories.values(), key=lambda c: c.name)

    return Library(
        name=base_name,
        description=(
            f"Imported from legacy MeerK40t {os.path.basename(filepath)}"
        ),
        driver=driver_key,
        wattage=lib_wattage or 0.0,
        lens=lib_lens or "",
        # operations.cfg has historically stored values in MK's native PPI/mms.
        power_unit="ppi",
        speed_unit="mm/s",
        categories=cats,
    )


def _legacy_section_to_op(params: dict, id_counter: dict) -> "MaterialOperation":
    """Convert a legacy op section's key/value dict into a MaterialOperation."""
    op_type = params.get("type") or "op cut"
    op_id = params.get("id") or ""
    op_label = params.get("label") or ""
    settings = {}
    for k, raw in params.items():
        if k in _OP_INFO_DENYLIST:
            continue
        v = _coerce_value(raw)
        if v is not None:
            settings[k] = v
    # Auto-assign an ID if missing, following the C/E/R/I convention.
    if not op_id:
        prefix = op_type[3].upper() if len(op_type) > 3 else "O"
        id_counter[prefix] = id_counter.get(prefix, 0) + 1
        op_id = f"{prefix}{id_counter[prefix]}"
    normalize_passes_setting(settings)
    return MaterialOperation(
        type=op_type, id=op_id, label=op_label, settings=settings
    )


def _coerce_value(raw: str):
    """Best-effort string → typed value: bool, int, float, else string."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return ""
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "none":
        return None
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _most_common_numeric(values):
    seen = {}
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        seen[f] = seen.get(f, 0) + 1
    if not seen:
        return 0.0
    return max(seen.items(), key=lambda kv: kv[1])[0]


def _most_common_string(values):
    seen = {}
    for v in values:
        if not v:
            continue
        s = str(v).strip()
        if not s:
            continue
        seen[s] = seen.get(s, 0) + 1
    if not seen:
        return ""
    return max(seen.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MaterialLibraryService(Service):
    """Owns a dict of in-memory Library objects, mirrored to disk on shutdown."""

    def __init__(self, kernel, *args, **kwargs):
        Service.__init__(self, kernel, "matlib")
        self._libraries: dict = {}  # display-name -> Library
        # Cache of transient device services keyed by driver provider key.
        # Used so library-side editing of driver-specific op properties
        # works even when no real device of that driver is configured.
        # See get_transient_driver().
        self._transient_drivers: dict = {}
        # Allow tests (and advanced users) to override the libraries directory
        # via env var, so tests never touch real user data.
        override = os.environ.get("MEERK40T_MATLIB_DIR")
        if override:
            self._libraries_dir = override
        else:
            self._libraries_dir = os.path.join(
                get_safe_path(kernel.name, create=True), LIBRARIES_SUBDIR
            )
        os.makedirs(self._libraries_dir, exist_ok=True)
        self.load_all_libraries()
        self._register_commands()

    # -- Transient device factory (for library op editing) ------------------

    def get_transient_driver(self, driver_key: str):
        """Return a *transient* device service instance for the given driver
        key, suitable for hosting the driver's property panels even when the
        user has no configured device of that type.

        The returned service is NOT added to the kernel's active or
        available device list — it exists only for the matlib UI's
        property-panel hosting and is cached per-driver. Returns None if
        no provider is registered for that key, or if construction fails.

        Behavior:
          1. Looks up ``provider/device/<driver_key>`` to get the device class.
          2. Instantiates it under a transient path so its ``__init__``
             declarations (``setting(...)``, defaults) run normally.
          3. Sets ``registered_path`` so existing helpers that filter by
             ``provider/device/<driver_key>`` see it.
          4. Tries to call the driver's GUI plugin "added" lifecycle so
             its property-panel registrations land on this transient.
        """
        if not driver_key:
            return None
        if driver_key in self._transient_drivers:
            return self._transient_drivers[driver_key]

        device_cls = self.kernel.lookup(f"provider/device/{driver_key}")
        if device_cls is None:
            self._transient_drivers[driver_key] = None
            return None

        try:
            device = device_cls(
                self.kernel, f"matlib_transient/{driver_key}"
            )
        except Exception as exc:
            channel = self.kernel.channel("console")
            channel(
                f"matlib: could not instantiate transient device for "
                f"driver '{driver_key}': {exc}"
            )
            self._transient_drivers[driver_key] = None
            return None

        # The existing _find_driver_extra_panels helper filters by
        # registered_path; mirror what kernel.add_service would have set.
        device.registered_path = f"provider/device/{driver_key}"

        # Try to fire the driver's GUI plugin "added" lifecycle so it
        # populates this transient with its property-panel registrations.
        # We try the common convention <pkg>.gui.gui:plugin, falling back
        # to <pkg>.gui:plugin.
        try:
            import importlib
            module_path = type(device).__module__
            package = module_path.rsplit(".", 1)[0]
            gui_mod = None
            for candidate in (f"{package}.gui.gui", f"{package}.gui"):
                try:
                    gui_mod = importlib.import_module(candidate)
                    break
                except ImportError:
                    continue
            if gui_mod is not None and hasattr(gui_mod, "plugin"):
                try:
                    gui_mod.plugin(device, "added")
                except Exception as exc:
                    channel = self.kernel.channel("console")
                    channel(
                        f"matlib: transient device for '{driver_key}' "
                        f"created, but its GUI 'added' lifecycle raised: "
                        f"{exc}"
                    )
        except Exception:
            pass

        self._transient_drivers[driver_key] = device
        return device

    # -- discovery / I/O ----------------------------------------------------

    @property
    def libraries_dir(self) -> str:
        return self._libraries_dir

    def library_names(self) -> List[str]:
        return sorted(self._libraries.keys())

    def libraries(self) -> List[Library]:
        return [self._libraries[k] for k in self.library_names()]

    def get_library(self, name: str) -> Optional[Library]:
        return self._libraries.get(name)

    def _path_for(self, name: str) -> str:
        return os.path.join(
            self._libraries_dir, sanitize_library_filename(name) + MEERLIB_EXTENSION
        )

    def load_all_libraries(self) -> None:
        self._libraries.clear()
        if not os.path.isdir(self._libraries_dir):
            return
        for entry in sorted(os.listdir(self._libraries_dir)):
            if not entry.endswith(MEERLIB_EXTENSION):
                continue
            fullpath = os.path.join(self._libraries_dir, entry)
            try:
                lib = load_library_from_file(fullpath)
            except Exception as exc:
                # Don't kill startup; surface in console later if needed.
                channel = self.kernel.channel("console")
                channel(f"Failed to load library {entry}: {exc}")
                continue
            if not lib.name:
                lib.name = os.path.splitext(entry)[0]
            self._libraries[lib.name] = lib

    def save_library(self, lib: Library) -> None:
        """Save a managed library back to its file in the libraries dir."""
        if not lib.filepath:
            lib.filepath = self._path_for(lib.name)
        save_library_to_file(lib, lib.filepath)

    def save_all(self) -> None:
        """Save only libraries whose in-memory YAML differs from on-disk.
        Avoids rewriting unchanged files on every shutdown."""
        for lib in self._libraries.values():
            try:
                current = library_to_yaml(lib)
                on_disk = ""
                if lib.filepath and os.path.isfile(lib.filepath):
                    with open(lib.filepath, "r", encoding="utf-8") as f:
                        on_disk = f.read()
                if current != on_disk:
                    self.save_library(lib)
            except Exception as exc:
                channel = self.kernel.channel("console")
                channel(f"Failed to save library {lib.name}: {exc}")

    # -- CRUD ----------------------------------------------------------------

    def create_library(self, name: str, description: str = "") -> Library:
        if not name:
            raise ValueError("Library name required")
        if name in self._libraries:
            raise ValueError(f"Library '{name}' already exists")
        lib = Library(name=name, description=description)
        lib.filepath = self._path_for(name)
        self._libraries[name] = lib
        self.save_library(lib)
        return lib

    def delete_library(self, name: str) -> bool:
        lib = self._libraries.pop(name, None)
        if lib is None:
            return False
        path = lib.filepath or self._path_for(name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return True

    def rename_library(self, old_name: str, new_name: str) -> bool:
        """Rename a managed library. Renames the file on disk."""
        if not new_name:
            raise ValueError("New name required")
        if old_name == new_name:
            return False
        if old_name not in self._libraries:
            raise ValueError(f"No such library: {old_name}")
        if new_name in self._libraries:
            raise ValueError(f"Library '{new_name}' already exists")
        lib = self._libraries.pop(old_name)
        old_path = lib.filepath
        lib.name = new_name
        lib.filepath = self._path_for(new_name)
        self._libraries[new_name] = lib
        self.save_library(lib)
        if old_path and old_path != lib.filepath and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        return True

    def import_library_file(
        self, filepath: str, rename: Optional[str] = None
    ) -> Library:
        """Import a library file. Format is detected from the extension:
        ``.meerlib`` (native), ``.clb`` (LightBurn), ``.lib`` / ``.ini``
        (EzCad), ``.cfg`` (legacy MeerK40t). On failure to detect, falls
        back to trying each parser in order."""
        lib = parse_library_file(filepath)
        if rename:
            lib.name = rename
        if not lib.name:
            lib.name = os.path.splitext(os.path.basename(filepath))[0]
        # Disambiguate name collisions
        base = lib.name
        suffix = 1
        while lib.name in self._libraries:
            suffix += 1
            lib.name = f"{base} ({suffix})"
        lib.filepath = self._path_for(lib.name)
        self._libraries[lib.name] = lib
        self.save_library(lib)
        return lib

    def add_imported_library(self, lib: "Library") -> "Library":
        """Register an externally-parsed library as a new library managed
        by the service. Assigns a unique name on collision, sets the
        filepath under the libraries dir, persists, and returns it."""
        if not lib.name:
            lib.name = "imported"
        base = lib.name
        suffix = 1
        while lib.name in self._libraries:
            suffix += 1
            lib.name = f"{base} ({suffix})"
        lib.filepath = self._path_for(lib.name)
        self._libraries[lib.name] = lib
        self.save_library(lib)
        return lib

    def apply_library_to_document(
        self, identifier: str, elements_service
    ) -> bool:
        """Replace the document's operations with the ops from the library
        leaf identified by ``identifier``. Returns True on success.

        ``identifier`` is a JSON-encoded ``[lib_name, cat_path, mat_name,
        thk_value]``, where ``cat_path`` is ``">"``-joined category names
        (top-to-leaf) and an empty ``thk_value`` means the material has
        no thickness children. This is produced by the Library tree menu
        builder in element_treeops.py.
        """
        import json
        try:
            lib_name, cat_path, mat_name, thk_value = json.loads(identifier)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        lib = self.get_library(lib_name)
        if lib is None:
            return False
        container = lib
        if cat_path:
            for name in cat_path.split(">"):
                sub = next(
                    (c for c in container.categories if c.name == name),
                    None,
                )
                if sub is None:
                    return False
                container = sub
        mat = next(
            (m for m in container.materials if m.name == mat_name), None
        )
        if mat is None:
            return False
        if thk_value:
            thk = next(
                (t for t in mat.thicknesses if t.value == thk_value), None
            )
            if thk is None:
                return False
            ops = thk.operations
        else:
            ops = mat.operations
        return self.replace_document_ops(elements_service, ops)

    def replace_document_ops(self, elements_service, ops) -> bool:
        """Clear the elements service's op_branch (skipping branch/ref
        children) and add fresh op nodes from a list of MaterialOperation.
        Wrapped in an undoscope when available."""
        op_branch = elements_service.op_branch

        def _do_replace():
            for child in list(op_branch.children):
                ctype = child.type or ""
                if ctype.startswith("branch") or ctype.startswith("ref"):
                    continue
                child.remove_node()
            for mat_op in ops:
                # Make sure passes_custom matches passes>1 before push.
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

        try:
            with elements_service.undoscope("Load library entry"):
                _do_replace()
        except AttributeError:
            _do_replace()
        elements_service.signal("rebuild_tree", "operations")
        return True

    def merge_library_into(
        self, source_lib: "Library", dest_lib: "Library"
    ) -> None:
        """Merge ``source_lib``'s categories into ``dest_lib`` in place.

        Categories collide-by-name: if ``dest_lib`` already has a category
        with the same name, materials from the matching source category
        are appended to it (renamed on duplicate). New categories are
        added at the end. Persists ``dest_lib`` on success.
        """
        for src_cat in source_lib.categories:
            existing = next(
                (c for c in dest_lib.categories if c.name == src_cat.name),
                None,
            )
            if existing is None:
                # Clone so the dest library owns its own objects.
                dest_lib.categories.append(clone_node(src_cat))
            else:
                # Append materials and sub-categories from src into existing.
                for sub in src_cat.categories:
                    sub_clone = clone_node(sub)
                    sub_clone.name = make_unique_name(
                        sub_clone.name,
                        [c.name for c in existing.categories],
                    )
                    existing.categories.append(sub_clone)
                for mat in src_cat.materials:
                    mat_clone = clone_node(mat)
                    mat_clone.name = make_unique_name(
                        mat_clone.name,
                        [m.name for m in existing.materials],
                    )
                    existing.materials.append(mat_clone)
        self.save_library(dest_lib)

    def export_library(self, name: str, filepath: str) -> None:
        lib = self.get_library(name)
        if lib is None:
            raise ValueError(f"No such library: {name}")
        save_library_to_file(lib, filepath)

    # -- shutdown -----------------------------------------------------------

    def shutdown(self, *args, **kwargs):
        self.save_all()

    # -- console commands ---------------------------------------------------

    def _register_commands(self):
        _ = self.kernel.translation

        @self.console_command(
            "matlib",
            help=_("Material library base command — lists libraries when bare."),
            input_type=None,
            output_type="matlib",
        )
        def matlib_root(command, channel, _, remainder=None, **kwargs):
            if remainder is None:
                channel("----------")
                channel(_("Material Libraries:"))
                if not self._libraries:
                    channel(_("  (none — use 'matlib new <name>' to create one)"))
                for lib in self.libraries():
                    n_cats = len(lib.categories)
                    n_mats = sum(_count_materials(c) for c in lib.categories)
                    channel(
                        f"  {lib.name}  "
                        f"[{n_cats} categories, {n_mats} materials]"
                    )
                channel("----------")
            return "matlib", None

        @self.console_argument("name", type=str, help=_("Library name"))
        @self.console_option(
            "description", "d", type=str, help=_("Library description")
        )
        @self.console_command(
            "new",
            help=_("Create a new empty material library"),
            input_type="matlib",
            output_type="matlib",
        )
        def matlib_new(
            command, channel, _, name=None, description=None, **kwargs
        ):
            if not name:
                raise CommandSyntaxError(_("name required"))
            try:
                lib = self.create_library(name, description or "")
            except ValueError as exc:
                channel(str(exc))
                return "matlib", None
            channel(_("Created library '{name}' at {path}").format(
                name=lib.name, path=lib.filepath
            ))
            return "matlib", lib.name

        @self.console_argument("name", type=str, help=_("Library name"))
        @self.console_command(
            "delete",
            help=_("Delete a material library (removes the file)"),
            input_type="matlib",
            output_type="matlib",
        )
        def matlib_delete(command, channel, _, name=None, **kwargs):
            if not name:
                raise CommandSyntaxError(_("name required"))
            if self.delete_library(name):
                channel(_("Deleted library '{name}'").format(name=name))
            else:
                channel(_("No such library: {name}").format(name=name))
            return "matlib", None

        @self.console_argument("name", type=str, help=_("Library name"))
        @self.console_command(
            "show",
            help=_("Show the structure of a material library"),
            input_type="matlib",
            output_type="matlib",
        )
        def matlib_show(command, channel, _, name=None, **kwargs):
            if not name:
                raise CommandSyntaxError(_("name required"))
            lib = self.get_library(name)
            if lib is None:
                channel(_("No such library: {name}").format(name=name))
                return "matlib", None
            channel(f"Library: {lib.name}")
            if lib.description:
                channel(f"  description: {lib.description}")
            if lib.source or lib.wattage:
                bits = []
                if lib.source:
                    bits.append(lib.source)
                if lib.wattage:
                    bits.append(f"{lib.wattage:g}W")
                if lib.motion:
                    bits.append(lib.motion)
                if lib.lens:
                    bits.append(lib.lens)
                channel(f"  {' / '.join(bits)}")
            channel(f"  file: {lib.filepath}")
            for cat in lib.categories:
                _print_category(channel, cat, indent=1)
            return "matlib", name

        @self.console_argument("name", type=str, help=_("Library name"))
        @self.console_argument("filepath", type=str, help=_("Destination path"))
        @self.console_command(
            "export",
            help=_("Export a library to a file"),
            input_type="matlib",
            output_type="matlib",
        )
        def matlib_export(command, channel, _, name=None, filepath=None, **kwargs):
            if not name or not filepath:
                raise CommandSyntaxError(_("name and filepath required"))
            try:
                self.export_library(name, filepath)
            except ValueError as exc:
                channel(str(exc))
                return "matlib", None
            channel(_("Exported '{name}' to {path}").format(name=name, path=filepath))
            return "matlib", name

        @self.console_argument("filepath", type=str, help=_("Source path"))
        @self.console_option("rename", "r", type=str, help=_("Rename on import"))
        @self.console_command(
            "import",
            help=_("Import a .meerlib library file"),
            input_type="matlib",
            output_type="matlib",
        )
        def matlib_import(
            command, channel, _, filepath=None, rename=None, **kwargs
        ):
            if not filepath:
                raise CommandSyntaxError(_("filepath required"))
            if not os.path.isfile(filepath):
                channel(_("File not found: {path}").format(path=filepath))
                return "matlib", None
            try:
                lib = self.import_library_file(filepath, rename=rename)
            except Exception as exc:
                channel(_("Failed to import {path}: {exc}").format(
                    path=filepath, exc=exc
                ))
                return "matlib", None
            channel(_("Imported library '{name}'").format(name=lib.name))
            return "matlib", lib.name


# ---------------------------------------------------------------------------
# Helpers for the show command
# ---------------------------------------------------------------------------


def _count_materials(cat: Category) -> int:
    return len(cat.materials) + sum(_count_materials(c) for c in cat.categories)


def _print_category(channel, cat: Category, indent: int = 0) -> None:
    pad = "  " * indent
    channel(f"{pad}[cat] {cat.name}")
    for c in cat.categories:
        _print_category(channel, c, indent + 1)
    for m in cat.materials:
        _print_material(channel, m, indent + 1)


def _print_material(channel, mat: MaterialEntry, indent: int = 0) -> None:
    pad = "  " * indent
    channel(f"{pad}[mat] {mat.name}")
    for t in mat.thicknesses:
        channel(f"{pad}  [thk] {t.value}  ({len(t.operations)} ops)")
    if mat.operations:
        channel(f"{pad}  ({len(mat.operations)} loose ops)")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def plugin(kernel, lifecycle=None):
    if lifecycle == "register":
        kernel.add_service("matlib", MaterialLibraryService(kernel))
