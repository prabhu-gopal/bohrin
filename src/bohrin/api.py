"""The seam: the one module a plugin or an extension imports.

Everything a plugin needs is re-exported here, and nothing else in ``bohrin`` is promised to stay
where it is. :data:`PLUGIN_API` names the version of this seam: it changes only when the seam
breaks (a name removed or a signature changed incompatibly), never when one is added. A plugin
class may declare ``plugin_api = PLUGIN_API``; one written for another version is skipped, with a
warning, rather than failing in the middle of a run.

Plugins register under the entry-point groups in :data:`GROUPS`, the same way the built-in
operators, rewritings and commands do:

``bohrin.mutators``
    :class:`MutationOperator` subclasses: submissions a correct grader must reject.
``bohrin.relations``
    :class:`Relation` subclasses: certified rewritings a correct grader must accept.
``bohrin.commands``
    :class:`Command` subclasses: subcommands of ``bohrin``.
``bohrin.adapters``, ``bohrin.probes``, ``bohrin.renderers``
    Reserved for extensions that load environments, run checks that report a
    :class:`ProbeResult`, and render reports. This library reads none of them: it never calls a
    grader.

A name in a group belongs to its first owner: when two packages register the same one, this
package's is kept and the other is skipped with a warning.
"""

from __future__ import annotations

from bohrin._plugins import ADAPTERS, COMMANDS, GROUPS, MUTATORS, PLUGIN_API, PROBES, RELATIONS, RENDERERS
from bohrin.command import CANNOT_RUN, CLEAN, FINDINGS, NEEDS_SIGN_IN, OUT_OF_CREDITS, USAGE, Command
from bohrin.conformance import check as check_conformance
from bohrin.conformance import read_results as read_conformance_results
from bohrin.decisions import Decision, format_decisions, read_decisions
from bohrin.decisions import active as active_decisions
from bohrin.evidence.finding import (
    DifferentiatingInput,
    DifferentiatingObservation,
    Finding,
    Reproduction,
    Run,
    Scored,
    Submission,
    finding_id,
)
from bohrin.evidence.reproduction import ReproductionResult, check_script, judge, parse_result
from bohrin.ir.evidence import (
    AnswerInPrompt,
    BaselineFailure,
    Exploit,
    Flake,
    GroundTruthRejected,
    HarnessDisruption,
    Unverified,
)
from bohrin.ir.evidence import Finding as CheckFinding
from bohrin.ir.result import ProbeResult, ProbeStatus
from bohrin.ir.task import Candidate, Ground, Payload, Provenance, Shape, Source, Task, Verdict, Workspace
from bohrin.mutate import discover as discover_operators
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.battery import Battery, battery
from bohrin.registry import read_record
from bohrin.relations import BASELINE, Control, Relation, positive_controls
from bohrin.relations import discover as discover_relations
from bohrin.report.sarif import to_sarif
from bohrin.scoring.coverage import BATTERY_VERSION, CATEGORIES, Attempt, CoverageScore, coverage_score
from bohrin.scoring.gap import GapScore, verification_gap
from bohrin.scoring.interval import wilson_interval
from bohrin.scoring.scorecard import Acceptance, ControlAttempt, Scorecard, scorecard
from bohrin.spec import probe_for, probes, weakness_list, weakness_of

__all__ = [
    "ADAPTERS",
    "BASELINE",
    "BATTERY_VERSION",
    "CANNOT_RUN",
    "CATEGORIES",
    "CLEAN",
    "COMMANDS",
    "FINDINGS",
    "GROUPS",
    "MUTATORS",
    "NEEDS_SIGN_IN",
    "OUT_OF_CREDITS",
    "PLUGIN_API",
    "PROBES",
    "RELATIONS",
    "RENDERERS",
    "USAGE",
    "Acceptance",
    "AnswerInPrompt",
    "Attempt",
    "BaselineFailure",
    "Battery",
    "Candidate",
    "CheckFinding",
    "Command",
    "Control",
    "ControlAttempt",
    "CoverageScore",
    "Decision",
    "DifferentiatingInput",
    "DifferentiatingObservation",
    "Exploit",
    "Finding",
    "Flake",
    "GapScore",
    "Ground",
    "GroundTruthRejected",
    "HarnessDisruption",
    "MutationOperator",
    "Payload",
    "ProbeResult",
    "ProbeStatus",
    "Provenance",
    "Relation",
    "Reproduction",
    "ReproductionResult",
    "Run",
    "Scorecard",
    "Scored",
    "Shape",
    "Source",
    "Submission",
    "Task",
    "Unverified",
    "Verdict",
    "Workspace",
    "active_decisions",
    "battery",
    "check_conformance",
    "check_script",
    "coverage_score",
    "discover_operators",
    "discover_relations",
    "finding_id",
    "format_decisions",
    "judge",
    "parse_result",
    "positive_controls",
    "probe_for",
    "probes",
    "read_conformance_results",
    "read_decisions",
    "read_record",
    "scorecard",
    "to_sarif",
    "verification_gap",
    "weakness_list",
    "weakness_of",
    "wilson_interval",
]
