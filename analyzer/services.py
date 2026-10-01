"""OFBiz-style service definitions (servicedef/*.xml): service name -> implementation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from analyzer.schema import ServiceMapping


def parse_services(path: Path, rel: str) -> list[ServiceMapping] | None:
    """None when the file is not a <services> document (e.g. service-eca files)."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    if root.tag != "services":
        return None
    out: list[ServiceMapping] = []
    for svc in root.findall("service"):
        engine, location, invoke = svc.get("engine", ""), svc.get("location", ""), svc.get("invoke", "")
        is_java = engine == "java" and bool(location)
        out.append(ServiceMapping(
            service=svc.get("name", ""), engine=engine,
            implementation=f"{location}#{invoke}" if is_java else location,
            analyzed=is_java, file=rel))
    return out
