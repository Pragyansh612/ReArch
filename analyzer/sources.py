"""Find the files to analyse. Pure filesystem work; no parsing of Java here."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from analyzer.config import AnalysisConfig


@dataclass
class SourceSet:
    root: Path
    main_java: list[Path] = field(default_factory=list)
    test_java: list[Path] = field(default_factory=list)
    groovy: list[Path] = field(default_factory=list)
    service_xml_candidates: list[Path] = field(default_factory=list)


def _walk(base: Path, skip: set[str]) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        found.extend(Path(dirpath) / f for f in sorted(filenames))
    return found


def _under(path: Path, root: Path, marker: str) -> bool:
    return f"/{marker.strip('/')}/" in "/" + path.relative_to(root).as_posix()


def discover(root: Path, scope: list[str], cfg: AnalysisConfig) -> SourceSet:
    """`scope` is a list of directories relative to `root`; empty means the whole repo."""
    skip = set(cfg.skip_dirs)
    out = SourceSet(root=root)
    for base in [root / s for s in scope] or [root]:
        if not base.is_dir():
            raise FileNotFoundError(f"scope directory not found: {base}")
        for path in _walk(base, skip):
            if path.suffix == ".java" and _under(path, root, cfg.main_java_dir):
                out.main_java.append(path)
            elif path.suffix == ".java" and _under(path, root, cfg.test_java_dir):
                out.test_java.append(path)
            elif path.suffix == ".groovy":
                out.groovy.append(path)
            elif path.suffix == ".xml" and path.parent.name == cfg.services_dir_name:
                out.service_xml_candidates.append(path)
    return out


def find_dependency_files(root: Path, cfg: AnalysisConfig) -> tuple[list[Path], list[Path]]:
    """pom.xml and libs.versions.toml anywhere under the repo root (not limited to the scope)."""
    poms, tomls = [], []
    for path in _walk(root, set(cfg.skip_dirs)):
        if path.name == "pom.xml":
            poms.append(path)
        elif path.name == "libs.versions.toml":
            tomls.append(path)
    return poms, tomls
