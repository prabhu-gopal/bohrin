"""The actions this repository's workflows run are pinned to commits, not to tags.

A tag can be moved to different code after it is reviewed; a commit cannot. The release
workflow runs third-party actions in the same job as ``id-token: write``, the credential that
publishes to PyPI, so a moved tag on any of them could publish a package this repository never
built. That is not hypothetical: in March 2025 the tags of a widely used action were rewritten to
point at code that dumped CI secrets into build logs.

To update a pin, change the commit and the version comment together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

pytestmark = pytest.mark.skipif(not WORKFLOWS.is_dir(), reason="no workflows in this checkout (e.g. an sdist)")

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)", re.MULTILINE)
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _workflows() -> list[Path]:
    """The workflows, and the Action this repository publishes, which runs in other people's CI."""
    action = WORKFLOWS.parents[1] / "action.yml"
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")) + ([action] if action.is_file() else [])


def test_every_third_party_action_is_pinned_to_a_full_commit() -> None:
    unpinned = [
        f"{path.name}: {ref}"
        for path in _workflows()
        for ref in _USES.findall(path.read_text(encoding="utf-8"))
        if not ref.startswith("./") and not _PINNED.match(ref)
    ]

    assert unpinned == [], f"pin these to a 40-character commit SHA: {unpinned}"


def test_every_checkout_drops_the_token_after_cloning() -> None:
    """``actions/checkout`` otherwise writes the job's token into ``.git/config``, where every
    later step, and any artefact that includes the directory, can read it."""
    missing = []
    for path in _workflows():
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            if "uses: actions/checkout@" in line:
                block = "\n".join(lines[number + 1 : number + 4])
                if "persist-credentials: false" not in block:
                    missing.append(f"{path.name}:{number + 1}")

    assert missing == [], f"add `persist-credentials: false` to the checkout at {missing}"


def test_the_guard_would_catch_a_tag() -> None:
    """The counterweight: the pattern really rejects the forms it exists to reject."""
    assert not _PINNED.match("actions/checkout@v7")
    assert not _PINNED.match("pypa/gh-action-pypi-publish@release/v1")
    assert _PINNED.match("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")


def test_the_build_that_ships_restores_no_cache_and_uses_no_third_party_release_action() -> None:
    """A cache another run wrote must never feed the published files (zizmor: cache-poisoning)."""
    release = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml").read_text()
    build = release[release.index("  build:") : release.index("  publish-testpypi:")]
    assert "enable-cache: false" in build
    assert "softprops/" not in release
    assert "sigstore/gh-action-sigstore-python@" in release and "dist/*.sigstore.json" in release
