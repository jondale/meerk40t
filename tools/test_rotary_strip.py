"""
Local test for rotary strip splitting logic.

Simulates the balor pipeline: loads meerk40t.png, creates a RasterCut
with galvo-realistic parameters, runs it through _split_raster, and
verifies the output makes sense.

Run: python test_rotary_strip.py
"""

from math import pi
from PIL import Image

from meerk40t.core.cutcode.rastercut import RasterCut
from meerk40t.core.cutcode.rotaryadvancecut import RotaryAdvanceCut
from meerk40t.core.cutcode.cutcode import CutCode
from meerk40t.core.cutplan import CutPlan
from meerk40t.core.units import Length, UNITS_PER_MM, UNITS_PER_INCH


def simulate_balor_view(lens_size_mm):
    """Compute balor view parameters for a given lens size."""
    unit_size = lens_size_mm * UNITS_PER_MM  # Tats
    galvo_range = 0xFFFF
    native_scale = unit_size / galvo_range  # Tats per galvo unit
    device_units_per_mm = UNITS_PER_MM / native_scale
    return native_scale, device_units_per_mm


def simulate_dpi_to_steps(lens_size_mm, dpi):
    """Simulate View.dpi_to_steps for balor."""
    unit_size = lens_size_mm * UNITS_PER_MM
    galvo_range = 0xFFFF
    native_scale = unit_size / galvo_range
    # View.reset() scales by 1/native_scale
    # oneinch in device units = UNITS_PER_INCH / native_scale
    oneinch_device = UNITS_PER_INCH / native_scale
    step = oneinch_device / dpi
    return step, step  # symmetric for galvo


def test_strip_splitting():
    print("=" * 60)
    print("Rotary Strip Splitting Test")
    print("=" * 60)

    # --- Parameters (simulate a typical balor setup) ---
    lens_size_mm = 110.0
    raster_dpi = 500  # typical raster DPI
    split_size_mm = 1.0
    overlap_mm = 0.05

    # Rotary params
    steps_per_rotation = 12800
    object_diameter_mm = 50.0
    circumference_mm = object_diameter_mm * pi

    native_scale, device_units_per_mm = simulate_balor_view(lens_size_mm)
    step_x, step_y = simulate_dpi_to_steps(lens_size_mm, raster_dpi)

    print(f"\n--- Device Parameters ---")
    print(f"Lens size: {lens_size_mm}mm")
    print(f"Raster DPI: {raster_dpi}")
    print(f"Native scale: {native_scale:.6f} Tats/galvo_unit")
    print(f"Device units/mm: {device_units_per_mm:.4f}")
    print(f"Step X: {step_x:.6f} device_units/pixel")
    print(f"Step Y: {step_y:.6f} device_units/pixel")
    print(f"1mm in device units: {device_units_per_mm:.4f}")
    print(f"1mm in pixels at {raster_dpi} DPI: {device_units_per_mm / step_y:.2f}")

    # --- Rotary Parameters ---
    steps_per_split = int(round(split_size_mm / circumference_mm * steps_per_rotation))
    print(f"\n--- Rotary Parameters ---")
    print(f"Object diameter: {object_diameter_mm}mm")
    print(f"Circumference: {circumference_mm:.2f}mm")
    print(f"Steps/rotation: {steps_per_rotation}")
    print(f"Steps/split ({split_size_mm}mm): {steps_per_split}")

    # --- Load image and create RasterCut ---
    img = Image.open("images/meerk40t.png").convert("L")
    width_px, height_px = img.size
    print(f"\n--- Image ---")
    print(f"Size: {width_px}x{height_px} px")
    print(f"Image width in mm: {width_px * step_x / device_units_per_mm:.2f}mm")
    print(f"Image height in mm: {height_px * step_y / device_units_per_mm:.2f}mm")

    # Place image at center of galvo field (like MeerK40t would)
    offset_x = 0x8000 - (width_px * step_x) / 2
    offset_y = 0x8000 - (height_px * step_y) / 2
    print(f"Offset: ({offset_x:.1f}, {offset_y:.1f})")

    raster_cut = RasterCut(
        image=img,
        offset_x=offset_x,
        offset_y=offset_y,
        step_x=step_x,
        step_y=step_y,
        inverted=False,
        bidirectional=True,
        horizontal=True,
    )

    # --- Test split along Y (scan_axis=Y) ---
    print(f"\n{'=' * 60}")
    print(f"Test: Split along Y (scan_axis=Y, use_x=False)")
    print(f"{'=' * 60}")

    class FakeChannel:
        def __call__(self, msg):
            print(msg)

    strips_y = CutPlan._split_raster(
        raster_cut, split_size_mm, overlap_mm,
        use_x=False, device_units_per_mm=device_units_per_mm,
        channel=FakeChannel()
    )

    print(f"\nResult: {len(strips_y)} strips")
    for i, s in enumerate(strips_y):
        w, h = s.image.size
        strip_mm = h * abs(s.step_y) / device_units_per_mm
        print(
            f"  [{i}] {w}x{h}px, "
            f"offset=({s.offset_x:.1f},{s.offset_y:.1f}), "
            f"~{strip_mm:.3f}mm tall"
        )
    print()

    # Verify all offsets are identical
    offsets_y = set((s.offset_x, s.offset_y) for s in strips_y)
    if len(offsets_y) == 1:
        print("PASS: All strips have identical offset (same galvo position)")
    else:
        print(f"FAIL: Strips have {len(offsets_y)} different offsets!")
        for o in offsets_y:
            print(f"  {o}")

    # Verify strip pixel heights sum correctly
    total_px = sum(s.image.size[1] for s in strips_y)
    # Account for overlap
    split_device = split_size_mm * device_units_per_mm
    overlap_device = overlap_mm * device_units_per_mm
    split_px = int(round(abs(split_device / step_y)))
    overlap_px = int(round(abs(overlap_device / step_y)))
    expected_total = height_px + overlap_px * (len(strips_y) - 1)
    print(f"Total strip pixels: {total_px}, expected ~{expected_total} (orig {height_px} + {len(strips_y)-1} overlaps of {overlap_px}px)")

    # --- Test split along X (scan_axis=X, use_x=True) ---
    print(f"\n{'=' * 60}")
    print(f"Test: Split along X (scan_axis=X, use_x=True)")
    print(f"{'=' * 60}")

    strips_x = CutPlan._split_raster(
        raster_cut, split_size_mm, overlap_mm,
        use_x=True, device_units_per_mm=device_units_per_mm,
        channel=FakeChannel()
    )

    print(f"\nResult: {len(strips_x)} strips")
    for i, s in enumerate(strips_x):
        w, h = s.image.size
        strip_mm = w * abs(s.step_x) / device_units_per_mm
        print(
            f"  [{i}] {w}x{h}px, "
            f"offset=({s.offset_x:.1f},{s.offset_y:.1f}), "
            f"~{strip_mm:.3f}mm wide"
        )

    # --- Test full CutCode with advances ---
    print(f"\n{'=' * 60}")
    print(f"Test: Full CutCode assembly with RotaryAdvanceCut")
    print(f"{'=' * 60}")

    cutcode = CutCode()
    cutcode.append(raster_cut)

    # Simulate what _split_cutcode_for_rotary does
    result = CutCode()
    strips = strips_y  # use Y split
    for i, strip in enumerate(strips):
        result.append(strip)
        if i < len(strips) - 1:
            result.append(RotaryAdvanceCut(steps_per_split))

    print(f"Items in result CutCode: {len(result)}")
    print(f"Raster strips: {sum(1 for c in result if isinstance(c, RasterCut))}")
    print(f"Rotary advances: {sum(1 for c in result if isinstance(c, RotaryAdvanceCut))}")

    # Verify advance step count
    total_advance_steps = sum(
        c.steps for c in result if isinstance(c, RotaryAdvanceCut)
    )
    total_advance_mm = total_advance_steps / steps_per_rotation * circumference_mm
    print(f"Total rotary advance: {total_advance_steps} steps = {total_advance_mm:.2f}mm")
    expected_advance_mm = split_size_mm * (len(strips) - 1)
    print(f"Expected advance: {expected_advance_mm:.2f}mm ({len(strips)-1} splits of {split_size_mm}mm)")

    # Image dimensions check
    img_height_mm = height_px * abs(step_y) / device_units_per_mm
    print(f"\nImage height: {img_height_mm:.2f}mm")
    print(f"Total rotary travel: {total_advance_mm:.2f}mm")
    print(f"Difference: {abs(img_height_mm - total_advance_mm):.4f}mm")
    if abs(img_height_mm - total_advance_mm - split_size_mm) < 0.1:
        print("PASS: Rotary travel + one split ≈ image height (expected)")
    elif abs(img_height_mm - total_advance_mm) < 0.5:
        print("PASS: Rotary travel ≈ image height")
    else:
        print(f"WARNING: Mismatch between image height and rotary travel")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("Summary of key numbers to compare with live machine:")
    print(f"{'=' * 60}")
    print(f"  1mm = {device_units_per_mm:.4f} device units")
    print(f"  1 pixel = {step_y:.6f} device units ({step_y/device_units_per_mm*1000:.3f} microns)")
    print(f"  split_px = {split_px} pixels per strip")
    print(f"  overlap_px = {overlap_px} pixels overlap")
    print(f"  {len(strips_y)} strips for a {img_height_mm:.2f}mm image")
    print(f"  {steps_per_split} motor steps per advance")
    print(f"  Each strip covers {split_px * abs(step_y) / device_units_per_mm:.4f}mm")


def test_visual_strips():
    """Save strip images and a reassembled composite for visual verification."""
    import os

    lens_size_mm = 110.0
    raster_dpi = 500
    split_size_mm = 1.0
    overlap_mm = 0.05

    native_scale, device_units_per_mm = simulate_balor_view(lens_size_mm)
    step_x, step_y = simulate_dpi_to_steps(lens_size_mm, raster_dpi)

    img = Image.open("images/meerk40t.png").convert("L")
    width_px, height_px = img.size
    offset_x = 0x8000 - (width_px * step_x) / 2
    offset_y = 0x8000 - (height_px * step_y) / 2

    raster_cut = RasterCut(
        image=img, offset_x=offset_x, offset_y=offset_y,
        step_x=step_x, step_y=step_y,
    )

    # Test both axes
    for axis_name, use_x in [("Y", False), ("X", True)]:
        strips = CutPlan._split_raster(
            raster_cut, split_size_mm, overlap_mm,
            use_x=use_x, device_units_per_mm=device_units_per_mm,
        )

        split_device = split_size_mm * device_units_per_mm
        split_px = int(round(abs(split_device / step_y)))

        # Reassemble strips (without overlap) to see if image reconstructs
        if use_x:
            composite = Image.new("L", (split_px * len(strips), height_px), 128)
            for i, s in enumerate(strips):
                w, h = s.image.size
                # Only paste split_px width (exclude overlap)
                crop = s.image.crop((0, 0, min(split_px, w), h))
                composite.paste(crop, (i * split_px, 0))
        else:
            composite = Image.new("L", (width_px, split_px * len(strips)), 128)
            for i, s in enumerate(strips):
                w, h = s.image.size
                crop = s.image.crop((0, 0, w, min(split_px, h)))
                composite.paste(crop, (0, i * split_px))

        out_name = f"noraster-test-axis{axis_name}.png"
        composite.save(out_name)
        print(f"Saved reassembled composite: {out_name} ({composite.size[0]}x{composite.size[1]})")

        # Also save first few strips individually
        outdir = f"strips_axis{axis_name}"
        os.makedirs(outdir, exist_ok=True)
        for i, s in enumerate(strips[:5]):
            s.image.save(f"{outdir}/strip_{i:03d}.png")
        print(f"Saved first 5 strip images to {outdir}/")


if __name__ == "__main__":
    test_strip_splitting()
    print()
    test_visual_strips()
