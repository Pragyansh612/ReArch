"""OFBiz-style service definitions (servicedef/*.xml): service name -> implementation."""

from __future__ import annotations

from pathlib import Path

from analyzer.schema import ServiceMapping
from analyzer.xmlscan import scan


def parse_services(path: Path, rel: str) -> list[ServiceMapping] | None:
    """None when the file is not a <services> document (e.g. service-eca files)."""
    scanned = scan(path)
    if scanned is None or scanned[0] != "services":
        return None
    out: list[ServiceMapping] = []
    for el in scanned[1]:
        if el.tag != "service":
            continue
        engine, location, invoke = el.attrs.get("engine", ""), el.attrs.get("location", ""), el.attrs.get("invoke", "")
        is_java = engine == "java" and bool(location)
        out.append(ServiceMapping(
            service=el.attrs.get("name", ""), engine=engine, line=el.line, file=rel, analyzed=is_java,
            implementation=f"{location}#{invoke}" if is_java else location))
    return out
