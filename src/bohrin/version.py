"""Single source of truth for the package and report-schema versions.

`__version__` is read by Hatchling (see ``[tool.hatch.version]``) and re-exported from
``bohrin``. ``REPORT_SCHEMA_VERSION`` is the frozen contract L2 depends on: it changes
only when the serialized :class:`~bohrin.report.model.Report` shape changes, following
SemVer independently of the package version.
"""

from __future__ import annotations

__version__ = "0.1.0"

# The versioned Report schema (docs/06_ROADMAP.md P0 DoD, docs/09 §3). "1.0" is the first
# *published* contract: it ships with 0.1.0, and nothing outside this repo ever consumed an
# earlier shape. From here it is frozen — bump MAJOR on a breaking change to the serialized
# Report, MINOR on additive fields.
REPORT_SCHEMA_VERSION = "1.0"
