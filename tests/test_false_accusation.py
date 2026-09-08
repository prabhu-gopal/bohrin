"""The false-accusation guard.

Bohrin's governing rule is that it must never falsely accuse a verifier. Until 1.0.1 the
only clean fixture was an exact-string matcher, which cannot catch the whole class of
defect where an operator mistakes a difference in *rendering* for a difference in
*behaviour*. Four paths were reachable:

* ``constant_return`` submitting ``"1"`` against a reference of ``"1.0"``;
* the same against ``"true"`` versus ``"True"``;
* ``negate_condition`` inverting a branch whose arms do the same thing;
* ``drop_side_effect`` emptying a body that was already ``pass``.

Every test here fails the build if any of them comes back. The last test in the file is
the one that keeps the rest honest: it proves the guards suppress false accusations
without simply switching the probe off.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from _fixtures import (
    EQUIVALENT_BRANCH_REFERENCE,
    LENIENT_CORRECT,
    TRIVIAL_REFERENCE,
    behavioural_source,
    exact_match_source,
    lenient_source,
    weak_source,
)
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.mutate import discover as discover_operators
from bohrin.mutate.equivalence import code_equivalent, collides_under, provably_distinct
from bohrin.probes import registry as probe_registry
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.scoring.gap import verification_gap

CONFIG = ScanConfig(unsafe_local=True)


def _exploits(result: ProbeResult) -> list[Exploit]:
    """The acceptance findings, narrowed. ``weak_oracle`` emits no flakes, but the
    ``Finding`` union carries them, so the narrowing is explicit rather than assumed."""
    return [f for f in result.findings if isinstance(f, Exploit)]


# --------------------------------------------------------------------------- the guard


@pytest.mark.parametrize(("name", "reference", "equal"), LENIENT_CORRECT, ids=[c[0] for c in LENIENT_CORRECT])
async def test_a_lenient_but_correct_verifier_is_never_accused(
    name: str, reference: str, equal: Callable[[str, str], bool]
) -> None:
    """A verifier can be generous about presentation and still be entirely correct.

    Accepting ``1`` for a stored answer of ``1.0`` is numeric comparison working, not a
    weak oracle. Reporting it is the failure this whole file exists to prevent.
    """
    result = await WeakOracleProbe().run(lenient_source(reference, equal), CONFIG)

    assert result.findings == (), (
        f"falsely accused the {name!r} verifier, which is correct: "
        f"{[(f.task_id, f.candidate.provenance.operator, f.candidate.payload) for f in _exploits(result)]}"
    )
    assert result.sub_score == 0.0


async def test_emptying_an_already_empty_reference_is_not_an_exploit() -> None:
    """The mutant is byte-identical to the answer the verifier just accepted.

    Reporting it accuses the verifier of accepting its own known-good solution.
    """
    result = await WeakOracleProbe().run(exact_match_source(TRIVIAL_REFERENCE), CONFIG)

    assert result.findings == ()
    assert result.sub_score == 0.0


async def test_negating_an_inert_branch_is_a_lead_and_never_a_finding() -> None:
    """Negating a predicate whose arms are identical cannot change behaviour.

    This is the textbook equivalent mutant. Trivial Compiler Equivalence cannot catch it —
    the negation compiles to different bytecode — so the operator must not claim a ground
    in the first place.
    """
    # A behavioural grader is required here: it accepts any program that behaves like
    # the reference, so it *correctly* accepts the inert negation. A textual grader would
    # reject the mutated source outright and the test would pass for the wrong reason.
    source = behavioural_source(EQUIVALENT_BRANCH_REFERENCE, inputs=(-2, 0, 3))
    result = await WeakOracleProbe().run(source, CONFIG)

    negations = [f for f in _exploits(result) if f.candidate.provenance.operator == "negate_condition"]
    assert negations == [], "an equivalent mutant was reported as an exploit"

    # It is still allowed to surface as advisory, and it must carry no ground if it does.
    for lead in result.unverified:
        if lead.candidate.provenance.operator == "negate_condition":
            assert lead.candidate.ground is None


async def test_no_operator_accuses_any_clean_verifier() -> None:
    """The exhaustive matrix: every registered operator against every correct grader.

    Enumerated rather than randomly generated because the space is small and finite — the
    six literals against the renderings that collide with them — so exhaustion is a
    stronger guarantee here than sampling.
    """
    offenders: list[str] = []
    for name, reference, equal in LENIENT_CORRECT:
        for operator in discover_operators():
            config = ScanConfig(unsafe_local=True, only_operators=frozenset({operator.id}))
            result = await WeakOracleProbe().run(lenient_source(reference, equal), config)
            for finding in _exploits(result):
                offenders.append(f"{operator.id} accused the {name} verifier with {finding.candidate.payload!r}")

    assert offenders == [], "\n".join(offenders)


async def test_the_guards_did_not_simply_disable_the_probe() -> None:
    """The counterweight, and the reason the tests above are not vacuous.

    Suppressing every candidate would pass every test in this file. A genuinely weak
    verifier must still be caught, with a ground attached.
    """
    result = await WeakOracleProbe().run(weak_source(), CONFIG)

    assert result.findings, "the guards silenced the probe on a verifier that accepts anything"
    assert result.sub_score == 1.0
    assert all(f.candidate.known_wrong for f in _exploits(result))


@pytest.mark.parametrize(("name", "reference", "equal"), LENIENT_CORRECT, ids=[c[0] for c in LENIENT_CORRECT])
async def test_a_full_audit_of_a_correct_verifier_scores_zero(
    name: str, reference: str, equal: Callable[[str, str], bool]
) -> None:
    """The number the customer actually sees, not a probe's internal sub-score.

    Every other test here asserts on one probe. A user reads the Verification Gap, which
    is computed across all of them, so the invariant is stated where they see it: a
    verifier that is correct scores zero, at full coverage.
    """
    probes = probe_registry.discover()
    source = lenient_source(reference, equal)
    results = [await probe.run(source, CONFIG) for probe in probes]

    gap = verification_gap(results, probes)

    assert gap.score == 0.0, f"a correct {name!r} verifier was scored {gap.score}"
    # Zero at *no* coverage would be vacuous: the probes must actually have measured it.
    assert len(gap.coverage.measured) == len(probes)
    assert all(r.status is ProbeStatus.OK for r in results)


# --------------------------------------------------------------- the underlying checks


@pytest.mark.parametrize(
    ("literal", "reference", "normalisation"),
    [
        ("1", "1.0", "numeric"),
        ("0", "0.0", "numeric"),
        ("1", "01", "numeric"),
        ("1", "+1", "numeric"),
        ("1", "1.00", "numeric"),
        ("True", "true", "case"),
        ("None", "none", "case"),
        ("1", "yes", "boolean"),
        ("True", "1", "boolean"),
        ("[]", "[ ]", "literal"),
        ('""', "''", "literal"),
    ],
)
def test_renderings_of_one_answer_are_not_distinct(literal: str, reference: str, normalisation: str) -> None:
    assert collides_under(literal, reference) == normalisation
    assert not provably_distinct(literal, reference)


@pytest.mark.parametrize(
    ("literal", "reference"),
    [("0", "42"), ("1", "42"), ("1", "1.5"), ("1", "100"), ("[]", "[1]"), ('""', "hello"), ("True", "banana")],
)
def test_genuinely_different_answers_keep_their_ground(literal: str, reference: str) -> None:
    """The guard must not cost recall on answers that really are different."""
    assert provably_distinct(literal, reference)


def test_trivial_compiler_equivalence_ignores_formatting_only_changes() -> None:
    reference = "def solve(x):\n    if x > 0:\n        return x\n    return 0\n"
    commented = "def solve(x):\n    # unchanged\n    if x > 0:\n        return x\n    return 0\n"

    assert code_equivalent(reference, commented)
    assert code_equivalent(reference, "\n\n" + reference)


def test_trivial_compiler_equivalence_does_not_suppress_real_mutations() -> None:
    """Sound, not merely convenient: it must never call two different programs the same."""
    reference = "def solve(x):\n    if x > 0:\n        return x\n    return 0\n"

    assert not code_equivalent(reference, "def solve(x):\n    pass\n")
    assert not code_equivalent(reference, "def solve(x):\n    if not x > 0:\n        return x\n    return 0\n")
    assert not code_equivalent(reference, "I cannot complete this task.")


def test_equivalence_descends_into_nested_code_objects() -> None:
    """The trap that makes a naive implementation catastrophic.

    A module's own ``co_code`` only builds and stores its functions; the body lives in
    ``co_consts``. Two modules whose functions differ completely still share a
    byte-identical module-level ``co_code``, so comparing that alone would declare every
    mutant equivalent and silently suppress every finding in the product.
    """
    one = "def f(x):\n    return x + 1\n"
    two = "def f(x):\n    return x * 999\n"

    assert compile(one, "<a>", "exec").co_code == compile(two, "<b>", "exec").co_code
    assert not code_equivalent(one, two)


@pytest.mark.parametrize("reference", ["70", "5050", "0", "1", "3.14", "True", "None"])
def test_a_bare_answer_is_not_a_program_and_suppresses_nothing(reference: str) -> None:
    """The recall bug this pins, and why it was invisible.

    Python discards a bare constant expression statement as dead code, so ``compile("70")``
    is byte-identical to ``compile("")``. Trivial Compiler Equivalence therefore called an
    empty reply "the same program as the reference" and suppressed it — on every taskset
    whose answer is a bare number, which is the commonest shape in the ecosystem.

    Nothing failed and nothing was reported; the candidate simply never reached the
    verifier. Silent lost recall is the mirror image of the false accusations this module
    exists to prevent, and it was introduced by the fix for them.
    """
    assert not code_equivalent("", reference)
    assert not code_equivalent("0", reference) or reference == "0"
    assert not code_equivalent("I cannot complete this task.", reference)


def test_the_equivalence_check_still_catches_a_real_equivalent_mutant() -> None:
    """The counterweight: the fix must not switch TCE off.

    Emptying a body that was already ``pass`` produces a mutant byte-identical to its
    reference. Reporting that accuses a verifier of accepting its own known-good answer,
    and it must stay suppressed.
    """
    trivial = "def solve(x):\n    pass\n"

    assert code_equivalent(trivial, trivial)
    assert code_equivalent(trivial, "def solve(x):\n    # unchanged\n    pass\n")
    assert not code_equivalent("def solve(x):\n    return 1\n", trivial)


async def test_an_empty_reply_is_still_found_on_a_numeric_answer() -> None:
    """End to end: the suppressed candidate reaches the verifier again.

    A verifier accepting an empty reply is weak whatever its answer looks like, and the
    numeric-answer case is the commonest one in the ecosystem — so this is exactly where
    the probe must not go quiet.
    """
    from bohrin.adapters.memory import MemorySource
    from bohrin.ir.task import Task

    tasks = [Task(id="t0", prompt="p", reference="70", reward_fns=("r",))]
    source = MemorySource(tasks, lambda _t, _p: 1.0)  # accepts literally anything

    result = await WeakOracleProbe().run(source, CONFIG)

    operators = {f.candidate.provenance.operator for f in _exploits(result)}
    assert "empty_body" in operators, "an empty reply was suppressed against a numeric answer"
    assert result.detail.get("equivalent_suppressed") == 0
