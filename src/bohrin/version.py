"""Single source of truth for the package and report-schema versions.

``__version__`` is read by Hatchling (see ``[tool.hatch.version]``) and re-exported from
``bohrin``. ``REPORT_SCHEMA_VERSION`` is the frozen contract that ``--json`` consumers
depend on: it changes only when the serialized :class:`~bohrin.report.model.Report` shape
changes, following SemVer independently of the package version.
"""

from __future__ import annotations

# The verifier auditor starts at 1.0.0. The 0.x line on PyPI belongs to a different tool
# (now published as `adduct`) and is yanked; the major bump makes the discontinuity read
# as a break rather than an upgrade.
__version__ = "1.0.0.dev0"

# "1.0" is the first published report contract. From here it is frozen — bump MAJOR on a
# breaking change to the serialized Report, MINOR on additive fields.
REPORT_SCHEMA_VERSION = "1.0"
