"""Tests for the material_library data layer and matlib service."""

import os
import shutil
import tempfile
import unittest

from test import bootstrap

from meerk40t.core.elements.material_library import (
    KIND_CATEGORY,
    KIND_MATERIAL,
    KIND_THICKNESS,
    UNCATEGORIZED_NAME,
    Category,
    Library,
    MaterialEffect,
    MaterialEntry,
    MaterialLibraryService,
    MaterialOperation,
    ThicknessEntry,
    can_move_node,
    clone_node,
    discover_effect_types,
    find_or_create_uncategorized,
    find_parent,
    get_effect_schema,
    is_descendant_of,
    library_from_yaml,
    library_to_yaml,
    load_library_from_file,
    make_unique_name,
    match_op_against_query,
    move_node,
    normalize_passes_setting,
    parse_ezcad_library,
    parse_legacy_operations_cfg,
    parse_library_file,
    parse_lightburn_library,
    parse_search_query,
    sanitize_library_filename,
    save_library_to_file,
    short_effect_name,
    wrap_for_export,
)


class TestMaterialLibraryDataModel(unittest.TestCase):
    """Pure data-layer tests (no kernel needed)."""

    def test_round_trip_minimal_library(self):
        lib = Library(name="Empty", description="nothing here")
        text = library_to_yaml(lib)
        restored = library_from_yaml(text)
        self.assertEqual(restored.name, "Empty")
        self.assertEqual(restored.description, "nothing here")
        self.assertEqual(restored.categories, [])

    def test_round_trip_full_tree(self):
        op = MaterialOperation(
            type="op cut",
            id="C1",
            label="Through cut",
            settings={"power": 1000, "speed": 10, "passes": 1},
        )
        thk = ThicknessEntry(value="3mm", notes="birch", operations=[op])
        mat = MaterialEntry(name="Plywood", thicknesses=[thk])
        sub_cat = Category(name="Subcat", materials=[
            MaterialEntry(name="Leather", operations=[op]),
        ])
        cat = Category(name="Wood", color="#8B4513",
                       categories=[sub_cat], materials=[mat])
        lib = Library(name="K40", categories=[cat])

        text = library_to_yaml(lib)
        restored = library_from_yaml(text)
        self.assertEqual(len(restored.categories), 1)
        wood = restored.categories[0]
        self.assertEqual(wood.name, "Wood")
        self.assertEqual(wood.color, "#8B4513")
        self.assertEqual(len(wood.categories), 1)
        self.assertEqual(wood.categories[0].name, "Subcat")
        self.assertEqual(wood.categories[0].materials[0].name, "Leather")
        plywood = wood.materials[0]
        self.assertEqual(plywood.name, "Plywood")
        self.assertEqual(len(plywood.thicknesses), 1)
        self.assertEqual(plywood.thicknesses[0].value, "3mm")
        op_back = plywood.thicknesses[0].operations[0]
        self.assertEqual(op_back.type, "op cut")
        self.assertEqual(op_back.id, "C1")
        self.assertEqual(op_back.settings["power"], 1000)

    def test_material_with_loose_operations_no_thickness(self):
        mat = MaterialEntry(
            name="Anodized Aluminum",
            operations=[
                MaterialOperation(type="op engrave", id="E1", label="mark"),
            ],
        )
        cat = Category(name="Metal", materials=[mat])
        lib = Library(name="X", categories=[cat])
        restored = library_from_yaml(library_to_yaml(lib))
        m = restored.categories[0].materials[0]
        self.assertEqual(m.name, "Anodized Aluminum")
        self.assertEqual(len(m.thicknesses), 0)
        self.assertEqual(len(m.operations), 1)

    def test_legacy_loose_materials_migrate_to_uncategorized(self):
        # Simulate a legacy on-disk file that had materials at the root.
        legacy = {
            "name": "Legacy",
            "categories": [{"name": "Wood", "materials": []}],
            "materials": [
                {"name": "Loose1"},
                {"name": "Loose2"},
            ],
        }
        lib = Library.from_dict(legacy)
        # Wood survives; Uncategorized is added at the end with both loose mats.
        names = [c.name for c in lib.categories]
        self.assertIn("Wood", names)
        self.assertIn(UNCATEGORIZED_NAME, names)
        unc = next(c for c in lib.categories if c.name == UNCATEGORIZED_NAME)
        self.assertEqual([m.name for m in unc.materials], ["Loose1", "Loose2"])
        # Round-trip drops the obsolete root "materials" key.
        restored = library_from_yaml(library_to_yaml(lib))
        # Uncategorized still present after round-trip.
        self.assertIn(
            UNCATEGORIZED_NAME, [c.name for c in restored.categories]
        )

    def test_legacy_loose_materials_merge_with_existing_uncategorized(self):
        legacy = {
            "name": "L",
            "categories": [{"name": UNCATEGORIZED_NAME, "materials": [
                {"name": "Existing"},
            ]}],
            "materials": [{"name": "Loose"}],
        }
        lib = Library.from_dict(legacy)
        unc = next(c for c in lib.categories if c.name == UNCATEGORIZED_NAME)
        # Existing material kept; loose appended.
        self.assertEqual([m.name for m in unc.materials], ["Existing", "Loose"])

    def test_find_or_create_uncategorized_is_idempotent(self):
        lib = Library(name="X")
        a = find_or_create_uncategorized(lib)
        b = find_or_create_uncategorized(lib)
        self.assertIs(a, b)
        self.assertEqual(len(lib.categories), 1)
        self.assertEqual(a.name, UNCATEGORIZED_NAME)

    def test_from_dict_with_missing_keys(self):
        lib = Library.from_dict({"name": "Bare"})
        self.assertEqual(lib.name, "Bare")
        self.assertEqual(lib.categories, [])

    def test_schema_field_present_in_serialized_output(self):
        lib = Library(name="X")
        d = lib.to_dict()
        self.assertEqual(d["schema"], Library.SCHEMA_VERSION)

    def test_library_metadata_round_trip(self):
        lib = Library(
            name="K40",
            description="my plywood setup",
            driver="lhystudios",
            motion="gantry",
            source="co2",
            wattage=50,
            lens="50mm",
            power_unit="ppi",
            speed_unit="mm/s",
        )
        restored = library_from_yaml(library_to_yaml(lib))
        self.assertEqual(restored.driver, "lhystudios")
        self.assertEqual(restored.motion, "gantry")
        self.assertEqual(restored.source, "co2")
        self.assertEqual(restored.wattage, 50.0)
        self.assertEqual(restored.lens, "50mm")
        self.assertEqual(restored.power_unit, "ppi")
        self.assertEqual(restored.speed_unit, "mm/s")

    def test_legacy_device_hint_promotes_to_driver(self):
        # An earlier prototype stored this value under "device_hint"; we
        # honor it so old files don't lose the association.
        lib = Library.from_dict({"name": "X", "device_hint": "grbl"})
        self.assertEqual(lib.driver, "grbl")

    def test_driver_takes_precedence_over_legacy_device_hint(self):
        lib = Library.from_dict(
            {"name": "X", "driver": "balor", "device_hint": "grbl"}
        )
        self.assertEqual(lib.driver, "balor")

    def test_library_metadata_freetext_values(self):
        # motion/source can hold arbitrary user-typed values.
        lib = Library(name="X", motion="custom_xy", source="exotic_laser")
        restored = library_from_yaml(library_to_yaml(lib))
        self.assertEqual(restored.motion, "custom_xy")
        self.assertEqual(restored.source, "exotic_laser")

    def test_library_metadata_defaults(self):
        lib = Library(name="X")
        self.assertEqual(lib.driver, "")
        self.assertEqual(lib.motion, "")
        self.assertEqual(lib.source, "")
        self.assertEqual(lib.wattage, 0.0)
        self.assertEqual(lib.lens, "")
        # Power and speed default to the most common units so new libraries
        # have sensible values without needing to open the properties dialog.
        self.assertEqual(lib.power_unit, "percent")
        self.assertEqual(lib.speed_unit, "mm/s")

    def test_legacy_column_flags_ignored(self):
        # Older files set show_frequency / show_pulse_width as bools;
        # these are no longer modeled (visibility derives from driver),
        # so loading shouldn't raise — just silently drop the keys.
        lib = Library.from_dict({
            "name": "L",
            "show_frequency": True,
            "show_pulse_width": True,
        })
        self.assertFalse(hasattr(lib, "show_frequency"))
        self.assertFalse(hasattr(lib, "show_pulse_width"))

    def test_sanitize_library_filename(self):
        self.assertEqual(sanitize_library_filename("My Library"), "My Library")
        self.assertEqual(sanitize_library_filename("a/b\\c:d"), "a_b_c_d")
        # collapsed: regex replaces runs of unsafe chars with a single underscore
        self.assertEqual(sanitize_library_filename("foo<>bar"), "foo_bar")
        self.assertEqual(sanitize_library_filename(""), "library")

    def test_save_and_load_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "test.meerlib")
            lib = Library(
                name="Disk Test",
                categories=[Category(name="Cat1", materials=[
                    MaterialEntry(name="M1", operations=[
                        MaterialOperation(type="op cut", id="C1",
                                          settings={"power": 500}),
                    ])
                ])],
            )
            save_library_to_file(lib, path)
            self.assertTrue(os.path.isfile(path))
            restored = load_library_from_file(path)
            self.assertEqual(restored.name, "Disk Test")
            self.assertEqual(restored.filepath, path)
            self.assertEqual(restored.categories[0].materials[0].name, "M1")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestTreeHelpers(unittest.TestCase):
    """Tests for clone_node, find_parent, and make_unique_name."""

    def _build_sample_library(self):
        op = MaterialOperation(type="op cut", id="C1",
                               settings={"power": 100, "speed": 5})
        thk = ThicknessEntry(value="3mm", operations=[op])
        plywood = MaterialEntry(name="Plywood", thicknesses=[thk])
        leather = MaterialEntry(name="Leather", operations=[op])
        sub = Category(name="Sub", materials=[leather])
        wood = Category(name="Wood", categories=[sub], materials=[plywood])
        misc = Category(name="Misc", materials=[MaterialEntry(name="MiscMat")])
        lib = Library(name="L", categories=[wood, misc])
        return lib, wood, sub, plywood, leather, thk, misc

    def test_clone_node_category_is_independent(self):
        lib, wood, sub, plywood, leather, thk, misc = self._build_sample_library()
        clone = clone_node(wood)
        clone.name = "WoodCopy"
        clone.materials[0].name = "OtherPlywood"
        # original untouched
        self.assertEqual(wood.name, "Wood")
        self.assertEqual(wood.materials[0].name, "Plywood")

    def test_clone_node_material_is_independent(self):
        _, _, _, plywood, _, _, _ = self._build_sample_library()
        clone = clone_node(plywood)
        clone.thicknesses[0].value = "9mm"
        self.assertEqual(plywood.thicknesses[0].value, "3mm")

    def test_clone_node_thickness_is_independent(self):
        _, _, _, _, _, thk, _ = self._build_sample_library()
        clone = clone_node(thk)
        clone.operations[0].settings["power"] = 999
        self.assertEqual(thk.operations[0].settings["power"], 100)

    def test_clone_node_unsupported_type(self):
        with self.assertRaises(TypeError):
            clone_node(object())

    def test_find_parent_top_level_category(self):
        lib, wood, sub, plywood, leather, thk, misc = self._build_sample_library()
        self.assertIs(find_parent(lib, wood), lib)
        self.assertIs(find_parent(lib, misc), lib)

    def test_find_parent_nested_category(self):
        lib, wood, sub, plywood, leather, thk, misc = self._build_sample_library()
        self.assertIs(find_parent(lib, sub), wood)

    def test_find_parent_material_in_category(self):
        lib, wood, sub, plywood, leather, thk, misc = self._build_sample_library()
        self.assertIs(find_parent(lib, plywood), wood)
        self.assertIs(find_parent(lib, leather), sub)

    def test_find_parent_thickness_in_material(self):
        lib, wood, sub, plywood, leather, thk, misc = self._build_sample_library()
        self.assertIs(find_parent(lib, thk), plywood)

    def test_find_parent_not_in_library(self):
        lib, _, _, _, _, _, _ = self._build_sample_library()
        orphan = Category(name="X")
        self.assertIsNone(find_parent(lib, orphan))

    def test_make_unique_name_no_collision(self):
        self.assertEqual(make_unique_name("Plywood", []), "Plywood")
        self.assertEqual(make_unique_name("Plywood", ["Acrylic"]), "Plywood")

    def test_make_unique_name_collision(self):
        self.assertEqual(
            make_unique_name("Plywood", ["Plywood"]), "Plywood (2)"
        )
        self.assertEqual(
            make_unique_name("Plywood", ["Plywood", "Plywood (2)"]),
            "Plywood (3)",
        )


class TestMaterialEffect(unittest.TestCase):
    def test_round_trip(self):
        eff = MaterialEffect(
            type="effect hatch",
            settings={"hatch_distance": "1mm", "hatch_angle": "0deg",
                      "loops": 2, "unidirectional": True},
        )
        op = MaterialOperation(
            type="op raster", id="R1",
            settings={"power": 1000, "speed": 50},
            effects=[eff],
        )
        restored = MaterialOperation.from_dict(op.to_dict())
        self.assertEqual(len(restored.effects), 1)
        e0 = restored.effects[0]
        self.assertEqual(e0.type, "effect hatch")
        self.assertEqual(e0.settings["hatch_distance"], "1mm")
        self.assertEqual(e0.settings["loops"], 2)
        self.assertTrue(e0.settings["unidirectional"])

    def test_operation_without_effects_serializes_empty_list(self):
        op = MaterialOperation(type="op cut")
        d = op.to_dict()
        self.assertEqual(d["effects"], [])

    def test_legacy_operation_yaml_without_effects_loads(self):
        # A dict missing the "effects" key (older file) loads with no effects.
        op = MaterialOperation.from_dict({"type": "op cut", "id": "C1"})
        self.assertEqual(op.effects, [])

    def test_full_yaml_round_trip_with_effects(self):
        op = MaterialOperation(
            type="op raster", id="R1",
            settings={"power": 1000, "speed": 50},
            effects=[
                MaterialEffect(type="effect hatch",
                               settings={"hatch_distance": "1mm"}),
                MaterialEffect(type="effect wobble",
                               settings={"wobble_radius": "0.5mm",
                                         "wobble_speed": 50.0}),
            ],
        )
        mat = MaterialEntry(name="Plywood", operations=[op])
        cat = Category(name="Wood", materials=[mat])
        lib = Library(name="L", categories=[cat])
        restored = library_from_yaml(library_to_yaml(lib))
        ops = restored.categories[0].materials[0].operations
        self.assertEqual(len(ops[0].effects), 2)
        self.assertEqual(ops[0].effects[0].type, "effect hatch")
        self.assertEqual(ops[0].effects[1].settings["wobble_radius"], "0.5mm")

    def test_clone_node_for_effect(self):
        eff = MaterialEffect(type="effect hatch", settings={"loops": 3})
        clone = clone_node(eff)
        clone.settings["loops"] = 99
        self.assertEqual(eff.settings["loops"], 3)


class TestEffectDiscovery(unittest.TestCase):
    def test_discover_returns_only_effects_with_schemas(self):
        types = discover_effect_types()
        # Hatch and wobble have curated schemas, so they appear.
        self.assertIn("effect hatch", types)
        self.assertIn("effect wobble", types)
        # Warp exists in the node bootstrap but lacks a schema, so it's
        # filtered out of the library UI.
        self.assertNotIn("effect warp", types)

    def test_discover_results_are_sorted(self):
        types = discover_effect_types()
        self.assertEqual(types, sorted(types))

    def test_schema_for_known_effects(self):
        hatch = get_effect_schema("effect hatch")
        self.assertTrue(any(f["key"] == "hatch_distance" for f in hatch))
        wobble = get_effect_schema("effect wobble")
        self.assertTrue(any(f["key"] == "wobble_radius" for f in wobble))

    def test_schema_for_unknown_is_empty(self):
        # Plugin-supplied / future effects with no curated schema return [].
        self.assertEqual(get_effect_schema("effect bogus"), [])

    def test_short_effect_name(self):
        self.assertEqual(short_effect_name("effect hatch"), "hatch")
        self.assertEqual(short_effect_name("plain"), "plain")


class TestSearchQueryParser(unittest.TestCase):
    def test_empty_query(self):
        free, fields = parse_search_query("")
        self.assertEqual(free, [])
        self.assertEqual(fields, {})

    def test_pure_free_text(self):
        free, fields = parse_search_query("black wood plywood")
        self.assertEqual(free, ["black", "wood", "plywood"])
        self.assertEqual(fields, {})

    def test_pure_field_filters(self):
        free, fields = parse_search_query("material:steel thickness:3mm")
        self.assertEqual(free, [])
        self.assertEqual(fields, {"material": "steel", "thickness": "3mm"})

    def test_mixed(self):
        free, fields = parse_search_query("black material:steel")
        self.assertEqual(free, ["black"])
        self.assertEqual(fields, {"material": "steel"})

    def test_case_insensitive(self):
        free, fields = parse_search_query("BLACK Material:Steel")
        self.assertEqual(free, ["black"])
        self.assertEqual(fields, {"material": "steel"})

    def test_empty_field_value_treated_as_free_text(self):
        free, fields = parse_search_query("material: orphan")
        # 'material:' with no value should NOT register a field filter;
        # both fragments are treated as free text instead.
        self.assertIn("orphan", free)
        self.assertNotIn("material", fields)


class TestMatchOpAgainstQuery(unittest.TestCase):
    def _make_op(self, type="op cut", id="C1", label="cut", **settings):
        return MaterialOperation(
            type=type, id=id, label=label, settings=dict(settings)
        )

    def test_free_text_matches_label(self):
        op = self._make_op(label="black cut")
        self.assertTrue(
            match_op_against_query(op, "wood", "plywood", "3mm", ["black"], {})
        )

    def test_free_text_matches_path(self):
        op = self._make_op(label="cut")
        self.assertTrue(
            match_op_against_query(op, "wood", "plywood", "3mm", ["plywood"], {})
        )

    def test_free_text_matches_setting_value(self):
        op = self._make_op(power=800)
        self.assertTrue(
            match_op_against_query(op, "", "", "", ["800"], {})
        )

    def test_free_text_all_tokens_required(self):
        op = self._make_op(label="black cut")
        # 'red' isn't anywhere — fails even though 'black' is present.
        self.assertFalse(
            match_op_against_query(
                op, "wood", "plywood", "3mm", ["black", "red"], {}
            )
        )

    def test_op_type_field_filter(self):
        cut = self._make_op(type="op cut")
        eng = self._make_op(type="op engrave")
        self.assertTrue(
            match_op_against_query(cut, "", "", "", [], {"op": "cut"})
        )
        self.assertFalse(
            match_op_against_query(eng, "", "", "", [], {"op": "cut"})
        )

    def test_power_field_filter(self):
        op = self._make_op(power=800)
        self.assertTrue(
            match_op_against_query(op, "", "", "", [], {"power": "800"})
        )
        self.assertFalse(
            match_op_against_query(op, "", "", "", [], {"power": "999"})
        )

    def test_effect_field_filter(self):
        op = self._make_op()
        op.effects.append(MaterialEffect(type="effect hatch"))
        self.assertTrue(
            match_op_against_query(op, "", "", "", [], {"effect": "hatch"})
        )
        self.assertFalse(
            match_op_against_query(op, "", "", "", [], {"effect": "wobble"})
        )


class TestNormalizePassesSetting(unittest.TestCase):
    def test_sets_custom_flag_when_passes_greater_than_one(self):
        s = {"passes": 3}
        normalize_passes_setting(s)
        self.assertTrue(s["passes_custom"])

    def test_removes_stale_custom_flag_when_passes_back_to_one(self):
        s = {"passes": 1, "passes_custom": True}
        normalize_passes_setting(s)
        self.assertNotIn("passes_custom", s)

    def test_removes_stale_custom_flag_when_passes_zero(self):
        s = {"passes": 0, "passes_custom": True}
        normalize_passes_setting(s)
        self.assertNotIn("passes_custom", s)

    def test_noop_when_no_passes_key(self):
        s = {"power": 100}
        normalize_passes_setting(s)
        self.assertNotIn("passes_custom", s)

    def test_handles_float_or_string_passes(self):
        s = {"passes": "2"}
        normalize_passes_setting(s)
        self.assertTrue(s["passes_custom"])
        s = {"passes": 2.0}
        normalize_passes_setting(s)
        self.assertTrue(s["passes_custom"])

    def test_lightburn_import_sets_passes_custom(self):
        # An entry with numPasses=2 should land in the library with
        # passes_custom=True so the document op respects the count when
        # pushed.
        sample = """<?xml version="1.0"?>
<LightBurnLibrary>
  <Material name="Wood">
    <Entry Thickness="6" Desc="Heavy">
      <CutSetting type="Cut">
        <maxPower Value="100"/>
        <speed Value="5"/>
        <numPasses Value="2"/>
      </CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.clb")
            with open(path, "w") as f:
                f.write(sample)
            lib = parse_lightburn_library(path)
            op = (
                lib.categories[0].materials[0].thicknesses[0].operations[0]
            )
            self.assertEqual(op.settings["passes"], 2)
            self.assertTrue(op.settings["passes_custom"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestExportWrapping(unittest.TestCase):
    def test_wrap_category(self):
        cat = Category(name="Wood", materials=[
            MaterialEntry(name="Plywood"),
        ])
        lib = wrap_for_export(cat)
        self.assertEqual(lib.name, "Wood")
        self.assertEqual(len(lib.categories), 1)
        self.assertEqual(lib.categories[0].name, "Wood")
        # Independent clone:
        lib.categories[0].name = "Changed"
        self.assertEqual(cat.name, "Wood")

    def test_wrap_material_creates_uncategorized(self):
        mat = MaterialEntry(name="Acrylic")
        lib = wrap_for_export(mat)
        self.assertEqual(lib.name, "Acrylic")
        self.assertEqual(len(lib.categories), 1)
        self.assertEqual(lib.categories[0].name, UNCATEGORIZED_NAME)
        self.assertEqual(lib.categories[0].materials[0].name, "Acrylic")

    def test_wrap_thickness_rejected(self):
        thk = ThicknessEntry(value="3mm")
        with self.assertRaises(TypeError):
            wrap_for_export(thk)

    def test_wrap_uses_explicit_library_name(self):
        cat = Category(name="Wood")
        lib = wrap_for_export(cat, library_name="My Export")
        self.assertEqual(lib.name, "My Export")


class TestMoveLogic(unittest.TestCase):
    """Cycle prevention, validity rules, and the actual move mutation."""

    def _build(self):
        thk1 = ThicknessEntry(value="3mm")
        thk2 = ThicknessEntry(value="6mm")
        plywood = MaterialEntry(name="Plywood", thicknesses=[thk1, thk2])
        mdf = MaterialEntry(name="MDF")
        sub = Category(name="Sub", materials=[MaterialEntry(name="Leather")])
        wood = Category(name="Wood", categories=[sub], materials=[plywood, mdf])
        acrylic = Category(name="Acrylic", materials=[
            MaterialEntry(name="Cast"),
        ])
        lib = Library(name="L", categories=[wood, acrylic])
        return lib, wood, sub, plywood, mdf, thk1, thk2, acrylic

    # -- is_descendant_of ---------------------------------------------------

    def test_is_descendant_of_self(self):
        cat = Category(name="X")
        self.assertTrue(is_descendant_of(cat, cat))

    def test_is_descendant_of_nested_category(self):
        lib, wood, sub, *_ = self._build()
        self.assertTrue(is_descendant_of(sub, wood))

    def test_is_descendant_of_material(self):
        lib, wood, sub, plywood, *_ = self._build()
        self.assertTrue(is_descendant_of(plywood, wood))

    def test_is_descendant_of_thickness(self):
        lib, wood, _, _, _, thk1, *_ = self._build()
        self.assertTrue(is_descendant_of(thk1, wood))

    def test_is_descendant_of_unrelated(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertFalse(is_descendant_of(plywood, acrylic))
        self.assertFalse(is_descendant_of(wood, acrylic))

    # -- can_move_node ------------------------------------------------------

    def test_can_move_category_to_category(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(can_move_node(
            lib, KIND_CATEGORY, acrylic, KIND_CATEGORY, wood
        ))

    def test_can_move_category_to_root(self):
        lib, wood, sub, *_ = self._build()
        self.assertTrue(can_move_node(lib, KIND_CATEGORY, sub, None, None))

    def test_cannot_move_category_into_own_descendant(self):
        lib, wood, sub, *_ = self._build()
        self.assertFalse(can_move_node(
            lib, KIND_CATEGORY, wood, KIND_CATEGORY, sub
        ))

    def test_cannot_move_category_onto_self(self):
        lib, wood, *_ = self._build()
        self.assertFalse(can_move_node(
            lib, KIND_CATEGORY, wood, KIND_CATEGORY, wood
        ))

    def test_can_move_material_to_category(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(can_move_node(
            lib, KIND_MATERIAL, plywood, KIND_CATEGORY, acrylic
        ))

    def test_can_move_material_to_sibling(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(can_move_node(
            lib, KIND_MATERIAL, plywood, KIND_MATERIAL, mdf
        ))

    def test_cannot_move_material_to_root(self):
        lib, wood, sub, plywood, *_ = self._build()
        self.assertFalse(can_move_node(
            lib, KIND_MATERIAL, plywood, None, None
        ))

    def test_cannot_move_material_onto_thickness(self):
        lib, wood, sub, plywood, mdf, thk1, *_ = self._build()
        self.assertFalse(can_move_node(
            lib, KIND_MATERIAL, mdf, KIND_THICKNESS, thk1
        ))

    def test_can_move_thickness_to_material(self):
        lib, wood, sub, plywood, mdf, thk1, *_ = self._build()
        self.assertTrue(can_move_node(
            lib, KIND_THICKNESS, thk1, KIND_MATERIAL, mdf
        ))

    def test_can_move_thickness_to_sibling(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(can_move_node(
            lib, KIND_THICKNESS, thk1, KIND_THICKNESS, thk2
        ))

    def test_cannot_move_thickness_to_category(self):
        lib, wood, sub, plywood, mdf, thk1, *_ = self._build()
        self.assertFalse(can_move_node(
            lib, KIND_THICKNESS, thk1, KIND_CATEGORY, wood
        ))

    # -- move_node mutation -------------------------------------------------

    def test_move_category_to_root(self):
        lib, wood, sub, *_ = self._build()
        self.assertTrue(move_node(lib, KIND_CATEGORY, sub, None, None))
        self.assertIn(sub, lib.categories)
        self.assertNotIn(sub, wood.categories)

    def test_move_material_between_categories(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(move_node(
            lib, KIND_MATERIAL, plywood, KIND_CATEGORY, acrylic
        ))
        self.assertNotIn(plywood, wood.materials)
        self.assertIn(plywood, acrylic.materials)

    def test_move_thickness_to_other_material(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        self.assertTrue(move_node(
            lib, KIND_THICKNESS, thk1, KIND_MATERIAL, mdf
        ))
        self.assertNotIn(thk1, plywood.thicknesses)
        self.assertIn(thk1, mdf.thicknesses)

    def test_move_material_to_sibling_inserts_after(self):
        lib, wood, sub, plywood, mdf, *_ = self._build()
        # Move mdf to be right after plywood (already after — let's reorder)
        # plywood is at index 0, mdf at index 1. Move plywood after mdf.
        move_node(lib, KIND_MATERIAL, plywood, KIND_MATERIAL, mdf)
        self.assertEqual(
            [m.name for m in wood.materials], ["MDF", "Plywood"]
        )

    def test_move_renames_on_collision(self):
        lib, wood, sub, plywood, mdf, thk1, thk2, acrylic = self._build()
        # Add another Plywood inside Acrylic to force a collision.
        rival = MaterialEntry(name="Plywood")
        acrylic.materials.append(rival)
        move_node(lib, KIND_MATERIAL, plywood, KIND_CATEGORY, acrylic)
        names = [m.name for m in acrylic.materials]
        self.assertIn("Plywood", names)
        self.assertIn("Plywood (2)", names)

    def test_move_invalid_does_nothing(self):
        lib, wood, sub, *_ = self._build()
        before = [c.name for c in wood.categories]
        # Try to move wood into its descendant sub — invalid.
        self.assertFalse(move_node(
            lib, KIND_CATEGORY, wood, KIND_CATEGORY, sub
        ))
        self.assertEqual([c.name for c in wood.categories], before)


class TestLightburnImport(unittest.TestCase):
    LBRN_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<LightBurnLibrary>
  <Material name="Plywood">
    <Entry Thickness="3" Desc="Through cut" NoThickTitle="">
      <CutSetting type="Cut">
        <maxPower Value="80" />
        <speed Value="10" />
        <numPasses Value="1" />
      </CutSetting>
      <CutSetting type="Scan">
        <maxPower Value="40" />
        <speed Value="100" />
      </CutSetting>
    </Entry>
    <Entry Thickness="6" Desc="Heavy cut">
      <CutSetting type="Cut">
        <maxPower Value="100" />
        <speed Value="5" />
        <numPasses Value="2" />
      </CutSetting>
    </Entry>
  </Material>
  <Material name="Acrylic">
    <Entry Thickness="3" Desc="Clear">
      <CutSetting type="Cut">
        <maxPower Value="60" />
        <speed Value="15" />
      </CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""

    def _write_and_parse(self, content, ext=".clb"):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "sample" + ext)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return parse_lightburn_library(path), tmpdir
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    def test_basic_structure(self):
        lib, tmp = self._write_and_parse(self.LBRN_SAMPLE)
        try:
            self.assertEqual(lib.name, "sample")
            self.assertEqual(lib.power_unit, "percent")
            self.assertEqual(lib.speed_unit, "mm/s")
            self.assertEqual(len(lib.categories), 1)
            cat = lib.categories[0]
            self.assertEqual([m.name for m in cat.materials], ["Plywood", "Acrylic"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_thicknesses_and_ops(self):
        lib, tmp = self._write_and_parse(self.LBRN_SAMPLE)
        try:
            plywood = lib.categories[0].materials[0]
            self.assertEqual(len(plywood.thicknesses), 2)
            self.assertEqual(plywood.thicknesses[0].value, "3mm")
            self.assertEqual(plywood.thicknesses[1].value, "6mm")
            # Through cut at 3mm: maxPower 80 → PPI 800, speed 10, 1 pass.
            cut_op = plywood.thicknesses[0].operations[0]
            self.assertEqual(cut_op.type, "op engrave")
            self.assertEqual(cut_op.settings["power"], 800.0)
            self.assertEqual(cut_op.settings["speed"], 10.0)
            self.assertEqual(cut_op.settings["passes"], 1)
            # Scan op converts to op raster.
            scan_op = plywood.thicknesses[0].operations[1]
            self.assertEqual(scan_op.type, "op raster")
            self.assertEqual(scan_op.settings["power"], 400.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_root_raises(self):
        with self.assertRaises(ValueError):
            self._write_and_parse(
                "<?xml version='1.0'?><WrongRoot/>"
            )

    GROUPED_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<LightBurnLibrary DisplayName="100w">
  <Material name="100w">
    <Entry Thickness="-1.0000" Desc="Engrave" NoThickTitle="Acrylic">
      <CutSetting type="Scan">
        <maxPower Value="60"/>
        <speed Value="300"/>
      </CutSetting>
    </Entry>
    <Entry Thickness="-1.0000" Desc="Score" NoThickTitle="Acrylic">
      <CutSetting type="Cut">
        <maxPower Value="20"/>
        <speed Value="50"/>
      </CutSetting>
    </Entry>
    <Entry Thickness="-1.0000" Desc="Light Brown" NoThickTitle="Bamboo">
      <CutSetting type="Scan">
        <maxPower Value="12"/>
        <speed Value="800"/>
      </CutSetting>
    </Entry>
  </Material>
</LightBurnLibrary>
"""

    def test_grouped_layout_uses_no_thick_title_as_material(self):
        lib, tmp = self._write_and_parse(self.GROUPED_SAMPLE)
        try:
            # DisplayName lifts to the library + category name.
            self.assertEqual(lib.name, "100w")
            self.assertEqual(lib.categories[0].name, "100w")
            # Materials come from NoThickTitle, deduplicated.
            mat_names = [m.name for m in lib.categories[0].materials]
            self.assertEqual(sorted(mat_names), ["Acrylic", "Bamboo"])
            # Acrylic merged 2 entries → 2 ops, no thicknesses.
            acrylic = next(
                m for m in lib.categories[0].materials if m.name == "Acrylic"
            )
            self.assertEqual(len(acrylic.thicknesses), 0)
            self.assertEqual(len(acrylic.operations), 2)
            # Op labels come from Desc.
            labels = [o.label for o in acrylic.operations]
            self.assertIn("Engrave", labels)
            self.assertIn("Score", labels)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_grouped_layout_assigns_unique_ids_within_material(self):
        lib, tmp = self._write_and_parse(self.GROUPED_SAMPLE)
        try:
            acrylic = next(
                m for m in lib.categories[0].materials if m.name == "Acrylic"
            )
            ids = [o.id for o in acrylic.operations]
            self.assertEqual(len(ids), len(set(ids)))  # all unique
            for i in ids:
                self.assertTrue(i)  # non-empty
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_conventional_layout_still_works(self):
        # Original test data still parses correctly with the new code.
        lib, tmp = self._write_and_parse(self.LBRN_SAMPLE)
        try:
            plywood = next(
                m for m in lib.categories[0].materials if m.name == "Plywood"
            )
            self.assertEqual(
                [t.value for t in plywood.thicknesses], ["3mm", "6mm"]
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEzcadImport(unittest.TestCase):
    EZCAD_SAMPLE = """[F Steel]
markspeed=3000
powerratio=80
freq=20000
loop=2
qpulsewidth=200

[F Aluminum]
markspeed=2000
powerratio=60
freq=30000
jumpspeed=5000
"""

    def _write_and_parse(self, content, ext=".lib"):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "sample" + ext)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return parse_ezcad_library(path), tmpdir
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    def test_basic_structure(self):
        lib, tmp = self._write_and_parse(self.EZCAD_SAMPLE)
        try:
            self.assertEqual(lib.driver, "balor")
            self.assertEqual(lib.source, "fiber")
            self.assertEqual(lib.motion, "galvo")
            self.assertEqual(len(lib.categories), 1)
            mats = lib.categories[0].materials
            self.assertEqual([m.name for m in mats], ["Steel", "Aluminum"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_setting_conversions(self):
        lib, tmp = self._write_and_parse(self.EZCAD_SAMPLE)
        try:
            steel = lib.categories[0].materials[0].operations[0]
            self.assertEqual(steel.settings["speed"], 3000.0)
            self.assertEqual(steel.settings["power"], 800.0)  # 80 × 10
            self.assertEqual(steel.settings["frequency"], 20.0)  # Hz/1000
            self.assertEqual(steel.settings["passes"], 2)
            self.assertEqual(steel.settings["pulse_width"], 200.0)
            self.assertTrue(steel.settings["pulse_width_enabled"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ini_extension_also_accepted(self):
        lib, tmp = self._write_and_parse(self.EZCAD_SAMPLE, ext=".ini")
        try:
            self.assertEqual(len(lib.categories[0].materials), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLegacyOperationsCfgImport(unittest.TestCase):
    # Mirrors the real format MK uses for imported entries:
    #   material  = source/group name (e.g. "Internet", "Member Added")
    #   title     = actual material name (e.g. "Aluminum", "Copper Plated PCB")
    CFG_SAMPLE = """[import_0001 info]
title = Aluminum
material = Internet
thickness =
laser = 0
power = 50

[import_0001 000000]
type = op engrave
id = E1
power = 200
speed = 50

[import_0002 info]
title = Copper Plated PCB
material = Member Added
thickness =
laser = 0
power = 50

[import_0002 000000]
type = op cut
id = C1
power = 800
speed = 10
passes = 1

[import_0003 info]
title = Aluminum
material = Member Added
thickness =
laser = 0
power = 50

[import_0003 000000]
type = op engrave
id = E1
power = 600
speed = 1000
"""

    def _write_and_parse(self, content):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "operations.cfg")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return parse_legacy_operations_cfg(path), tmpdir
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    def test_category_from_material_field(self):
        lib, tmp = self._write_and_parse(self.CFG_SAMPLE)
        try:
            cat_names = sorted(c.name for c in lib.categories)
            # `material` field becomes the Category name.
            self.assertEqual(cat_names, ["Internet", "Member Added"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_material_name_from_title_field(self):
        lib, tmp = self._write_and_parse(self.CFG_SAMPLE)
        try:
            member = next(c for c in lib.categories if c.name == "Member Added")
            mat_names = sorted(m.name for m in member.materials)
            # `title` field becomes the MaterialEntry name.
            self.assertIn("Aluminum", mat_names)
            self.assertIn("Copper Plated PCB", mat_names)
            internet = next(c for c in lib.categories if c.name == "Internet")
            self.assertEqual([m.name for m in internet.materials], ["Aluminum"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_library_defaults_from_metadata(self):
        lib, tmp = self._write_and_parse(self.CFG_SAMPLE)
        try:
            self.assertEqual(lib.wattage, 50.0)
            self.assertEqual(lib.power_unit, "ppi")
            self.assertEqual(lib.speed_unit, "mm/s")
            # All entries use laser=0 (any), so driver stays empty.
            self.assertEqual(lib.driver, "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_consistent_laser_lifts_to_driver(self):
        cfg = """[A info]
title = Plywood
material = My Materials
laser = 1
power = 50

[A 000000]
type = op cut
power = 800
speed = 10

[B info]
title = MDF
material = My Materials
laser = 1
power = 50

[B 000000]
type = op cut
power = 900
speed = 8
"""
        lib, tmp = self._write_and_parse(cfg)
        try:
            self.assertEqual(lib.driver, "lhystudios")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_title_falls_back_to_prefix_and_uses_filename_category(self):
        # No title, no material field — should fall back gracefully.
        cfg = """[Plywood info]
thickness = 3mm
laser = 0

[Plywood 000000]
type = op cut
power = 800
speed = 10
"""
        lib, tmp = self._write_and_parse(cfg)
        try:
            self.assertEqual(len(lib.categories), 1)
            # category falls back to filename, material falls back to prefix.
            self.assertEqual(lib.categories[0].name, "operations")
            self.assertEqual(
                lib.categories[0].materials[0].name, "Plywood"
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestParseLibraryFileDispatch(unittest.TestCase):
    def test_dispatch_meerlib(self):
        lib = Library(name="X")
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.meerlib")
            save_library_to_file(lib, path)
            out = parse_library_file(path)
            self.assertEqual(out.name, "X")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dispatch_lbrn(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.clb")
            with open(path, "w") as f:
                f.write(TestLightburnImport.LBRN_SAMPLE)
            out = parse_library_file(path)
            self.assertEqual(out.power_unit, "percent")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dispatch_ezcad_lib(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.lib")
            with open(path, "w") as f:
                f.write(TestEzcadImport.EZCAD_SAMPLE)
            out = parse_library_file(path)
            self.assertEqual(out.driver, "balor")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dispatch_legacy_cfg(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "operations.cfg")
            with open(path, "w") as f:
                f.write(TestLegacyOperationsCfgImport.CFG_SAMPLE)
            out = parse_library_file(path)
            self.assertEqual(out.power_unit, "ppi")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMaterialLibraryService(unittest.TestCase):
    """Tests against the live matlib service using the bootstrap kernel."""

    def setUp(self):
        # CRITICAL: isolate to a temp directory via env var so tests never
        # touch the real user libraries at ~/.config/MeerK40t/libraries/.
        # This must be set *before* bootstrap, because the service reads it
        # in its __init__ at "register" lifecycle.
        self._tmpdir = tempfile.mkdtemp(prefix="matlib_test_")
        self._prev_env = os.environ.get("MEERK40T_MATLIB_DIR")
        os.environ["MEERK40T_MATLIB_DIR"] = self._tmpdir
        self.kernel = bootstrap.bootstrap(profile="MeerK40t_MatLibTest")
        self.svc = self.kernel.matlib
        # Sanity check: the service must have honored the env override.
        assert self.svc.libraries_dir == self._tmpdir, (
            f"Service ignored MEERK40T_MATLIB_DIR; refusing to run tests "
            f"that would touch {self.svc.libraries_dir}"
        )

    def tearDown(self):
        self.kernel()  # shutdown
        if self._prev_env is None:
            os.environ.pop("MEERK40T_MATLIB_DIR", None)
        else:
            os.environ["MEERK40T_MATLIB_DIR"] = self._prev_env
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_service_registered(self):
        self.assertIsInstance(self.svc, MaterialLibraryService)
        self.assertTrue(os.path.isdir(self.svc.libraries_dir))

    def test_create_and_delete_library_persists(self):
        lib = self.svc.create_library("Acme", description="d")
        self.assertEqual(lib.name, "Acme")
        self.assertTrue(os.path.isfile(lib.filepath))

        # Reload the service: file should be picked up.
        self.svc.load_all_libraries()
        self.assertIn("Acme", self.svc.library_names())

        self.assertTrue(self.svc.delete_library("Acme"))
        self.assertNotIn("Acme", self.svc.library_names())
        self.assertFalse(os.path.isfile(lib.filepath))

    def test_create_duplicate_raises(self):
        self.svc.create_library("Dup")
        with self.assertRaises(ValueError):
            self.svc.create_library("Dup")

    def test_rename_library(self):
        lib = self.svc.create_library("Old")
        old_path = lib.filepath
        self.assertTrue(self.svc.rename_library("Old", "New"))
        self.assertNotIn("Old", self.svc.library_names())
        self.assertIn("New", self.svc.library_names())
        new_lib = self.svc.get_library("New")
        self.assertEqual(new_lib.name, "New")
        self.assertTrue(os.path.isfile(new_lib.filepath))
        self.assertFalse(os.path.isfile(old_path))

    def test_rename_library_collision_raises(self):
        self.svc.create_library("A")
        self.svc.create_library("B")
        with self.assertRaises(ValueError):
            self.svc.rename_library("A", "B")

    def test_rename_library_unknown_raises(self):
        with self.assertRaises(ValueError):
            self.svc.rename_library("Nope", "Other")

    def test_rename_library_to_same_name_no_op(self):
        self.svc.create_library("Same")
        self.assertFalse(self.svc.rename_library("Same", "Same"))

    def test_round_trip_via_service(self):
        lib = self.svc.create_library("Round")
        lib.categories.append(Category(name="Wood", materials=[
            MaterialEntry(name="Plywood", thicknesses=[
                ThicknessEntry(value="3mm", operations=[
                    MaterialOperation(type="op cut", id="C1",
                                      settings={"power": 800, "speed": 12}),
                ])
            ])
        ]))
        self.svc.save_library(lib)
        self.svc.load_all_libraries()
        restored = self.svc.get_library("Round")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.categories[0].materials[0].name, "Plywood")
        self.assertEqual(
            restored.categories[0].materials[0].thicknesses[0].operations[0].settings["power"],
            800,
        )

    def test_merge_library_into_appends_new_categories(self):
        dest = self.svc.create_library("Dest")
        dest.categories.append(Category(name="Cat1"))
        self.svc.save_library(dest)
        src = Library(categories=[Category(name="Cat2", materials=[
            MaterialEntry(name="MatX"),
        ])])
        self.svc.merge_library_into(src, dest)
        cat_names = [c.name for c in dest.categories]
        self.assertIn("Cat1", cat_names)
        self.assertIn("Cat2", cat_names)
        cat2 = next(c for c in dest.categories if c.name == "Cat2")
        self.assertEqual(cat2.materials[0].name, "MatX")

    def test_merge_library_into_appends_into_matching_category(self):
        dest = self.svc.create_library("Dest")
        dest.categories.append(Category(name="Wood", materials=[
            MaterialEntry(name="Plywood"),
        ]))
        self.svc.save_library(dest)
        src = Library(categories=[Category(name="Wood", materials=[
            MaterialEntry(name="MDF"),
            MaterialEntry(name="Plywood"),  # collides with dest material name
        ])])
        self.svc.merge_library_into(src, dest)
        # Wood category gets MDF appended, and Plywood gets renamed.
        wood = next(c for c in dest.categories if c.name == "Wood")
        names = [m.name for m in wood.materials]
        self.assertIn("Plywood", names)
        self.assertIn("MDF", names)
        self.assertIn("Plywood (2)", names)

    def test_import_library_disambiguates_name(self):
        first = self.svc.create_library("Same")
        # Write a second file with the same library name to an external location.
        tmpdir = tempfile.mkdtemp()
        try:
            external = os.path.join(tmpdir, "external.meerlib")
            extra = Library(name="Same", description="external")
            save_library_to_file(extra, external)
            imported = self.svc.import_library_file(external)
            self.assertEqual(imported.name, "Same (2)")
            self.assertIn("Same", self.svc.library_names())
            self.assertIn("Same (2)", self.svc.library_names())
            self.assertEqual(first.name, "Same")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_console_matlib_lists(self):
        self.svc.create_library("Alpha")
        self.svc.create_library("Beta")
        captured = []
        chan = self.kernel.channel("console")
        chan.watch(captured.append)
        try:
            self.kernel.console("matlib\n")
        finally:
            chan.unwatch(captured.append)
        output = "\n".join(captured)
        self.assertIn("Alpha", output)
        self.assertIn("Beta", output)

    def test_console_matlib_new_and_delete(self):
        self.kernel.console("matlib new Gamma\n")
        self.assertIn("Gamma", self.svc.library_names())
        self.kernel.console("matlib delete Gamma\n")
        self.assertNotIn("Gamma", self.svc.library_names())

    def test_console_matlib_show(self):
        lib = self.svc.create_library("Demo")
        lib.categories.append(Category(name="Wood", materials=[
            MaterialEntry(name="Plywood", thicknesses=[
                ThicknessEntry(value="3mm")
            ])
        ]))
        captured = []
        chan = self.kernel.channel("console")
        chan.watch(captured.append)
        try:
            self.kernel.console("matlib show Demo\n")
        finally:
            chan.unwatch(captured.append)
        output = "\n".join(captured)
        self.assertIn("Demo", output)
        self.assertIn("Wood", output)
        self.assertIn("Plywood", output)
        self.assertIn("3mm", output)

    def test_console_matlib_export_and_import(self):
        lib = self.svc.create_library("Export")
        lib.categories.append(Category(name="Cat"))
        self.svc.save_library(lib)
        tmpdir = tempfile.mkdtemp()
        try:
            outpath = os.path.join(tmpdir, "exported.meerlib")
            self.kernel.console(f"matlib export Export {outpath}\n")
            self.assertTrue(os.path.isfile(outpath))
            # Delete the original then re-import.
            self.svc.delete_library("Export")
            self.assertNotIn("Export", self.svc.library_names())
            self.kernel.console(f"matlib import {outpath}\n")
            self.assertIn("Export", self.svc.library_names())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
