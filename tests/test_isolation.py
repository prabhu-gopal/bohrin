"""Isolation classification and the refusal to run unshielded.

These tests are about honesty as much as safety. The failure this guards against is not
only "untrusted code escaped" — it is "a result produced with no boundary was mistaken for
one produced inside a container".
"""

from __future__ import annotations

import pytest

from bohrin.config import default_concurrency
from bohrin.execute.isolation import (
    Assessment,
    Isolation,
    UnsafeExecutionError,
    assess,
    require,
)


def _unbounded() -> Assessment:
    return Assessment(
        effective=Isolation.NONE,
        best_available=Isolation.SUBPROCESS,
        already_contained=False,
        notes=("docker is installed but not running",),
    )


def _contained() -> Assessment:
    return Assessment(
        effective=Isolation.NONE,
        best_available=Isolation.CONTAINER,
        already_contained=True,
        notes=("running inside a container",),
    )


# ------------------------------------------------------------------------- the refusal


def test_unshielded_execution_is_refused_by_default() -> None:
    with pytest.raises(UnsafeExecutionError) as exc:
        require(_unbounded(), unsafe_local=False)

    message = str(exc.value)
    assert "--unsafe-local" in message, "a refusal must name the way forward"
    assert "downloaded" in message, "the refusal must state the threat model, not just refuse"


def test_the_acknowledgement_permits_it() -> None:
    require(_unbounded(), unsafe_local=True)  # must not raise


def test_running_inside_a_container_is_already_bounded() -> None:
    """The boundary exists around Bohrin as a whole; in-process execution inherits it."""
    assessment = _contained()

    assert assessment.is_bounded
    require(assessment, unsafe_local=False)  # must not raise


@pytest.mark.parametrize(
    ("level", "bounded"),
    [(Isolation.NONE, False), (Isolation.SUBPROCESS, True), (Isolation.CONTAINER, True)],
)
def test_levels_are_ordered_so_policy_is_a_comparison(level: Isolation, bounded: bool) -> None:
    assessment = Assessment(effective=level, best_available=level, already_contained=False)
    assert assessment.is_bounded is bounded
    assert Isolation.NONE < Isolation.SUBPROCESS < Isolation.CONTAINER < Isolation.VM


# ---------------------------------------------------------------------------- honesty


def test_subprocess_is_never_described_as_a_sandbox() -> None:
    """Process limits prevent denial of service, not escape.

    Calling that level a sandbox would misrepresent what the audit was protected by, which
    matters because the isolation level is recorded as evidence.
    """
    label = Isolation.SUBPROCESS.label

    assert "not a security boundary" in label
    assert "sandbox" not in label.lower()


def test_the_assessment_serializes_for_the_report() -> None:
    """How an audit was executed is part of its evidence."""
    blob = _unbounded().to_dict()

    assert blob["effective"] == "none"
    assert blob["already_contained"] is False
    assert blob["notes"], "an assessment must explain itself"


def test_a_real_assessment_is_self_consistent() -> None:
    """Runs against whatever this machine actually has."""
    assessment = assess()

    assert assessment.best_available >= assessment.effective
    assert isinstance(assessment.notes, tuple)
    assert assessment.notes, "every assessment should say something actionable"


# ----------------------------------------------------------------- resource-awareness


def test_concurrency_is_bounded_and_leaves_the_machine_usable() -> None:
    """An audit must not crowd out the machine it is running on."""
    value = default_concurrency()

    assert 2 <= value <= 8, f"concurrency {value} is outside the intended envelope"
