from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analyzer.analyze import analyze
from analyzer.schema import AnalysisResult

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "legacy-sample"
PKG = "com.example.legacy"


@pytest.fixture(scope="session")
def expected() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / "fixtures" / "expected.json").read_text())
    return data


@pytest.fixture(scope="session")
def result() -> AnalysisResult:
    return analyze(FIXTURE, name="legacy-sample")


@pytest.fixture(scope="session")
def fqn_of(expected: dict[str, Any]) -> Any:
    """simple class name -> fully qualified name, using the module recorded in expected.json."""
    return lambda name: f"{PKG}.{expected['classes'][name]['module']}.{name}"
