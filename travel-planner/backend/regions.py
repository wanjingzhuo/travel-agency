"""Single source of truth for the fixed set of regions the crew can research.

Shared by crew.py (builds researcher agents) and models.py (validates the
client's region selection) so the two can't drift apart.
"""

REGIONS = ["North America", "Europe", "Asia", "Oceania"]
