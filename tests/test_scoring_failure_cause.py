"""When a reward function raises, the message names the likely cause — and only a checkable one.

Found on the 2026-09-15 sweep. An environment's grader failed on every task with
``KeyError: 'PRIME_API_KEY'``: it calls an external service and needs a credential. Bohrin said
the reward functions "read rollout state that only a live multi-turn rollout produces", which is
true of many environments and false of that one, so the advice pointed at the wrong fix.

A missing environment variable is checkable, so it is named when it is the cause. Everything else
keeps the rollout-state explanation. The counterweights matter as much as the fix: an ordinary
state field such as ``'answer'`` must not be mistaken for a credential, and a variable that *is*
set cannot be the reason.
"""

from __future__ import annotations

import pytest

from bohrin.adapters.verifiers_legacy import _likely_cause

_ROLLOUT = "rollout state"
_CREDENTIAL = "environment variable"


@pytest.mark.parametrize(
    "error",
    [
        "Error calling reward function reward_fn: 'PRIME_API_KEY'",  # the measured case
        "Error calling reward function judge: 'OPENAI_API_KEY'",
        "Error calling reward function f: 'HF_TOKEN'",
    ],
)
def test_a_missing_credential_is_named(error: str, monkeypatch: pytest.MonkeyPatch) -> None:
    name = error.rsplit("'", 2)[1]
    monkeypatch.delenv(name, raising=False)

    cause = _likely_cause(error)

    assert name in cause
    assert _CREDENTIAL in cause
    assert _ROLLOUT not in cause


@pytest.mark.parametrize(
    "error",
    [
        "Error calling reward function f: 'answer'",  # a state field, not a credential
        "Error calling reward function f: 'responses'",
        "Error calling reward function f: 'X'",  # too short to be an environment variable name
        "Error calling reward function f: division by zero",
    ],
)
def test_anything_else_keeps_the_rollout_explanation(error: str) -> None:
    assert _ROLLOUT in _likely_cause(error)


def test_a_variable_that_is_set_is_not_blamed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIME_API_KEY", "present")

    cause = _likely_cause("Error calling reward function reward_fn: 'PRIME_API_KEY'")

    assert _CREDENTIAL not in cause
    assert _ROLLOUT in cause
