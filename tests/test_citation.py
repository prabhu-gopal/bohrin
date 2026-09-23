"""The citation file names the version that is actually released.

A release bumps ``bohrin.__version__``; a citation left on the previous version sends readers to
the wrong code. Read with a line match rather than a YAML parser, so no dependency is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bohrin import __version__

CITATION = Path(__file__).resolve().parents[1] / "CITATION.cff"

pytestmark = pytest.mark.skipif(not CITATION.is_file(), reason="no CITATION.cff in this checkout")


def test_the_citation_names_the_package_version() -> None:
    match = re.search(r"^version:\s*(\S+)\s*$", CITATION.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None, "CITATION.cff has no version line"
    assert match.group(1) == __version__, "bump CITATION.cff's version and date-released with the release"
