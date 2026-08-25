"""The detector contract — Stage ④ (docs/02 §4).

A detector is a pure, independent function of a read-only context: it reads the shared
``DatasetProfile`` + sampled episodes and returns typed ``Finding`` objects. It never
mutates shared state and never depends on another detector's output — which is what lets
detectors run in parallel and be added or removed freely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.calibrate.corpus import CalibrationCorpus
from bohrin.ir.episode import Episode
from bohrin.ir.schema import DatasetSchema, Family, PolicyProfile
from bohrin.report.model import Finding

if TYPE_CHECKING:
    from bohrin.config import ScanConfig
    from bohrin.profile.dataset_profile import DatasetProfile


@dataclass(frozen=True, slots=True)
class Requirements:
    """What a detector needs present before it is worth running (``applicable`` gate)."""

    needs_proprio: bool = False
    needs_images: bool = False
    needs_timestamps: bool = False
    needs_policy: bool = False
    min_episodes: int = 1


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """The read-only inputs handed to every detector's ``run`` (docs/02 §4)."""

    profile: DatasetProfile
    schema: DatasetSchema
    episodes: Sequence[Episode]
    config: ScanConfig
    rng: np.random.Generator
    policy: PolicyProfile | None = None
    #: Reference non-conformity scores from known-good data. Empty unless the user pointed
    #: ``--calibration`` at a corpus; an empty corpus means every gate self-calibrates
    #: (:mod:`bohrin.calibrate.gate`).
    corpus: CalibrationCorpus = field(default_factory=CalibrationCorpus.empty)


class Detector(ABC):
    """Base class for every check. Register via the ``bohrin.detectors`` entry-point group.

    The same class works as a built-in or a third-party plugin — there is no privileged
    path (docs/02 §10). ``run`` is the only required method.
    """

    #: Stable dotted id, e.g. ``"stats.dead_dimension"``. Set on the subclass.
    id: str = ""
    #: The family this check belongs to (docs/02 §4.2). Set on the subclass.
    family: Family = Family.INTEGRITY
    #: Preconditions checked cheaply before ``run`` (see :meth:`applicable`).
    #: A frozen, shared default instance — safe because ``Requirements`` is immutable.
    requires: Requirements = Requirements()
    #: One-line description surfaced by ``bohrin explain``.
    description: str = ""

    def applicable(self, profile: DatasetProfile, policy: PolicyProfile | None) -> bool:
        """Whether this detector should run at all. Override for family-specific gating.

        The default enforces :attr:`requires` against the profile so a vision detector
        skips a proprio-only dataset and a policy↔data detector skips when no checkpoint
        is given — no wasted work, no false "N/A" noise (docs/02 §4.1).
        """
        req = self.requires
        if profile.n_episodes < req.min_episodes:
            return False
        if req.needs_proprio and not profile.has_proprio:
            return False
        if req.needs_images and not profile.has_images:
            return False
        if req.needs_timestamps and not profile.has_timestamps:
            return False
        return not (req.needs_policy and policy is None)

    @abstractmethod
    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        """Analyze the context and yield typed findings."""
        raise NotImplementedError

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """The per-unit non-conformity scores this detector gates on, or ``None``.

        Overriding this makes a detector **calibratable**: ``bohrin calibrate`` collects these
        scores over known-good datasets into a reference band, and the gate then selects at
        FDR ``--fpr`` against it instead of using a hand-picked robust-z constant
        (:mod:`bohrin.calibrate.gate`).

        The contract is narrow and load-bearing: return the *same* quantity, computed the
        *same* way, that :meth:`run` gates on — higher meaning more anomalous. A band built
        from a different quantity than the one being tested would be an invalid calibration
        set, and the resulting p-values would be meaningless rather than merely imprecise.
        ``tests/test_calibration_gate.py`` asserts this correspondence per detector.

        Returning ``None`` (the default) means "not threshold-gated" — a detector whose
        decision is a hard structural fact (a NaN is present, a dimension is dead) has no
        score distribution to calibrate and needs none.
        """
        return None

    def explain(self) -> str:
        """Human explanation for ``bohrin explain <id>``."""
        return self.description or f"{self.id}: no description provided."
