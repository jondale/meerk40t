"""
Self-contained codec and generator for BJJCZ/JCZ ``.cor`` lens-correction files.

The wizard side of the cor_generator feature uses this module to:
  1. Convert 9-point/12-segment user measurements into a 65x65 (dx, dy) table.
  2. Write the table to disk in the ``JCZ_COR_2_1`` (CORV2) format that the
     LMC controller reads at ``init_laser`` time via the existing
     ``balormk.controller._read_correction_file`` path.

The codec is intentionally independent of the wx GUI, the balor controller
class, and the BalorDevice service so it can be unit-tested in isolation and
imported in ``--no-gui`` mode without dragging in optional dependencies.

File format reference (CORV2 / ``JCZ_COR_2_1``):
    offset  size   meaning
    0x00    0x16   label, UTF-16LE encoded "JCZ_COR_2_1" padded with zero bytes
    0x16    0x06   reserved/unknown (zero-filled when writing)
    0x1C    0x08   float64 little-endian, galvo_units_per_mm scale
    0x24    ...    65x65 entries of (int32 dx, int32 dy) little-endian

Each (dx, dy) is a signed delta in galvo units (0..0xFFFF == full field).
The controller's wire protocol later remaps these to a sign-magnitude uint16
when streaming via WriteCorLine; that remap is the controller's concern, not
the file's.
"""

import os
import struct

GRID_N = 65
GALVO_MAX = 0xFFFF
COR_LABEL_V2 = "JCZ_COR_2_1"
COR_LABEL_V1 = "LMC1COR_1.0"


def write_cor_file(path: str, table, lens_size_mm: float) -> None:
    """
    Write a CORV2 ``.cor`` file.

    ``table`` is an iterable of GRID_N*GRID_N (dx, dy) signed integer pairs in
    row-major order (j=0..64 outer, k=0..64 inner — same order the reader
    consumes). Values are stored as little-endian int32.

    ``lens_size_mm`` is the field size in millimetres; the embedded scale is
    ``GALVO_MAX / lens_size_mm`` (galvo units per mm), matching what EzCad's
    CorFile2 writes and what ``controller.get_scale_from_correction_file``
    reads back.
    """
    cells = list(table)
    if len(cells) != GRID_N * GRID_N:
        raise ValueError(
            f"table must have exactly {GRID_N * GRID_N} entries, got {len(cells)}"
        )
    label = COR_LABEL_V2.encode("utf-16-le")
    label = label.ljust(0x16, b"\x00")[:0x16]
    reserved = b"\x00" * 6
    scale = GALVO_MAX / float(lens_size_mm)
    with open(path, "wb") as f:
        f.write(label)
        f.write(reserved)
        f.write(struct.pack("<d", scale))
        for dx, dy in cells:
            f.write(struct.pack("<ii", int(dx), int(dy)))


def read_cor_file(path: str):
    """
    Read a ``.cor`` file produced by this module (or any compatible writer).

    Returns ``(version, scale, table)`` where ``table`` is a list of
    ``(dx, dy)`` *signed* integer pairs in row-major order. Unlike the
    controller's ``_read_correction_file``, this does *not* apply the
    sign-magnitude remap to uint16 — callers get the raw signed deltas as
    stored on disk, which is what generators want for round-tripping.
    """
    with open(path, "rb") as f:
        raw_label = f.read(0x16)
        try:
            label = raw_label.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            label = raw_label.decode("utf-8", errors="ignore").rstrip("\x00")
        if label.startswith(COR_LABEL_V1):
            # CORV1: 504-byte header (63 doubles), then 65*65 (float64, float64).
            header = struct.unpack("<63d", f.read(0x1F8))
            scale = header[43]
            table = []
            for _j in range(GRID_N):
                for _k in range(GRID_N):
                    dx, dy = struct.unpack("<dd", f.read(16))
                    table.append((int(round(dx)), int(round(dy))))
            return "V1", scale, table
        # CORV2 (default): 6 reserved + double scale, then 65*65 (int32, int32).
        f.read(6)
        (scale,) = struct.unpack("<d", f.read(8))
        table = []
        for _j in range(GRID_N):
            for _k in range(GRID_N):
                dx, dy = struct.unpack("<ii", f.read(8))
                table.append((dx, dy))
        return "V2", scale, table


def generate_identity_table():
    """Return a 65x65 all-zero (no-correction) table."""
    return [(0, 0)] * (GRID_N * GRID_N)


def generate_table_from_9_point(
    measurements, lens_size_mm: float, nominal_segment_mm=None
):
    """
    Build a 65x65 correction table from 9 anchor measurements.

    ``measurements`` is a dict keyed ``(ai, aj)`` with ``ai, aj`` in ``{-1, 0, 1}``
    representing the 3x3 anchor grid (``(-1,-1)`` = bottom-left, ``(0,0)`` =
    center, ``(1,1)`` = top-right). Each value is a tuple ``(mx, my)``: the
    measured horizontal and vertical distance, in millimetres, from the
    *previous* anchor along the row / column to this anchor.

    ``lens_size_mm`` is the full galvo field width in mm (sets the
    galvo-units-per-mm conversion used when packing the table).

    ``nominal_segment_mm`` is the expected un-distorted length of one half-edge
    segment in the burn pattern. If omitted, defaults to ``lens_size_mm / 2``
    (assumes the burn pattern spans the entire half-field). Callers that burn
    a smaller pattern for safety margin should pass the actual physical
    spacing of the anchors.

    A measurement equal to ``nominal_segment_mm`` means no distortion; larger
    means the field is locally stretched in that direction.

    Returns a list of GRID_N*GRID_N (dx, dy) signed integer pairs in row-major
    order. Bilinear interpolation fills the 65x65 grid between the 3x3 anchor
    offsets. Center anchor is pinned at (0, 0); each non-center anchor's
    offset is derived by accumulating the per-segment scale error along the
    row or column.

    The algorithm intentionally mirrors EzCad's 9-point UX: simple per-segment
    scale errors propagated to anchor offsets, then bilinear interpolation to
    fill. It does not model true non-linear pincushion — for that, a denser
    grid or a polynomial fit would be needed.
    """
    nominal = (
        float(nominal_segment_mm)
        if nominal_segment_mm is not None
        else float(lens_size_mm) / 2.0
    )
    units_per_mm = GALVO_MAX / float(lens_size_mm)

    # Build a 3x3 array of anchor offsets in galvo units. The center is fixed
    # at (0, 0). For each non-center anchor, walk from the center along the
    # row (for ai != 0) and column (for aj != 0) accumulating the displacement
    # error of each segment.
    anchor_offsets = {}
    for ai in (-1, 0, 1):
        for aj in (-1, 0, 1):
            anchor_offsets[(ai, aj)] = [0.0, 0.0]

    def seg_error_mm(measured_mm):
        # Positive means segment was longer than nominal -> the outer endpoint
        # sits *further* from the inner endpoint than expected.
        return float(measured_mm) - nominal

    # Walk horizontally from center along each row of the 3x3.
    for aj in (-1, 0, 1):
        # Right half: 0 -> +1
        m = measurements.get((1, aj), (nominal, nominal))[0]
        anchor_offsets[(1, aj)][0] = seg_error_mm(m) * units_per_mm
        # Left half: 0 -> -1
        m = measurements.get((-1, aj), (nominal, nominal))[0]
        anchor_offsets[(-1, aj)][0] = -seg_error_mm(m) * units_per_mm

    # Walk vertically from center along each column of the 3x3.
    for ai in (-1, 0, 1):
        # Top half: 0 -> +1
        m = measurements.get((ai, 1), (nominal, nominal))[1]
        anchor_offsets[(ai, 1)][1] = seg_error_mm(m) * units_per_mm
        # Bottom half: 0 -> -1
        m = measurements.get((ai, -1), (nominal, nominal))[1]
        anchor_offsets[(ai, -1)][1] = -seg_error_mm(m) * units_per_mm

    # Pack into 3x3 lists indexed [row][col] (row = aj+1, col = ai+1).
    anchor_dx = [[0.0] * 3 for _ in range(3)]
    anchor_dy = [[0.0] * 3 for _ in range(3)]
    for ai in (-1, 0, 1):
        for aj in (-1, 0, 1):
            dx, dy = anchor_offsets[(ai, aj)]
            anchor_dx[aj + 1][ai + 1] = dx
            anchor_dy[aj + 1][ai + 1] = dy

    # Map 65x65 grid indices to (u, v) in [0, 2] -> bilinear over anchor_dx/dy.
    # Outer loop j = row = y (matches controller's _read_int_correction_file order).
    table = []
    for j in range(GRID_N):
        v = (j / (GRID_N - 1)) * 2.0  # 0..2 spanning aj index
        v0 = int(min(v, 1.0))         # 0 for j in lower half, 1 for upper half
        vt = v - v0                   # 0..1 within that half
        for k in range(GRID_N):
            u = (k / (GRID_N - 1)) * 2.0
            u0 = int(min(u, 1.0))
            ut = u - u0
            dx = (
                (1 - ut) * (1 - vt) * anchor_dx[v0][u0]
                + ut * (1 - vt) * anchor_dx[v0][u0 + 1]
                + (1 - ut) * vt * anchor_dx[v0 + 1][u0]
                + ut * vt * anchor_dx[v0 + 1][u0 + 1]
            )
            dy = (
                (1 - ut) * (1 - vt) * anchor_dy[v0][u0]
                + ut * (1 - vt) * anchor_dy[v0][u0 + 1]
                + (1 - ut) * vt * anchor_dy[v0 + 1][u0]
                + ut * vt * anchor_dy[v0 + 1][u0 + 1]
            )
            table.append((int(round(dx)), int(round(dy))))
    return table


def default_cor_directory(settings_path: str) -> str:
    """Return the standard wizard-output directory, creating it on demand."""
    path = os.path.join(settings_path, "cor")
    os.makedirs(path, exist_ok=True)
    return path
