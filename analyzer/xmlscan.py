"""Tiny line-number-aware XML scanner (expat). ElementTree drops line numbers; evidence needs them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: dict[str, str]
    line: int
    parents: tuple[tuple[str, dict[str, str]], ...]  # ancestors, outermost first


def scan(path: Path) -> tuple[str, list[Element]] | None:
    """Returns (root tag, every element in document order), or None if the file is not well-formed."""
    stack: list[tuple[str, dict[str, str]]] = []
    elements: list[Element] = []
    parser = expat.ParserCreate()

    def start(tag: str, attrs: dict[str, str]) -> None:
        elements.append(Element(tag, dict(attrs), parser.CurrentLineNumber, tuple(stack)))
        stack.append((tag, dict(attrs)))

    def end(_tag: str) -> None:
        stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(path.read_bytes(), True)
    except expat.ExpatError:
        return None
    return (elements[0].tag, elements) if elements else None
