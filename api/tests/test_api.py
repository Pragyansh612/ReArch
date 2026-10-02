"""API tests (TestClient): end to end on the fixture, versioning, what-if, cache, demo mode, validation, explain."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from api.app.db import Analysis, Run, RunArtifact, ScenarioVersion
from api.app.explain import explain as explain_number
from api.app.explain import locate, make_id, numeric_leaves, parse_id
from api.app.main import create_app
from api.app.runs import CLIENT_PROFILE
from api.app.settings import ROOT
from api.tests.conftest import FIXTURE, make_settings, write_demo
from engine.schema import Recommendation


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


def err(r: Any, status: int, code: str | None = None) -> dict[str, Any]:
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}  # one error format everywhere
    if code:
        assert body["error"]["code"] == code
    return dict(body["error"])


def counts(app: FastAPI) -> tuple[int, ...]:
    with app.state.svc.session() as s:
        return tuple(len(s.exec(select(t)).all()) for t in (Analysis, ScenarioVersion, Run, RunArtifact))


# --- end to end -----------------------------------------------------------------------------------------------------------------

def test_end_to_end_on_the_fixture(client: TestClient) -> None:
    created = ok(client.post("/analyses", json={"repo": str(FIXTURE), "name": "legacy-sample"}), 202)
    aid = created["id"]
    status = ok(client.get(f"/analyses/{aid}/status"))
    assert status["status"] == "done" and status["classes"] == 20 and status["loc"] == 2825  # the background job has finished
    summary = ok(client.get(f"/analyses/{aid}"))
    assert summary["totals"]["main_java_classes"] == 20 and summary["scenario_version"] == 1
    assert {c["module"] for c in summary["coverage"]} == {"billing", "common", "order", "party"}
    assert summary["findings"]["dependencies"] == {"declared": 11, "checked": 11, "outdated": 8}
    assert len(summary["findings"]["broken_references"]) == 3
    scenario = ok(client.get(f"/analyses/{aid}/scenario"))
    assert scenario["version"] == 1 and "ILLUSTRATIVE" in scenario["illustrative"]
    rec = ok(client.get(f"/analyses/{aid}/recommendation"))
    assert rec["run"]["analysis_id"] == aid and rec["run"]["profile"] == CLIENT_PROFILE
    assert Recommendation.model_validate(rec["recommendation"]).work_packages
    road = ok(client.get(f"/analyses/{aid}/roadmap"))
    assert road["roadmap"]["headlines"][0]["id"] == "portfolio" and road["roadmap"]["items"]
    number = rec["run"]["number_id_prefix"] + "work_packages/order~1cycle-1/options/0/tco/tco_jpy"
    ex = ok(client.get(f"/explain/{number}"))
    wp = rec["recommendation"]["work_packages"]["order/cycle-1"]
    assert ex["value"] == wp["options"][0]["tco"]["tco_jpy"] and ex["formula"] and ex["inputs"]
    put = ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 90000}}))
    assert put["created"] and put["scenario"]["version"] == 2


def test_analyses_list_and_unknown_ids(client: TestClient, aid: str) -> None:
    rows = ok(client.get("/analyses"))
    assert [(r["id"], r["status"], r["classes"]) for r in rows] == [(aid, "done", 20)]
    for path in ("/analyses/nope", "/analyses/nope/status", "/analyses/nope/modules", "/analyses/nope/scenario", "/analyses/nope/recommendation"):
        err(client.get(path), 404, "not_found")
    err(client.get("/no-such-route"), 404)


# --- scenario versions ----------------------------------------------------------------------------------------------------------

def test_a_scenario_put_changes_the_results_and_creates_a_new_version(client: TestClient, aid: str) -> None:
    before = ok(client.get(f"/analyses/{aid}/recommendation"))
    base_cost = before["recommendation"]["work_packages"]["order/cycle-1"]["options"][3]["migration_cost_jpy"]
    put = ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 160000}}))
    assert put["created"] is True and put["changed_fields"] == ["assumptions.daily_rate_jpy"]
    assert put["scenario"]["version"] == 2 and [v["version"] for v in put["scenario"]["versions"]] == [1, 2]
    assert put["run"]["scenario_version"] == 2 and put["run"]["run_id"] != before["run"]["run_id"] and put["run"]["cache_hit"] is False
    after = ok(client.get(f"/analyses/{aid}/recommendation"))
    new_cost = after["recommendation"]["work_packages"]["order/cycle-1"]["options"][3]["migration_cost_jpy"]
    assert new_cost == pytest.approx(base_cost * 2, rel=1e-3)  # day rate 80,000 -> 160,000
    assert ok(client.get(f"/analyses/{aid}/roadmap"))["roadmap"]["economics"] != ok(client.get(f"/analyses/{aid}/roadmap?version=1"))["roadmap"]["economics"]
    old = ok(client.get(f"/analyses/{aid}/recommendation?version=1"))  # old versions stay readable and unchanged
    assert old["recommendation"]["work_packages"]["order/cycle-1"]["options"][3]["migration_cost_jpy"] == base_cost
    assert ok(client.get(f"/analyses/{aid}/scenario?version=1"))["state"]["assumptions"] == {}
    assert ok(client.get(f"/analyses/{aid}/scenario"))["state"]["assumptions"] == {"daily_rate_jpy": 160000}
    err(client.get(f"/analyses/{aid}/scenario?version=9"), 404)


def test_a_put_that_changes_nothing_creates_no_version(client: TestClient, aid: str) -> None:
    current = ok(client.get(f"/analyses/{aid}/scenario"))["state"]["priorities"]
    put = ok(client.put(f"/analyses/{aid}/scenario", json={"priorities": current}))
    assert put["created"] is False and put["changed_fields"] == [] and put["scenario"]["version"] == 1


def test_overrides_and_client_maintenance_are_versioned_scenario_inputs(client: TestClient, aid: str) -> None:
    put = ok(client.put(f"/analyses/{aid}/scenario", json={
        "criticality_overrides": {"common": {"criticality": 3, "reason": "From client interview: shared by every module"}},
        "client_reported_maintenance_jpy": {"billing": 1_000_000}}))
    assert put["scenario"]["state"]["criticality_overrides"]["common"]["criticality"] == 3
    rec = ok(client.get(f"/analyses/{aid}/recommendation"))["recommendation"]
    assert rec["modules"]["common"]["criticality"]["source"] == "override"
    assert rec["modules"]["billing"]["maintenance_calibration"]["applied"] is True
    removed = ok(client.put(f"/analyses/{aid}/scenario", json={"criticality_overrides": {"common": None}}))
    assert "common" not in removed["scenario"]["state"]["criticality_overrides"]


# --- what-if ---------------------------------------------------------------------------------------------------------------------

def test_whatif_persists_nothing_and_diffs_against_the_current_scenario(app: FastAPI, client: TestClient, aid: str) -> None:
    ok(client.get(f"/analyses/{aid}/roadmap"))  # warm the current run's cached documents so counting rows is meaningful
    before = counts(app)
    r = ok(client.post(f"/analyses/{aid}/whatif", json={"priorities": {"cost": 0.1, "risk": 0.1, "speed": 0.1, "long_term_value": 0.7},
                                                         "profile": "client_scenario"}))
    assert counts(app) == before and r["persisted"] is False and r["cache_hit"] is False
    assert r["scenario_changes"] == ["priorities.cost", "priorities.risk", "priorities.long_term_value"]  # speed stays at 0.1
    assert r["current"]["profile"] == r["whatif"]["profile"] == "client_scenario"
    changed = r["diff"]["changed_picks"]
    assert changed and all(c["before"] != c["after"] for c in changed)  # long-term value weight 0.7 changes real picks
    assert r["diff"]["delta"]["migration_cost_jpy"] == r["whatif"]["migration_cost_jpy"] - r["current"]["migration_cost_jpy"]
    assert r["diff"]["delta"]["npv_vs_retain_jpy"] == r["whatif"]["npv_vs_retain_jpy"] - r["current"]["npv_vs_retain_jpy"]
    assert len(ok(client.get(f"/analyses/{aid}/scenario"))["versions"]) == 1  # no version was created


def test_whatif_and_the_equivalent_put_give_the_same_numbers(client: TestClient, aid: str) -> None:
    edit = {"budget_ceiling_jpy": 20_000_000, "profile": "long_term_value"}
    w = ok(client.post(f"/analyses/{aid}/whatif", json=edit))
    ok(client.put(f"/analyses/{aid}/scenario", json={"budget_ceiling_jpy": 20_000_000}))
    road = ok(client.get(f"/analyses/{aid}/roadmap?profile=long_term_value"))["roadmap"]
    assert w["whatif"]["migration_cost_jpy"] == road["portfolio"]["constrained"]["total_migration_cost_jpy"]
    assert w["whatif"]["npv_vs_retain_jpy"] == road["economics"]["npv_vs_retain_jpy"]
    assert w["whatif"]["strategy_by_package"] == {c["package_id"]: c["strategy"] for c in road["portfolio"]["constrained"]["choices"]}


def test_whatif_validates_like_put(client: TestClient, aid: str) -> None:
    err(client.post(f"/analyses/{aid}/whatif", json={"priorities": {"cost": 0.9, "risk": 0.9, "speed": 0.0, "long_term_value": 0.0}}), 422, "validation_error")
    err(client.post(f"/analyses/{aid}/whatif", json={"profile": "bogus", "budget_ceiling_jpy": 30_000_000}), 422, "unknown_profile")
    err(client.post(f"/analyses/{aid}/whatif", json={}), 422)


# --- cache -------------------------------------------------------------------------------------------------------------------------

def test_the_cache_is_hit_on_identical_inputs(app: FastAPI, client: TestClient, aid: str) -> None:
    first = ok(client.get(f"/analyses/{aid}/recommendation"))["run"]
    again = ok(client.get(f"/analyses/{aid}/recommendation"))["run"]
    assert again["run_id"] == first["run_id"] and again["cache_hit"] is True
    changed = ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 99000}}))
    assert changed["run"]["cache_hit"] is False
    runs_after_change = counts(app)[2]
    back = ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 80000}}))  # same effective inputs as v1
    assert back["created"] is True and back["scenario"]["version"] == 3  # a new scenario version...
    assert back["run"]["cache_hit"] is True and back["run"]["run_id"] == first["run_id"]  # ...but the cached run is reused
    assert counts(app)[2] == runs_after_change
    w = ok(client.post(f"/analyses/{aid}/whatif", json={"assumptions": {"daily_rate_jpy": 99000}}))
    assert w["cache_hit"] is True and w["diff"]["changed_picks"] == [] or w["cache_hit"] is True


def test_ids_are_stable_for_identical_inputs(client: TestClient, aid: str) -> None:
    a = ok(client.get(f"/analyses/{aid}/recommendation"))["run"]["number_id_prefix"]
    ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 99000}}))
    ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 80000}}))
    assert ok(client.get(f"/analyses/{aid}/recommendation"))["run"]["number_id_prefix"] == a


# --- demo mode ---------------------------------------------------------------------------------------------------------------------

def test_demo_mode_blocks_posting_and_serves_preloaded_analyses(tmp_path: Path, fixture_json: str) -> None:
    write_demo(tmp_path / "demo", fixture_json)
    app = create_app(make_settings(tmp_path, demo_mode=True))
    with TestClient(app) as c:  # entering the context runs the start-up seeding
        assert ok(c.get("/health")) == {"status": "ok", "mode": "demo"}
        err(c.post("/analyses", json={"repo": str(FIXTURE)}), 403, "demo_mode")
        assert [a["id"] for a in ok(c.get("/analyses"))] == ["legacy-sample"]
        assert ok(c.get("/analyses/legacy-sample/recommendation"))["run"]["scenario_version"] == 1
        assert ok(c.get("/analyses/legacy-sample/roadmap"))["roadmap"]["items"]
        assert ok(c.put("/analyses/legacy-sample/scenario", json={"budget_ceiling_jpy": 40_000_000}))["created"]  # editing is allowed
    full = TestClient(create_app(make_settings(tmp_path / "other")))
    assert ok(full.get("/health"))["mode"] == "full" and ok(full.get("/analyses")) == []  # nothing is seeded outside demo mode


def test_seeding_is_idempotent(tmp_path: Path, fixture_json: str) -> None:
    from api.app.seed import seed_demo

    write_demo(tmp_path / "demo", fixture_json)
    app = create_app(make_settings(tmp_path), seed=False)
    assert seed_demo(app.state.svc, app.state.settings, wait=True) == ["legacy-sample"]
    assert seed_demo(app.state.svc, app.state.settings, wait=True) == []


def test_the_committed_demo_data_is_small_and_loads(tmp_path: Path) -> None:
    from api.app.seed import seed_demo

    demo = ROOT / "data" / "demo"
    assert (demo / "ofbiz.json.gz").stat().st_size < 500_000 and (demo / "legacy-sample.json.gz").exists()
    app = create_app(make_settings(tmp_path, demo_dir=demo), seed=False)
    assert sorted(seed_demo(app.state.svc, app.state.settings, wait=True)) == ["legacy-sample", "ofbiz"]
    with TestClient(app) as c:
        assert ok(c.get("/analyses/ofbiz"))["totals"]["main_java_classes"] == 132


# --- validation ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body,code,needle", [
    ({"priorities": {"cost": 0.5, "risk": 0.5, "speed": 0.5, "long_term_value": 0.5}}, "validation_error", "sum to 1"),
    ({"priorities": {"cost": 1.2, "risk": -0.2, "speed": 0.0, "long_term_value": 0.0}}, "validation_error", ""),
    ({"budget_ceiling_jpy": 10}, "validation_error", "budget_ceiling_jpy"),
    ({"planning_horizon_years": 0}, "validation_error", "planning_horizon_years"),
    ({"assumptions": {"daily_rate_jpy": 5}}, "validation_error", "between"),
    ({"assumptions": {"daily_rate_jpy": 1e9}}, "validation_error", "between"),
    ({"assumptions": {"tco.discount_rate": 0.9}}, "validation_error", "between"),
    ({"assumptions": {"made.up.key": 1}}, "validation_error", "not an editable assumption"),
    ({"assumptions": {"daily_rate_jpy": None}}, "validation_error", "cannot be null"),
    ({"criticality_overrides": {"order": {"criticality": 5, "reason": "valid long reason"}}}, "validation_error", ""),
    ({"criticality_overrides": {"order": {"criticality": 3, "reason": "short"}}}, "validation_error", ""),
    ({"criticality_overrides": {"nonexistent": {"criticality": 3, "reason": "valid long reason"}}}, "validation_error", "unknown module"),
    ({"client_reported_maintenance_jpy": {"order": -5}}, "validation_error", ""),
    ({"client_reported_maintenance_jpy": {"nonexistent": 5}}, "validation_error", "unknown module"),
    ({"max_cutover_downtime_hours": {"order": -1}}, "validation_error", ""),
    ({"objective_weights": {"maintenance_cost": 1.0}}, "validation_error", "must cover exactly"),
    ({"analysed_scope_share": 0}, "validation_error", ""),
    ({"change_requests_per_year": {"order": 99999}}, "validation_error", ""),
    ({}, "validation_error", "changes nothing"),
])
def test_invalid_scenario_edits_are_rejected_with_one_error_format(client: TestClient, aid: str, body: dict[str, Any], code: str, needle: str) -> None:
    e = err(client.put(f"/analyses/{aid}/scenario", json=body), 422, code)
    assert needle in json.dumps(e)
    assert len(ok(client.get(f"/analyses/{aid}/scenario"))["versions"]) == 1  # a rejected edit never creates a version


@pytest.mark.parametrize("repo", ["file:///etc", "http://github.com/a/b", "ssh://git@github.com/a/b", "https://user:pw@github.com/a/b",
                                  "https://github.com/a b", "relative/path", "-oProxyCommand=x", "/definitely/not/there"])
def test_unsafe_or_invalid_repos_are_refused(client: TestClient, repo: str) -> None:
    r = client.post("/analyses", json={"repo": repo})
    assert r.status_code in (403, 422)
    assert r.json()["error"]["code"] in ("invalid_repo", "path_not_allowed", "validation_error")


def test_paths_outside_the_allowed_roots_scope_and_name_are_refused(client: TestClient) -> None:
    err(client.post("/analyses", json={"repo": str(ROOT / "api")}), 403, "path_not_allowed")
    err(client.post("/analyses", json={"repo": str(FIXTURE), "scope": ["../secrets"]}), 422, "invalid_scope")
    err(client.post("/analyses", json={"repo": str(FIXTURE), "scope": ["/etc"]}), 422, "invalid_scope")
    err(client.post("/analyses", json={"repo": str(FIXTURE), "name": "bad name!"}), 422, "invalid_name")
    err(client.post("/analyses", json={}), 422, "validation_error")


def test_a_failing_analysis_job_reports_failed_with_a_reason(client: TestClient) -> None:
    created = ok(client.post("/analyses", json={"repo": str(FIXTURE), "scope": ["no-such-dir"]}), 202)
    s = ok(client.get(f"/analyses/{created['id']}/status"))
    assert s["status"] == "failed" and s["message"]
    err(client.get(f"/analyses/{created['id']}/modules"), 409, "analysis_not_ready")


def test_the_analysis_time_limit_is_enforced(tmp_path: Path) -> None:
    c = TestClient(create_app(make_settings(tmp_path, analysis_timeout_s=0.001)))
    created = ok(c.post("/analyses", json={"repo": str(FIXTURE)}), 202)
    s = ok(c.get(f"/analyses/{created['id']}/status"))
    assert s["status"] == "failed" and "timed out" in s["message"]


def test_the_class_limit_is_enforced(tmp_path: Path) -> None:
    c = TestClient(create_app(make_settings(tmp_path, max_classes=5)))
    s = ok(c.get(f"/analyses/{ok(c.post('/analyses', json={'repo': str(FIXTURE)}), 202)['id']}/status"))
    assert s["status"] == "failed" and "exceed the limit" in s["message"]


def test_unknown_profiles_and_sort_keys_are_rejected(client: TestClient, aid: str) -> None:
    err(client.get(f"/analyses/{aid}/recommendation?profile=bogus"), 422, "unknown_profile")
    err(client.get(f"/analyses/{aid}/roadmap?profile=bogus"), 422, "unknown_profile")
    err(client.get(f"/analyses/{aid}/classes?sort_by=nope"), 422)
    err(client.get(f"/analyses/{aid}/classes?limit=0"), 422)
    err(client.get(f"/analyses/{aid}/graph?level=galaxy"), 422)


# --- results: profiles and roadmap ----------------------------------------------------------------------------------------------------

def test_the_profile_parameter_selects_one_profile_without_changing_number_ids(client: TestClient, aid: str) -> None:
    a = ok(client.get(f"/analyses/{aid}/recommendation?profile=minimize_cost"))
    b = ok(client.get(f"/analyses/{aid}/recommendation?profile=long_term_value"))
    wa, wb = a["recommendation"]["work_packages"]["order/cycle-1"], b["recommendation"]["work_packages"]["order/cycle-1"]
    assert list(wa["choices"]) == ["minimize_cost"] and list(wb["choices"]) == ["long_term_value"]
    assert a["run"]["run_id"] == b["run"]["run_id"] and a["run"]["number_id_prefix"] == b["run"]["number_id_prefix"]
    assert set(a["recommendation"]["estate"]) == set(b["recommendation"]["estate"])  # estate totals for all profiles stay
    rd = ok(client.get(f"/analyses/{aid}/roadmap?profile=long_term_value"))
    assert rd["roadmap"]["meta"]["profile"] == "long_term_value" and rd["run"]["number_id_prefix"].endswith(":roadmap.long_term_value:/")


def test_sensitivity_is_computed_on_demand_and_completes_the_headlines(client: TestClient, aid: str) -> None:
    rec = ok(client.get(f"/analyses/{aid}/recommendation"))
    assert rec["run"]["sensitivity"] == "pending" and rec["recommendation"]["work_packages"]["order/cycle-1"]["breakeven"] is None
    early = ok(client.get(f"/analyses/{aid}/roadmap"))["roadmap"]["headlines"]
    assert "has not been computed" in next(h for h in early if h["id"] == "breakeven_question")["text"]
    s = ok(client.get(f"/analyses/{aid}/sensitivity"))
    assert s["run"]["sensitivity"] == "ready" and set(s["packages"]) == set(rec["recommendation"]["work_packages"])
    assert s["packages"]["order/cycle-1"]["breakeven"]["baseline_jpy_per_year"] > 0
    late = ok(client.get(f"/analyses/{aid}/recommendation"))
    assert late["recommendation"]["work_packages"]["order/cycle-1"]["breakeven"]["chosen"]
    done = ok(client.get(f"/analyses/{aid}/roadmap"))["roadmap"]["headlines"]  # the stale roadmap was refreshed
    assert "has not been computed" not in next(h for h in done if h["id"] == "breakeven_question")["text"]


def test_recompute_after_a_scenario_edit_is_fast_enough_for_sliders(client: TestClient, aid: str) -> None:
    put = ok(client.put(f"/analyses/{aid}/scenario", json={"priorities": {"cost": 0.4, "risk": 0.2, "speed": 0.2, "long_term_value": 0.2}}))
    assert put["run"]["recompute_ms"] < 300  # fixture: tens of milliseconds; OFBiz is measured in docs/api.md


# --- explain -------------------------------------------------------------------------------------------------------------------------

def _docs(app: FastAPI, analysis_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    svc = app.state.svc
    with svc.session() as s:
        run = svc.current_run(s, analysis_id).run
        rec = svc.recommendation_doc(s, run)
        road = svc.roadmap_doc(s, run, CLIENT_PROFILE)
        return run.id, rec, road


def test_every_number_in_a_run_has_a_working_explain_id(app: FastAPI, aid: str) -> None:
    run_id, rec, road = _docs(app, aid)
    checked = specific = 0
    for doc_name, doc in (("rec", rec), (f"roadmap.{CLIENT_PROFILE}", road)):
        for parts in numeric_leaves(doc):
            out = explain_number(make_id(run_id, doc_name, parts), {doc_name: doc}, rec)  # every leaf resolves
            value = doc
            for p in parts:
                value = value[int(p)] if isinstance(value, list) else value[p]
            assert out["value"] == value and out["formula"] and out["label"] and out["kind"]
            assert all(i["name"] and "value" in i for i in out["inputs"])
            assert out["assumptions"] == [] or all("ILLUSTRATIVE" in a["label"] for a in out["assumptions"])
            checked += 1
            specific += out["specific"]
    assert checked > 5000 and specific / checked > 0.35  # thousands of numbers, over a third with a specific formula


def test_explain_over_http_covers_every_kind_of_number(app: FastAPI, client: TestClient, aid: str) -> None:
    run_id, rec, road = _docs(app, aid)
    seen: dict[tuple[str, str], list[str]] = {}
    for doc_name, doc in (("rec", rec), (f"roadmap.{CLIENT_PROFILE}", road)):
        model = {"rec": "Recommendation", "roadmap": "Roadmap"}[doc_name.split(".")[0]]
        from api.app.explain import ROOT_MODELS

        for parts in numeric_leaves(doc):
            owner, field, _ = locate(ROOT_MODELS[{"Recommendation": "rec", "Roadmap": "roadmap"}[model]], parts)
            seen.setdefault((owner, field), []).append(make_id(run_id, doc_name, parts))
    sample = [ids[0] for ids in seen.values()] + random.Random(7).sample([i for ids in seen.values() for i in ids], 150)
    assert len(seen) > 100
    for number_id in sample:
        body = ok(client.get(f"/explain/{number_id}"))
        assert body["id"] == number_id and body["inputs"] is not None


def test_explain_gives_the_formula_inputs_and_contribution(client: TestClient, aid: str) -> None:
    rec = ok(client.get(f"/analyses/{aid}/recommendation"))
    p, wp = rec["run"]["number_id_prefix"], rec["recommendation"]["work_packages"]["order/god-class-cluster-1"]
    comp = wp["health"]["components"][0]
    ex = ok(client.get(f"/explain/{p}work_packages/order~1god-class-cluster-1/health/components/0/contribution_points"))
    assert ex["formula"] == "100 x weight x normalized" and {i["name"] for i in ex["inputs"]} == {"weight", "normalized"}
    assert ex["value"] == comp["contribution_points"]
    assert ex["contribution"]["total"] == pytest.approx(sum(c["contribution_points"] for c in wp["health"]["components"]))
    assert 0 < ex["contribution"]["share_of_total"] <= 1
    inputs = {i["name"]: i for i in ex["inputs"]}  # inputs link to other numbers, so the UI can drill down
    follow = ok(client.get(f"/explain/{inputs['weight']['id']}"))
    assert follow["value"] == comp["weight"]
    option = wp["options"][3]
    ex2 = ok(client.get(f"/explain/{p}work_packages/order~1god-class-cluster-1/options/3/migration_cost_jpy"))
    assert ex2["inputs"][0]["name"] == "effort_days" and ex2["assumptions"][0] == {"key": "daily_rate_jpy", "value": 80000.0, "label": ex2["assumptions"][0]["label"]}
    assert "ILLUSTRATIVE" in ex2["assumptions"][0]["label"] and ex2["value"] == option["migration_cost_jpy"]


def test_explain_roadmap_and_analysis_numbers(client: TestClient, aid: str) -> None:
    road = ok(client.get(f"/analyses/{aid}/roadmap"))
    item = road["roadmap"]["items"][0]
    ex = ok(client.get(f"/explain/{road['run']['number_id_prefix']}items/0/cost_jpy"))
    assert ex["value"] == item["cost_jpy"] and ex["owner_model"] == "Item"
    summary = ok(client.get(f"/analyses/{aid}"))
    cls = ok(client.get(f"/analyses/{aid}/classes/OrderServices"))
    ex2 = ok(client.get(f"/explain/{cls['number_id_prefix']}loc"))
    assert ex2["value"] == cls["metrics"]["loc"] and ex2["kind"] == "measured" and summary["number_id_prefix"].endswith(":analysis:/")


def test_explain_errors(client: TestClient, aid: str) -> None:
    rid = ok(client.get(f"/analyses/{aid}/recommendation"))["run"]["run_id"]
    err(client.get("/explain/not-an-id"), 422, "bad_number_id")
    err(client.get(f"/explain/{rid}:rec:no-slash"), 422, "bad_number_id")
    err(client.get("/explain/deadbeefdeadbeef:rec:/meta"), 404, "not_found")
    err(client.get(f"/explain/{rid}:rec:/meta/analysis_name"), 422, "not_a_number")
    err(client.get(f"/explain/{rid}:rec:/work_packages/nope/loc"), 404, "not_found")
    err(client.get(f"/explain/{rid}:mystery:/x"), 422, "bad_number_id")


def test_number_ids_round_trip() -> None:
    parts = ["work_packages", "order/cycle-1", "options", "3", "tco", "tco_jpy"]
    owner, doc, back = parse_id(make_id("run1", "rec", parts))
    assert (owner, doc, back) == ("run1", "rec", parts)


# --- reading: modules, packages, classes, graph ----------------------------------------------------------------------------------------

def test_modules_packages_and_classes_support_filtering_sorting_and_paging(client: TestClient, aid: str) -> None:
    mods = ok(client.get(f"/analyses/{aid}/modules"))
    assert mods["total"] == 4 and {m["name"] for m in mods["items"]} == {"billing", "common", "order", "party"}
    assert all(m["health_band"] in ("good", "fair", "poor") and m["package_ids"] for m in mods["items"])
    by_health = [m["health"] for m in ok(client.get(f"/analyses/{aid}/modules?sort_by=health&descending=false"))["items"]]
    assert by_health == sorted(by_health)
    assert [m["name"] for m in ok(client.get(f"/analyses/{aid}/modules?has_tests=true"))["items"]] == sorted(
        m["name"] for m in mods["items"] if m["has_tests"])
    assert ok(client.get(f"/analyses/{aid}/modules?min_loc=1000"))["total"] < 4
    pk = ok(client.get(f"/analyses/{aid}/packages?module=order"))
    assert {p["kind"] for p in pk["items"]} == {"cycle", "god_class_cluster", "remainder"} and all(p["module"] == "order" for p in pk["items"])
    assert ok(client.get(f"/analyses/{aid}/packages?kind=god_class_cluster"))["total"] == 1
    cl = ok(client.get(f"/analyses/{aid}/classes?sort_by=loc&limit=3"))
    assert cl["total"] == 20 and cl["items"][0]["name"] == "OrderServices" and len(cl["items"]) == 3
    page2 = ok(client.get(f"/analyses/{aid}/classes?sort_by=loc&limit=3&offset=3"))["items"]
    assert not {c["fqn"] for c in cl["items"]} & {c["fqn"] for c in page2}
    assert [c["name"] for c in ok(client.get(f"/analyses/{aid}/classes?tier=extreme"))["items"]] == ["OrderServices"]
    assert ok(client.get(f"/analyses/{aid}/classes?q=invoice"))["total"] >= 2
    assert all(c["module"] == "billing" and not c["used"] for c in ok(client.get(f"/analyses/{aid}/classes?module=billing&used=false"))["items"])
    assert all(c["package_id"] == "order/cycle-1" for c in ok(client.get(f"/analyses/{aid}/classes?package=order/cycle-1"))["items"])


def test_class_detail_has_metrics_findings_with_evidence_and_edges(client: TestClient, aid: str) -> None:
    d = ok(client.get(f"/analyses/{aid}/classes/OrderServices"))
    assert d["metrics"]["fqn"] == "com.example.legacy.order.OrderServices" and d["metrics"]["size_tier"] == "extreme"
    god = next(f for f in d["findings"] if f["kind"] == "god_class")
    assert god["file"].endswith("OrderServices.java") and god["line"] and god["tier"] == "extreme"  # evidence: file and line
    assert d["db_coupling"] and all(i["line"] > 0 and i["file"].endswith("OrderServices.java") for i in d["db_coupling"])
    assert any(m["analyzed"] and m["service"] == "createOrder" for m in d["services"]) and d["controllers"]
    assert {e["name"] for e in d["depends_on"]} >= {"OrderReadHelper", "PartyService"} and d["depended_on_by"] == []
    assert any(m["import_"].startswith("javax.ejb") for m in d["legacy_markers"])
    by_fqn = ok(client.get(f"/analyses/{aid}/classes/com.example.legacy.billing.InvoiceService"))
    assert by_fqn["metrics"]["name"] == "InvoiceService" and by_fqn["depended_on_by"]
    err(client.get(f"/analyses/{aid}/classes/NoSuchClass"), 404, "not_found")


def test_the_graph_is_react_flow_shaped_with_bands_and_a_node_cap(client: TestClient, aid: str) -> None:
    for level, expected in (("module", 4), ("package", 8), ("class", 20)):
        g = ok(client.get(f"/analyses/{aid}/graph?level={level}"))
        assert g["level"] == level and len(g["nodes"]) == expected and g["total_nodes"] == expected and g["truncated"] is False
        ids = {n["id"] for n in g["nodes"]}
        for n in g["nodes"]:
            assert n["type"] == level and set(n["position"]) == {"x", "y"} and n["data"]["band"] in ("good", "fair", "poor") and n["data"]["label"]
            assert (n["data"]["band"] == "good") == (n["data"]["health"] >= 60)
        assert g["edges"] and all(e["source"] in ids and e["target"] in ids and e["data"]["weight"] >= 1 for e in g["edges"])
    capped = ok(client.get(f"/analyses/{aid}/graph?level=class&limit=5"))
    assert len(capped["nodes"]) == 5 and capped["truncated"] is True and capped["total_nodes"] == 20
    ids = {n["id"] for n in capped["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in capped["edges"])  # no dangling edges after the cap
    assert {n["data"]["label"] for n in capped["nodes"]} >= {"OrderServices"}  # the cap keeps the highest-scoring nodes
    focus = ok(client.get(f"/analyses/{aid}/graph?level=package&module=order"))
    assert {n["data"]["module"] for n in focus["nodes"]} == {"order"}
    layers = ok(client.get(f"/analyses/{aid}/graph?level=module"))
    x = {n["id"]: n["position"]["x"] for n in layers["nodes"]}
    assert x["common"] == 0  # leaves are drawn first (leftmost)


# --- presets, assumptions, contract ---------------------------------------------------------------------------------------------------

def test_presets_and_assumptions_are_described_and_labelled_illustrative(client: TestClient, aid: str) -> None:
    presets = ok(client.get("/presets"))
    assert {p["name"] for p in presets} == {"minimize_cost", "minimize_risk", "speed_to_market", "long_term_value", "balanced", "client_scenario"}
    for p in presets:
        assert p["description"] and "ILLUSTRATIVE" in p["illustrative"]
        assert sum(p["weights"].values()) == pytest.approx(1.0)
    a = ok(client.get("/assumptions"))
    assert "ILLUSTRATIVE" in a["illustrative"] and len(a["items"]) >= 25
    keys = {i["key"] for i in a["items"]}
    assert {"daily_rate_jpy", "base_days_per_kloc.rearchitect", "tco.discount_rate", "roadmap.teams", "roadmap.yearly_budget_cap_jpy"} <= keys
    for i in a["items"]:
        assert i["description"] and i["unit"] and "ILLUSTRATIVE" in i["illustrative"] and i["minimum"] <= (i["default"] or i["minimum"]) <= i["maximum"]
    ok(client.put(f"/analyses/{aid}/scenario", json={"assumptions": {"daily_rate_jpy": 91000, "roadmap.teams": 3}}))
    cur = {i["key"]: i for i in ok(client.get(f"/assumptions?analysis_id={aid}"))["items"]}
    assert cur["daily_rate_jpy"]["current"] == 91000 and cur["daily_rate_jpy"]["default"] == 80000 and cur["roadmap.teams"]["current"] == 3
    assert ok(client.get(f"/analyses/{aid}/roadmap"))["roadmap"]["meta"]["teams"] == 3  # a roadmap assumption reaches the roadmap


def test_cors_allows_the_local_web_app_and_a_configured_origin(tmp_path: Path) -> None:
    c = TestClient(create_app(make_settings(tmp_path, cors_origins=["http://localhost:3000", "https://rearch.example.com"])))
    for origin, allowed in (("http://localhost:3000", True), ("https://rearch.example.com", True), ("https://evil.example.com", False)):
        r = c.options("/analyses", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert (r.headers.get("access-control-allow-origin") == origin) is allowed


def test_the_openapi_contract_lists_every_endpoint(app: FastAPI) -> None:
    spec = app.openapi()
    paths = set(spec["paths"])
    assert {"/analyses", "/analyses/{analysis_id}", "/analyses/{analysis_id}/status", "/analyses/{analysis_id}/modules", "/analyses/{analysis_id}/packages",
            "/analyses/{analysis_id}/classes", "/analyses/{analysis_id}/classes/{name}", "/analyses/{analysis_id}/graph", "/analyses/{analysis_id}/scenario",
            "/analyses/{analysis_id}/recommendation", "/analyses/{analysis_id}/roadmap", "/analyses/{analysis_id}/whatif", "/analyses/{analysis_id}/sensitivity",
            "/explain/{number_id}", "/presets", "/assumptions", "/health"} <= paths
    schemas = spec["components"]["schemas"]
    assert {"Recommendation", "Roadmap", "ErrorResponse", "ScenarioEdit", "ScenarioState", "WhatIfResponse"} <= set(schemas)
    assert spec["paths"]["/analyses/{analysis_id}/scenario"]["put"]["requestBody"]


def test_the_environment_flags_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.app.settings import Settings

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("CORS_ORIGIN", "https://a.example.com, https://b.example.com")
    s = Settings.from_env()
    assert s.demo_mode is True and s.cors_origins == ["http://localhost:3000", "https://a.example.com", "https://b.example.com"]
    monkeypatch.delenv("DEMO_MODE")
    assert Settings.from_env().demo_mode is False


# --- background sensitivity: separate process, debounced, latest run only -------------------------------------------------------------

def test_background_sensitivity_runs_in_another_process_and_skips_superseded_runs(tmp_path: Path, fixture_json: str) -> None:
    import os
    import time

    app = create_app(make_settings(tmp_path, precompute_sensitivity=True, sensitivity_executor="process", sensitivity_debounce_s=0.6))
    svc = app.state.svc
    with TestClient(app) as c:
        with svc.session() as s:
            row = Analysis(id="demo", name="legacy-sample", source="user", status="done")
            s.add(row)
            s.commit()
            svc.store_analysis(s, row, fixture_json)
        runs = []
        for rate in (81000, 82000, 83000):  # a burst of slider edits: three versions, three runs
            runs.append(ok(c.put("/analyses/demo/scenario", json={"assumptions": {"daily_rate_jpy": rate}}))["run"]["run_id"])
        assert len(set(runs)) == 3
        deadline = time.time() + 60
        while time.time() < deadline and ok(c.get("/analyses/demo/recommendation"))["run"]["sensitivity"] != "ready":
            time.sleep(0.25)
        assert ok(c.get("/analyses/demo/recommendation"))["run"]["sensitivity"] == "ready"  # the latest run got its breakevens
        with svc.session() as s:
            ready = [r for r in runs if svc.sensitivity_ready(s, r)]
        assert ready == [runs[-1]]  # earlier runs of the burst were superseded and never computed
        assert svc._executor is not None and os.getpid() not in [p.pid for p in svc._executor._processes.values()]


def test_the_sensitivity_endpoint_waits_for_the_process_pool(tmp_path: Path, fixture_json: str) -> None:
    app = create_app(make_settings(tmp_path, sensitivity_executor="process"))
    svc = app.state.svc
    with TestClient(app) as c:
        with svc.session() as s:
            row = Analysis(id="demo", name="legacy-sample", source="user", status="done")
            s.add(row)
            s.commit()
            svc.store_analysis(s, row, fixture_json)
        body = ok(c.get("/analyses/demo/sensitivity"))
        assert body["run"]["sensitivity"] == "ready" and body["packages"]["order/cycle-1"]["breakeven"]["baseline_jpy_per_year"] > 0
