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
__version__ = "1.2.0"

# "1.0" is the first published report contract. From here it is frozen — bump MAJOR on a
# breaking change to the serialized Report, MINOR on additive fields.
#
# 1.3 adds ``detail.rate`` — ``affected``, ``measured``, ``interval_95`` — to every probe
# that reports a proportion of tasks.
#
# 1.4 adds ``detail.tasks_scale_unknown`` to ``weak_oracle``: tasks excluded because their
# rubric paid more than its own declared full marks.
#
# 1.5 adds two keys, both additive: ``selection`` — ``mode`` (all / prefix / random) and
# ``seed`` — naming how the audited tasks were chosen from the taskset; and
# ``detail.candidates_in_accepted_form`` on ``weak_oracle``, counting payloads re-submitted
# in the answer format the verifier accepted for its own answer.
REPORT_SCHEMA_VERSION = "1.5"
