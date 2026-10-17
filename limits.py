"""Shared resource ceilings for high-resolution manga pages.

Keep page acceptance separate from bounded region/tile/raster work.  The folder
runner, cleanup planner and lettering code must agree on these contracts so a
page accepted by one layer is not rejected later for a stale legacy limit.
"""

RESOURCE_CONTRACT_VERSION = 2
LEGACY_PAGE_PIXELS = 16 * 1024 * 1024
MAX_SOURCE_PIXELS = 64 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024 * 1024

# A detected text region may be substantially larger on scanned/high-DPI books
# than on the original 1600px development fixtures.  This is still bounded well
# below the whole-page ceiling.
MAX_REGION_PIXELS = 16 * 1024 * 1024

# Supersampled glyph rasters are temporary allocations.  Keep a separate cap so
# accepting a 64 MP source page never implies allocating an arbitrarily large
# supersampled lettering canvas.
MAX_RASTER_PIXELS = 32 * 1024 * 1024

# Sum of candidate typography rectangles prepared for one page.  This bounds
# repeated search work while allowing several large high-DPI text blocks.
MAX_TYPOGRAPHY_PIXELS = 32 * 1024 * 1024
