"""Fixed runtime field layouts; offline audits own accuracy certification.

``tools.audit_fields`` checks the retained scalar corpus and reports lower-grid
failure witnesses. Color coefficients, compact Adaptance and Web toes use the
authorized 0.05-code HDR worsening policy; their scalar/local precision remains
diagnostic. The retained safety and final-output checks still apply. Adaptance
always uses its single compact field, including stronger calibrated gains.
Receipts remain external evidence, not a claim over the continuous domain.
Runtime never chooses a resolution from authored values.
"""
from types import MappingProxyType

LAYOUT_SCHEMA = 5
TONE_CELLS = 256
FIELD_LATTICE = (2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288)
WEB_TOE_CANDIDATES = tuple(range(256, 2049, 256))
FIELD_CELLS = MappingProxyType({
    'Color coefficients': 8192,
    'Web parameters': 4096,
    'Web toes': 1536,
    'Adaptance parameters': 3072,
})


def supported_cells(name):
    """Supported offline grids for one role; small grids belong only to toes."""
    if name not in FIELD_CELLS:
        raise ValueError('Unknown Color field role: '+name)
    if name == 'Web toes':
        return tuple(sorted(set(WEB_TOE_CANDIDATES + FIELD_LATTICE)))
    if name == 'Adaptance parameters':
        return tuple(sorted((3072, *FIELD_LATTICE)))
    return FIELD_LATTICE


def packed_shape(name, semantic_rows):
    """Return the invariant RGBA image shape for a runtime Color field."""
    cells = FIELD_CELLS[name]
    segment = min(cells, 8192)
    rows = semantic_rows*(cells//segment)
    return (1 << (rows-1).bit_length(), segment+1, 4)
