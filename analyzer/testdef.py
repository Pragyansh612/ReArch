"""OFBiz testdef/*.xml suites: <test-suite><test-case>. Counted as test evidence, never executed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyzer.xmlscan import scan


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class
    line: int
    class_name: str | None  # first class-name attribute inside the case, if any


def parse_testdef(path: Path, data_load_elements: list[str]) -> list[TestCase] | None:
    """Test cases that run something (a case holding only data-load elements is not a test).

    None when the file is not a <test-suite> document.
    """
    scanned = scan(path)
    if scanned is None or scanned[0] != "test-suite":
        return None
    cases: dict[int, list[str | None]] = {}
    for el in scanned[1]:
        if el.tag == "test-case":
            cases.setdefault(el.line, [])
            continue
        owner = next((a for tag, a in reversed(el.parents) if tag == "test-case"), None)
        if owner is None or el.tag in data_load_elements:
            continue
        key = max(c for c in cases if c <= el.line)  # the enclosing test-case is the latest one opened
        cases[key].append(el.attrs.get("class-name"))
    return [TestCase(line, next((n for n in names if n), None)) for line, names in sorted(cases.items()) if names]
