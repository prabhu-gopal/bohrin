"""The message a version conflict produces has to point the right way.

`verifiers` can be wrong for this adapter in two opposite ways, and the advice differs:

* **Too old.** A taskset's own pin resolved `verifiers` *down* to a version predating
  `verifiers.legacy`. Upgrading fixes it.
* **Past the removal.** Upstream removed the legacy API after 0.3.1, so a taskset pinning a
  newer build installs a `verifiers` that will never have it. Upgrading makes it worse.

Until this was fixed, both produced the same sentence — "Bohrin needs 0.3.0 or newer" —
which a user on 0.3.2.dev86 reads as advice to upgrade past the version they already have.
Measured on the 2026-09-13 sweep: 8 of 57 public environments installed a `verifiers` past
the removal, so this is the most common failure the adapter reports.
"""

from __future__ import annotations

import pytest

from bohrin.adapters import verifiers_legacy as legacy
from bohrin.adapters.base import MissingExtraError


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.3.1", (0, 3, 1)),
        ("0.3.2.dev86", (0, 3, 2)),  # a pre-release carries that release's API
        ("0.3.2", (0, 3, 2)),
        ("1.0", (1, 0)),
        ("0.1.9.post2", (0, 1, 9)),
        ("nonsense", ()),
    ],
)
def test_release_reads_the_leading_numbers(version: str, expected: tuple[int, ...]) -> None:
    assert legacy._release(version) == expected


def _refusal(monkeypatch: pytest.MonkeyPatch, installed: str | None) -> str:
    monkeypatch.setattr(legacy, "_available", lambda: False)
    monkeypatch.setattr(legacy, "_installed_version", lambda: installed)
    with pytest.raises(MissingExtraError) as caught:
        legacy.VerifiersLegacyAdapter().check_requirements()
    return str(caught.value)


@pytest.mark.parametrize("installed", ["0.3.2", "0.3.2.dev86", "0.4.0", "1.0.0"])
def test_a_version_past_the_removal_is_told_to_pin_back(monkeypatch: pytest.MonkeyPatch, installed: str) -> None:
    """Before this: told to upgrade, from a version already past the removal."""
    message = _refusal(monkeypatch, installed)

    assert "verifiers<0.3.2" in message
    assert "removed after 0.3.1" in message
    assert "upgrade" not in message, "upgrading cannot fix this and must not be suggested"
    assert installed in message


@pytest.mark.parametrize("installed", ["0.2.0", "0.1.5"])
def test_a_version_below_the_api_is_still_told_to_upgrade(monkeypatch: pytest.MonkeyPatch, installed: str) -> None:
    """The counterweight: the original advice is right for the original case."""
    message = _refusal(monkeypatch, installed)

    assert "--upgrade" in message
    assert "verifiers<0.3.2" not in message


def test_verifiers_absent_asks_for_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _refusal(monkeypatch, None)

    assert "pip install 'bohrin[verifiers]'" in message


@pytest.mark.parametrize("installed", ["0.3.2.dev95", "0.3.2"])
def test_the_message_names_the_real_cause_of_a_version_past_the_removal(
    monkeypatch: pytest.MonkeyPatch, installed: str
) -> None:
    """Before: it said a taskset's pins "pulled verifiers past the removal". None had.

    Measured on the 2026-09-15 sweep: 10 of 57 environments installed 0.3.2.dev95. One asks for
    `verifiers>=0.1.11.dev0`; naming a dev release makes pip consider pre-releases for that
    requirement, so it picked the newest (a stable `>=0.1.11` resolves 0.3.1). Holding
    `verifiers<0.3.2` made two of them load. The advice was right and the explanation was not.
    """
    message = _refusal(monkeypatch, installed)

    assert "pre-release" in message
    assert "pulled verifiers past the removal" not in message
    assert "0.3.1 still" in message, "the user needs to know the pin cannot break the taskset's own requirement"
