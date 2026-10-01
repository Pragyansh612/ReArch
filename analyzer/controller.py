"""OFBiz controller.xml: request maps and the event handlers they invoke."""

from __future__ import annotations

from pathlib import Path

from analyzer.schema import ControllerMapping
from analyzer.xmlscan import scan


def parse_controller(path: Path, rel: str) -> tuple[list[ControllerMapping], dict[str, int]] | None:
    """(java event mappings, count of events per type); None when the file is not a <site-conf>."""
    scanned = scan(path)
    if scanned is None or scanned[0] != "site-conf":
        return None
    mappings: list[ControllerMapping] = []
    counts: dict[str, int] = {}
    for el in scanned[1]:
        if el.tag != "event":
            continue
        kind = el.attrs.get("type", "")
        counts[kind] = counts.get(kind, 0) + 1
        if kind != "java" or not el.attrs.get("path"):
            continue
        request = next((a.get("uri", "") for tag, a in reversed(el.parents) if tag == "request-map"), "")
        mappings.append(ControllerMapping(
            request=request, implementation=f"{el.attrs['path']}#{el.attrs.get('invoke', '')}",
            file=rel, line=el.line))
    return mappings, counts
