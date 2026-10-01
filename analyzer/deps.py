"""Dependency declarations (pom.xml, gradle/libs.versions.toml) checked against the bundled table."""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from analyzer.config import DependencySnapshot
from analyzer.schema import Dependency

Declared = tuple[str, str | None]  # (group:artifact, version or None)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return None


def parse_pom(path: Path) -> list[Declared]:
    root = ET.parse(path).getroot()
    props: dict[str, str] = {}
    for child in root:
        if _local(child.tag) == "properties":
            props = {_local(p.tag): (p.text or "").strip() for p in child}

    def resolve(value: str) -> str:
        return re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m.group(1), m.group(0)), value)

    found: list[Declared] = []
    for dep in root.iter():
        if _local(dep.tag) != "dependency":
            continue
        group, artifact = _child_text(dep, "groupId"), _child_text(dep, "artifactId")
        if not group or not artifact:
            continue
        version = _child_text(dep, "version")
        if version is not None:
            version = resolve(version)
            version = None if "${" in version else version
        found.append((f"{group}:{artifact}", version))
    return found


def _toml_version(entry: dict[str, Any], versions: dict[str, str]) -> str | None:
    ver = entry.get("version")
    if isinstance(ver, str):
        return ver
    if isinstance(ver, dict):
        ref = ver.get("ref")
        return versions.get(ref) if isinstance(ref, str) else None
    return None


def parse_version_catalog(path: Path) -> list[Declared]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    versions = {k: v for k, v in data.get("versions", {}).items() if isinstance(v, str)}
    found: list[Declared] = []
    for entry in data.get("libraries", {}).values():
        if isinstance(entry, str):  # "group:artifact:version"
            parts = entry.split(":")
            found.append((":".join(parts[:2]), parts[2] if len(parts) > 2 else None))
            continue
        module = entry.get("module") or f"{entry.get('group', '')}:{entry.get('name', '')}"
        found.append((module, _toml_version(entry, versions)))
    return found


def major(version: str | None) -> int | None:
    match = re.match(r"\d+", version or "")
    return int(match.group(0)) if match else None


def evaluate(file: str, declared: list[Declared], snapshot: DependencySnapshot,
             date_based_min: int = 1900) -> list[Dependency]:
    out: list[Dependency] = []
    for coordinate, version in declared:
        declared_major, entry = major(version), snapshot.entries.get(coordinate)
        latest = entry.latest_major if entry else None
        superseded = entry.superseded_by if entry else None
        calendar = any(m is not None and m >= date_based_min for m in (declared_major, latest))
        checked = (declared_major is not None and entry is not None and not calendar
                   and (latest is not None or superseded is not None))
        outdated: bool | None = None
        if checked and declared_major is not None:
            outdated = superseded is not None or (latest is not None and declared_major < latest)
        out.append(Dependency(
            file=file, coordinate=coordinate, declared_version=version, declared_major=declared_major,
            latest_stable_version=entry.latest_stable_version if entry else None, latest_major=latest,
            superseded_by=superseded, checked=checked, outdated=outdated))
    return out
