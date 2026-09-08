"""The rejection half of the gap.

The governing constraint on this probe is unusual: it reports findings that are
deliberately **not scored**. Every test here exists to keep that true, because the moment a
rejection contributes to the Verification Gap, a verifier enforcing a documented output
format becomes indistinguishable from a broken one — and Bohrin accuses the wrong party.
"""

from __future__ import annotations

import pytest

from _fixtures import LENIENT_CORRECT, REFERENCE, exact_match_source, lenient_source, unjudged_source
from bohrin.config import ScanConfig
from bohrin.ir.evidence import GroundTruthRejected
from bohrin.probes import registry as probe_registry
from bohrin.probes.base import ProbeStatus
from bohrin.probes.ground_truth_rejected import GroundTruthRejectedProbe
from bohrin.scoring.gap import verification_gap

CONFIG = ScanConfig(unsafe_local=True)


async def test_a_verifier_that_accepts_its_own_answer_produces_nothing() -> None:
    """The counterweight, and the reason the rest is not vacuous."""
    result = await GroundTruthRejectedProbe().run(exact_match_source(REFERENCE), CONFIG)

    assert result.status is ProbeStatus.OK
    assert result.findings == ()
    assert result.sub_score == 0.0


@pytest.mark.parametrize(("name", "reference", "equal"), LENIENT_CORRECT, ids=[c[0] for c in LENIENT_CORRECT])
async def test_a_lenient_correct_verifier_is_never_reported(name: str, reference: str, equal) -> None:  # type: ignore[no-untyped-def]
    """A verifier generous about presentation accepts the first rendering tried."""
    result = await GroundTruthRejectedProbe().run(lenient_source(reference, equal), CONFIG)

    assert result.findings == (), f"the {name!r} verifier accepts its own answer and was reported anyway"


async def test_a_verifier_refusing_every_rendering_is_reported_as_a_lead() -> None:
    """The finding, and the shape of it.

    The taskset declares an answer; the verifier accepts none of the certified renderings
    of it. That is worth a human's attention and is reported — as a search budget, never
    as a verdict.
    """
    from bohrin.adapters.memory import MemorySource
    from bohrin.ir.task import Task

    tasks = [Task(id="t0", prompt="p", reference="70", reward_fns=("r",))]
    # Accepts only a form the catalogue cannot produce — the `reverse_text` shape.
    source = MemorySource(tasks, lambda _t, payload: 1.0 if payload == "<tag>70</tag>" else 0.0)

    result = await GroundTruthRejectedProbe().run(source, CONFIG)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert isinstance(finding, GroundTruthRejected)
    assert finding.reference == "70"
    assert len(finding.relations_tried) >= 8, "the search budget must record what was actually tried"
    assert "no rendering of the declared answer was accepted" in finding.summary
    assert "tried" in finding.summary, "the summary must report a budget, not a verdict"


async def test_a_rejection_never_moves_the_verification_gap() -> None:
    """The decision this probe was built around, asserted where it can regress.

    A verifier enforcing an output format the prompt documents, and one whose reward never
    reads the reply, both look exactly like a broken comparison. Scoring them would report
    a correct verifier as defective. The weight is zero and must stay zero.
    """
    from bohrin.adapters.memory import MemorySource
    from bohrin.ir.task import Task

    assert GroundTruthRejectedProbe().weight == 0.0

    tasks = [Task(id=f"t{i}", prompt="p", reference="70", reward_fns=("r",)) for i in range(3)]
    source = MemorySource(tasks, lambda _t, _p: 0.0)

    probe = GroundTruthRejectedProbe()
    result = await probe.run(source, CONFIG)

    assert result.findings, "the fixture must actually produce findings for this test to mean anything"

    gap = verification_gap([result], [probe])
    assert gap.score is None, "a rejection-only audit has no acceptance-side measurement to report"


async def test_the_probe_contributes_nothing_alongside_a_scoring_probe() -> None:
    """The gap must read exactly as it did before this probe existed."""
    from bohrin.adapters.memory import MemorySource
    from bohrin.ir.task import Task
    from bohrin.probes.weak_oracle import WeakOracleProbe

    tasks = [Task(id=f"t{i}", prompt="p", reference="70", reward_fns=("r",)) for i in range(3)]
    source = MemorySource(tasks, lambda _t, payload: 1.0 if payload.strip() == "70" else 0.0)

    weak, rejected = WeakOracleProbe(), GroundTruthRejectedProbe()
    results = [await weak.run(source, CONFIG), await rejected.run(source, CONFIG)]

    with_rejection = verification_gap(results, [weak, rejected])
    without = verification_gap(results[:1], [weak])

    assert with_rejection.score == without.score, "a zero-weight probe changed the score"


async def test_a_taskset_with_no_reward_function_is_not_applicable() -> None:
    """Same refusal weak_oracle makes: no verifier means nothing to report about one."""
    result = await GroundTruthRejectedProbe().run(unjudged_source(), CONFIG)

    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert result.findings == ()


def test_the_probe_is_registered_and_explains_what_it_cannot_see() -> None:
    """Gate 1 requires every new probe to answer `explain` naming its own blind spot."""
    ids = [p.id for p in probe_registry.discover()]
    assert "ground_truth_rejected" in ids

    text = GroundTruthRejectedProbe().explain()
    assert "cannot see" in text
    assert "contract" in text, "the output-contract confound must be stated to the user"
