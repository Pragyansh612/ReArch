"""Generate fixtures/expected.json, the test oracle for the analyzer.

Deliberately shares NO code with the analyzer package: comments/strings are stripped with a hand-written
scanner, metrics come from regexes over the stripped text, cycles from plain reachability, percentiles from
plain counting. Thresholds are read from config/assumptions.yaml (the single source of truth).
Re-run after changing the fixture:  .venv/bin/python fixtures/generate_expected.py
Values were spot-checked by hand (see docs/fixture.md); the analyzer must reproduce all of them.
"""

from __future__ import annotations

import json
import pathlib
import re
import xml.etree.ElementTree as ET
from collections import Counter

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
R = ROOT / "fixtures" / "legacy-sample"
MAIN = R / "src/main/java"
PKG = "com.example.legacy"
FULL = yaml.safe_load((ROOT / "config/assumptions.yaml").read_text())
CFG = FULL["analysis"]
SNAP = yaml.safe_load((ROOT / "config" / FULL["dependency_snapshot_file"]).read_text())


def strip(src: str) -> str:
    """Blank out comments and string/char literal contents, keeping line structure."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.index("*/", i) + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j]))
            i = j
        elif c in "\"'":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            j += 1
            out.append(c + " " * (j - i - 2) + c)
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


KW = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?")
SKIP = re.compile(r"^\s*\}?\s*(if|for|while|switch|catch|else|try|synchronized|do)\b")
DECL = re.compile(r"\)\s*(throws[^{]*)?\{\s*$")


def complexity(lines: list[str]) -> int:
    bodies = sum(1 for ln in lines if DECL.search(ln) and not SKIP.match(ln))
    return bodies + sum(len(KW.findall(ln)) for ln in lines)


def band(c: int) -> str:
    b = CFG["complexity_bands"]
    return "low" if c <= b["low_max"] else "medium" if c <= b["medium_max"] else "high"


def tier(loc: int, cx: int) -> str:
    g, e = CFG["god_class"], CFG["god_class"]["extreme"]
    if loc >= e["min_loc"] and cx > e["min_complexity_above"]:
        return "extreme"
    return "large" if loc >= g["min_loc"] and cx > g["min_complexity_above"] else "none"


# ---- classes, dependencies -------------------------------------------------------------------------
classes: dict[str, dict] = {}
for f in sorted(MAIN.rglob("*.java")):
    raw = f.read_text()
    st = strip(raw)
    classes[f.stem] = dict(file=str(f.relative_to(R)), module=f.parent.name, st=st, lines=st.split("\n"))

deps: dict[str, set[str]] = {k: set() for k in classes}
for a, ca in classes.items():
    toks = set(re.findall(r"\b[A-Z]\w*\b", re.sub(r"^(import|package) .*$", "", ca["st"], flags=re.MULTILINE)))
    imports = set(re.findall(r"^import ([\w.]+);", ca["st"], re.MULTILINE))
    for b, cb in classes.items():
        if a != b and b in toks and (cb["module"] == ca["module"] or f"{PKG}.{cb['module']}.{b}" in imports):
            deps[a].add(b)
fan_in = {k: sorted(a for a in deps if k in deps[a]) for k in classes}

# ---- services.xml / controller.xml -----------------------------------------------------------------
svc_path = R / "src/main/resources/servicedef/services.xml"
svc_lines = svc_path.read_text().splitlines()
svc_line = {m.group(1): n for n, ln in enumerate(svc_lines, 1) if (m := re.search(r'<service name="(\w+)"', ln))}
svc_root = ET.parse(svc_path).getroot()
ctl_path = R / "src/main/webapp/WEB-INF/controller.xml"
ctl_lines = ctl_path.read_text().splitlines()

analysed_modules = {c["module"] for c in classes.values()}
fqn_to_class = {f"{PKG}.{c['module']}.{k}": k for k, c in classes.items()}


def ref_status(fqn: str, method: str) -> tuple[bool, bool, str]:
    simple = fqn_to_class.get(fqn)
    if simple is None:
        in_root = fqn.startswith(PKG + ".") and fqn.split(".")[3] in analysed_modules
        return False, False, "class_missing" if in_root else "out_of_scope"
    has = bool(re.search(rf"\b{re.escape(method)}\s*\(", classes[simple]["st"]))
    return True, has, "ok" if has else "method_missing"


svc_fan: Counter[str] = Counter()
service_mappings = []
for sv in svc_root.findall("service"):
    eng, loc, inv = sv.get("engine"), sv.get("location", ""), sv.get("invoke", "")
    entry = dict(service=sv.get("name"), engine=eng, line=svc_line[sv.get("name")])
    if eng == "java":
        found, has, status = ref_status(loc, inv)
        entry.update(implementation=f"{loc}#{inv}", analyzed=True, class_found=found, method_found=has,
                     reference_status=status)
        if found:
            svc_fan[fqn_to_class[loc]] += 1
    else:
        entry.update(implementation=loc, analyzed=False)
    service_mappings.append(entry)

ctl_fan: Counter[str] = Counter()
controller_mappings = []
event_counts: Counter[str] = Counter()
request = ""
for n, ln in enumerate(ctl_lines, 1):
    if m := re.search(r'<request-map uri="(\w+)"', ln):
        request = m.group(1)
    if m := re.search(r'<event type="(\w+)"', ln):
        event_counts[m.group(1)] += 1
        if m.group(1) == "java":
            path, inv = re.search(r'path="([\w.]+)"', ln).group(1), re.search(r'invoke="(\w+)"', ln).group(1)
            found, has, status = ref_status(path, inv)
            controller_mappings.append(dict(request=request, implementation=f"{path}#{inv}", line=n,
                                            class_found=found, method_found=has, reference_status=status))
            if found:
                ctl_fan[fqn_to_class[path]] += 1

broken = [dict(source="service", name=s["service"], line=s["line"], status=s["reference_status"])
          for s in service_mappings if s.get("reference_status") in ("method_missing", "class_missing")]
broken += [dict(source="controller", name=c["request"], line=c["line"], status=c["reference_status"])
           for c in controller_mappings if c["reference_status"] in ("method_missing", "class_missing")]

# ---- per-class records -----------------------------------------------------------------------------
cls: dict[str, dict] = {}
for k, c in sorted(classes.items(), key=lambda kv: (kv[1]["module"], kv[0])):
    loc = sum(1 for ln in c["lines"] if ln.strip())
    cx = complexity(c["lines"])
    cls[k] = dict(file=c["file"], module=c["module"], loc=loc, fan_in=len(fan_in[k]), fan_out=len(deps[k]),
                  complexity=cx, complexity_band=band(cx), size_tier=tier(loc, cx),
                  service_fan_in=svc_fan[k], controller_fan_in=ctl_fan[k],
                  used=len(fan_in[k]) + svc_fan[k] + ctl_fan[k] > 0,
                  depends_on=sorted(deps[k]), depended_on_by=fan_in[k])
for key in ("loc", "complexity", "fan_in", "fan_out"):
    vals = [v[key] for v in cls.values()]
    for v in cls.values():
        v[f"{key}_percentile"] = round(100.0 * sum(1 for x in vals if x < v[key]) / len(vals), 4)

# ---- modules ---------------------------------------------------------------------------------------
mods: dict[str, dict] = {}
for m in sorted(analysed_modules):
    names = [k for k in cls if cls[k]["module"] == m]
    edges: dict[str, int] = {}
    for a in names:
        for b in deps[a]:
            if classes[b]["module"] != m:
                edges[classes[b]["module"]] = edges.get(classes[b]["module"], 0) + 1
    mods[m] = dict(classes=names, class_count=len(names), loc=sum(cls[k]["loc"] for k in names),
                   depends_on_modules=dict(sorted(edges.items())))
for m in mods:
    mods[m]["module_fan_out"] = len(mods[m]["depends_on_modules"])
    mods[m]["module_fan_in"] = sum(1 for o in mods if m in mods[o]["depends_on_modules"])
T = R / "src/test/java/com/example/legacy"
for m in mods:
    tests = sorted(p.stem for p in (T / m).glob("*.java")) if (T / m).exists() else []
    groovy_tests = len(list((R / "src/test/groovy").rglob(f"{m}/*.groovy"))) if (R / "src/test/groovy").exists() else 0
    mods[m].update(test_classes=tests, groovy_test_files=groovy_tests, has_tests=bool(tests) or groovy_tests > 0)

# coverage: the fixture is a single component (repo root)
engines = Counter(sv.get("engine") for sv in svc_root.findall("service"))
rules = CFG["coverage"]
implemented = sum(n for e, n in engines.items() if e not in rules["non_implementing_engines"])
share = round(engines["java"] / implemented, 4) if implemented else None
groovy_logic = [str(p.relative_to(R)) for p in R.rglob("*.groovy") if "/src/test/" not in str(p)]
conf = ("high" if share is None and not groovy_logic else "medium" if share is None else
        "high" if share >= rules["high_min_java_share"] else
        "medium" if share >= rules["medium_min_java_share"] else "low")
for m in mods:
    mods[m]["coverage"] = dict(component="", service_defs_total=sum(engines.values()),
                               service_defs_by_engine=dict(sorted(engines.items())), implemented_defs=implemented,
                               java_defs=engines["java"], java_share=share, groovy_logic_files=len(groovy_logic),
                               confidence=conf)

# ---- DB coupling, markers --------------------------------------------------------------------------
JD = re.compile(r"DriverManager\.getConnection\(|\.prepareStatement\(|\.createStatement\(")
ED = re.compile(r"EntityQuery\.use\(|delegator\.makeValue\(|delegator\.create\(")
db = []
for k, c in classes.items():
    for n, ln in enumerate(c["lines"], 1):
        for typ, rx in (("jdbc", JD), ("entity_engine", ED)):
            for mt in rx.finditer(ln):
                db.append(dict(type=typ, file=c["file"], line=n, module=c["module"], match=mt.group(0), **{"class": k}))
db.sort(key=lambda d: (d["file"], d["line"]))

JDK_JAVAX = {"sql", "xml"}  # JDK packages that never moved to jakarta
markers = []
for k, c in classes.items():
    for n, ln in enumerate(c["lines"], 1):
        m = re.match(r"import ((javax|jakarta)\.(\w+)[\w.]*);", ln)
        if m and not (m.group(2) == "javax" and m.group(3) in JDK_JAVAX):
            markers.append(dict(file=c["file"], line=n, module=c["module"], namespace=m.group(2),
                                family=m.group(3), **{"import": m.group(1)}))
markers.sort(key=lambda d: (d["file"], d["line"]))
for m in mods:
    ms = [x for x in markers if x["module"] == m]
    mods[m]["javax_imports"] = sum(x["namespace"] == "javax" for x in ms)
    mods[m]["jakarta_imports"] = sum(x["namespace"] == "jakarta" for x in ms)
    mods[m]["namespace_mix"] = mods[m]["javax_imports"] > 0 and mods[m]["jakarta_imports"] > 0

# ---- dependencies ----------------------------------------------------------------------------------
declared: list[tuple[str, str, str]] = []
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
pom = ET.parse(R / "pom.xml").getroot()
props = {e.tag.split("}")[1]: e.text for e in pom.find("m:properties", ns)}
for d in pom.find("m:dependencies", ns):
    ver = re.sub(r"\$\{(.+?)\}", lambda x: props[x.group(1)], d.find("m:version", ns).text)
    declared.append(("pom.xml", f"{d.find('m:groupId', ns).text}:{d.find('m:artifactId', ns).text}", ver))
toml = (R / "gradle/libs.versions.toml").read_text()
vers = dict(re.findall(r'^([\w-]+) = "([^"]+)"$', toml.split("[libraries]")[0], re.MULTILINE))
for line in toml.split("[libraries]")[1].strip().splitlines():
    mod = re.search(r'module = "([^"]+)"', line).group(1)
    ref = re.search(r'version\.ref = "([^"]+)"', line)
    declared.append(("gradle/libs.versions.toml", mod,
                     vers[ref.group(1)] if ref else re.search(r'version = "([^"]+)"', line).group(1)))
items = []
for f, coord, ver in declared:
    e = SNAP["entries"][coord]
    dm = int(re.match(r"\d+", ver).group(0))
    items.append(dict(file=f, coordinate=coord, declared_version=ver, declared_major=dm,
                      superseded_by=e.get("superseded_by"),
                      outdated=bool(e.get("superseded_by")) or dm < e["latest_major"]))


def sccs(nodes, edges):
    reach = {n: set() for n in nodes}
    for n in nodes:
        stack = list(edges.get(n, ()))
        while stack:
            x = stack.pop()
            if x not in reach[n]:
                reach[n].add(x)
                stack.extend(edges.get(x, ()))
    groups, seen = [], set()
    for n in sorted(nodes):
        if n in seen:
            continue
        g = sorted(m for m in nodes if m == n or (m in reach[n] and n in reach[m]))
        seen.update(g)
        if len(g) > 1:
            groups.append(g)
    return groups


cycles = dict(module_cycles=sccs(list(mods), {m: set(mods[m]["depends_on_modules"]) for m in mods}),
              class_cycles=sccs(list(cls), deps))
gods = [k for k, v in cls.items() if v["size_tier"] != "none"]
extremes = [k for k, v in cls.items() if v["size_tier"] == "extreme"]
h = CFG["highly_coupled"]
coupled = [k for k, v in cls.items() if v["fan_in"] >= h["min_fan_in"] and v["fan_out"] >= h["min_fan_out"]]
groovy_files = sorted(str(p.relative_to(R)) for p in R.rglob("*.groovy"))

out = dict(
    _about="Expected OUTPUTS only (Phase 2 test oracle). Thresholds live in config/assumptions.yaml; metric definitions in "
           "docs/methodology.md. Generated by fixtures/generate_expected.py, which shares no code with the analyzer.",
    totals=dict(main_java_classes=len(cls), modules=len(mods), main_java_loc=sum(c["loc"] for c in cls.values()),
                test_classes=sum(len(m["test_classes"]) for m in mods.values()),
                dependencies_declared=len(items), dependencies_checked=len(items)),
    modules=mods, classes=cls, cycles=cycles,
    deliberate_smells=[
        dict(smell="god_class", subjects=gods, why="Large tier (loc >= 400 and complexity > 50). OrderServices stands in for OFBiz OrderServices.java (7,516 LOC). LedgerReconciler (400, 51) sits exactly on the thresholds and MUST be flagged; StatementFormatter (399, 50) is one short of both and must NOT be."),
        dict(smell="god_class_extreme", subjects=extremes, why="Extreme tier (loc >= 1500 and complexity > 200). Only OrderServices; LedgerReconciler is large but not extreme."),
        dict(smell="highly_coupled_service", subjects=coupled, why="OrderReadHelper is used by party, billing and order (fan-in) and itself reaches into party and billing (fan-out), creating module cycles order<->party and order<->billing."),
        dict(smell="db_coupling_jdbc", subjects=sorted({d["class"] for d in db if d["type"] == "jdbc"}), why="Raw Connection/PreparedStatement and SQL strings inside billing business logic."),
        dict(smell="db_coupling_entity_engine", subjects=sorted({d["class"] for d in db if d["type"] == "entity_engine"}), why="Business logic calls EntityQuery/delegator directly. Dominant OFBiz pattern."),
        dict(smell="no_tests", subjects=[m for m in mods if not mods[m]["has_tests"]], why="order (the riskiest module) and common have no test evidence."),
        dict(smell="namespace_mix", subjects=[m for m in mods if mods[m]["namespace_mix"]], why="party has PartyController on jakarta.servlet and PartyLegacyHelper on javax.servlet."),
        dict(smell="legacy_ejb", subjects=["OrderServices"], why="javax.ejb.Stateless import marks EJB-era design."),
        dict(smell="logic_outside_java", subjects=["services.xml", "controller.xml", "CheckOrderFraud.groovy"], why="Service definitions, controller events and a Groovy script carry behaviour the Java analyzer cannot see."),
        dict(smell="broken_reference", subjects=[f"{b['source']} {b['name']}" for b in broken], why="Definitions pointing at a missing method or at a class missing from an analysed module. syncExternalLedger points at an unanalysed module and is NOT broken.")],
    traps_must_not_count=[
        dict(where="PaymentCalculator.java", what="EntityQuery.use( and prepareStatement( in a Javadoc comment and a string literal must NOT be db_coupling; the Javadoc mention of InvoiceService must NOT be a dependency"),
        dict(where="InvoiceService.java", what="import javax.sql.DataSource is a JDK package, NOT a legacy marker"),
        dict(where="StringUtil / GenericValue", what="high fan-in but zero fan-out, so NOT highly coupled"),
        dict(where="OrderServices", what="Java fan-in is 0 but service_fan_in 2 and controller_fan_in 1, so used=true; fan-out 13 but fan-in 0, so NOT highly coupled"),
        dict(where="StatementFormatter / LedgerReconciler", what="boundary classes: 399/50 is not a god class; 400/51 is. No dependencies, unused."),
        dict(where="Delegator.java / EntityQuery.java", what="stub declarations and calls are not db_coupling (ignored classes)"),
        dict(where="services.xml", what="syncExternalLedger (class in an unanalysed module) is out_of_scope, not broken; interface engines are excluded from the coverage denominator"),
        dict(where="controller.xml", what="service and groovy events are counted by type but do not add controller_fan_in")],
    db_coupling=dict(total=len(db), jdbc=sum(d["type"] == "jdbc" for d in db),
                     entity_engine=sum(d["type"] == "entity_engine" for d in db), instances=db),
    legacy_markers=dict(instances=markers),
    dependencies=dict(snapshot_as_of=SNAP["as_of"], outdated_count=sum(i["outdated"] for i in items),
                      not_outdated=sorted({i["coordinate"] for i in items if not i["outdated"]}), items=items),
    service_mappings=service_mappings, controller_mappings=controller_mappings, broken_references=broken,
    unanalyzed_files=dict(groovy_count=len(groovy_files), groovy_files=groovy_files,
                          service_xml_files=["src/main/resources/servicedef/services.xml"],
                          controller_xml_files=["src/main/webapp/WEB-INF/controller.xml"],
                          controller_event_counts=dict(sorted(event_counts.items())),
                          service_engine_counts=dict(sorted(engines.items())), report_status="not_analyzed"))
(ROOT / "fixtures" / "expected.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out["totals"]))
for k, c in cls.items():
    print(f"{c['module']:8}{k:20} loc={c['loc']:5} in={c['fan_in']} out={c['fan_out']} svc={c['service_fan_in']} "
          f"ctl={c['controller_fan_in']} cx={c['complexity']:4} {c['complexity_band']:6} tier={c['size_tier']:8} used={c['used']}")
print("broken:", broken)
print("coverage:", mods["order"]["coverage"])
print("outdated:", out["dependencies"]["outdated_count"], "cycles:", cycles)
