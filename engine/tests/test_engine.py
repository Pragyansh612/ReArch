"""Phase 3 tests: every number reconstructs from its breakdown; assumptions move results the right way."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analyzer.analyze import analyze
from analyzer.config import load_config
from analyzer.schema import AnalysisResult
from engine.__main__ import main as cli_main
from engine.config import (
    CRITERIA,
    EngineConfig,
    Override,
    Priorities,
    load_overrides,
    parse_profile,
)
from engine.recommend import recommend
from engine.schema import Recommendation, StrategyOption
from engine.scoring import goodness
from engine.sensitivity import _reweighted
from engine.tests.conftest import FIXTURE

PRESETS = ["minimize_cost", "minimize_risk", "speed_to_market", "long_term_value", "balanced"]


def eligible(rec: Recommendation, module: str) -> list[StrategyOption]:
    return [o for o in rec.modules[module].options if o.eligible]


# --- every number has a breakdown that reconstructs it exactly -----------------------------------------

def test_health_reconstructs_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    for name, m in rec.modules.items():
        h = m.health
        assert sum(c.weight for c in h.components) == pytest.approx(1.0), name
        for c in h.components:
            assert c.contribution_points == round(100.0 * c.weight * c.normalized, 4), (name, c.key)
            assert 0.0 <= c.normalized <= 1.0
        assert h.score == round(100.0 - sum(c.contribution_points for c in h.components), 4), name
        assert set(h.top_drivers) <= {c.key for c in h.components} and len(h.top_drivers) == 3
        ranked = sorted(h.components, key=lambda c: (-c.contribution_points, c.key))
        assert h.top_drivers == [c.key for c in ranked[:3]]


def test_health_components_use_configured_weights(rec: Recommendation, cfg: EngineConfig) -> None:
    for m in rec.modules.values():
        assert {c.key: c.weight for c in m.health.components} == cfg.health.weights


def test_effort_cost_duration_reconstruct_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    for name, m in rec.modules.items():
        for o in eligible(rec, name):
            assert o.effort_days == round(sum(line.days for line in o.effort_lines), 4)
            assert o.cost_jpy == round(o.effort_days * cfg.daily_rate_jpy)
            assert isinstance(o.cost_jpy, int)
            assert o.team_size == cfg.team_size[o.strategy]
            assert o.duration_months == round(o.effort_days / (o.team_size * cfg.working_days_per_month), 4)
            core = o.effort_lines[0]
            mult = o.multipliers
            assert core.days == round(m.kloc * cfg.base_days_per_kloc[o.strategy] * mult["complexity_multiplier"]
                                      * (1.0 + mult["test_overhead"]) * mult["uncertainty_buffer"], 4)
            assert mult["uncertainty_buffer"] == cfg.coverage_uncertainty_buffer[m.confidence]


def test_risk_and_value_reconstruct_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    for name, m in rec.modules.items():
        for o in eligible(rec, name):
            for p in o.risk_components:
                assert p.contribution == round(p.weight * p.measure, 4)
            exposure = sum(p.contribution for p in o.risk_components)
            assert o.base_risk == cfg.risk.base[o.strategy]
            assert o.risk_score == round(min(100.0, cfg.risk.base[o.strategy] * (1.0 + cfg.risk.exposure_gain * exposure)), 4)
            maintenance = min(100.0, 100.0 * m.kloc / cfg.long_term_value.maintenance_kloc_cap)
            burden = round(cfg.long_term_value.debt_weight * (100.0 - m.health.score)
                           + (1.0 - cfg.long_term_value.debt_weight) * maintenance, 4)
            assert o.burden == burden
            assert o.long_term_value == round(cfg.long_term_value.debt_reduction[o.strategy] * burden, 4)


def test_risk_measures_come_from_module_facts(rec: Recommendation) -> None:
    for m in rec.modules.values():
        o = eligible(rec, m.module)[0]
        measures = {p.key: p.measure for p in o.risk_components}
        assert measures["health"] == pytest.approx(1.0 - m.health.score / 100.0, abs=1e-6)
        assert measures["criticality"] == (m.criticality.value - 1) / 2.0


def test_scores_reconstruct_exactly(rec: Recommendation, cfg: EngineConfig) -> None:
    for name, m in rec.modules.items():
        raw = {o.strategy: o for o in m.options}
        for choice in m.choices.values():
            assert sum(getattr(choice.weights, c) for c in CRITERIA) == pytest.approx(1.0)
            for s in choice.ranking:
                assert s.score == round(sum(c.contribution for c in s.criteria), 4), (name, s.strategy)
                for c in s.criteria:
                    assert c.contribution == round(100.0 * c.weight * c.goodness, 4)
                    assert c.goodness == round(goodness(c.criterion, c.raw, cfg), 6)
                    source = {"cost": raw[s.strategy].cost_jpy, "risk": raw[s.strategy].risk_score,
                              "speed": raw[s.strategy].duration_months,
                              "long_term_value": raw[s.strategy].long_term_value}[c.criterion]
                    assert c.raw == source
            assert choice.chosen == choice.ranking[0].strategy
            assert choice.score == choice.ranking[0].score
            assert choice.runner_up == choice.ranking[1].strategy
            assert choice.margin == round(choice.score - choice.ranking[1].score, 4)


def test_criticality_and_hotspot_scores_reconstruct(rec: Recommendation, cfg: EngineConfig) -> None:
    for m in rec.modules.values():
        i = m.criticality.inputs
        assert i.inbound_total == i.java_cross_module_fan_in + i.service_fan_in + i.controller_fan_in
        assert i.score == round(cfg.criticality.inbound_weight * i.inbound_share
                                + cfg.criticality.write_weight * i.write_share, 6)
    assert sum(m.criticality.inputs.inbound_share for m in rec.modules.values()) == pytest.approx(1.0, abs=1e-4)
    for h in rec.hotspots:
        assert h.score == round(sum(c.contribution for c in h.components), 4)
        assert all(c.contribution == round(c.weight * c.value, 4) for c in h.components)
    assert [h.score for h in rec.hotspots] == sorted((h.score for h in rec.hotspots), reverse=True)
    assert rec.hotspots[0].fqn.endswith("OrderReadHelper") or rec.hotspots[0].fqn.endswith("OrderServices")


def test_estate_totals_are_sums_of_the_chosen_options(rec: Recommendation) -> None:
    for profile, est in rec.estate.items():
        chosen = [next(o for o in rec.modules[m].options if o.strategy == s) for m, s in est.strategy_by_module.items()]
        assert est.total_cost_jpy == sum(o.cost_jpy or 0 for o in chosen)
        assert est.total_effort_days == round(sum(o.effort_days or 0 for o in chosen), 4)
        assert est.total_duration_months == round(sum(o.duration_months or 0 for o in chosen), 4)
        assert est.strategy_by_module == {m: r.choices[profile].chosen for m, r in rec.modules.items()}


# --- assumptions move results the right way ---------------------------------------------------------------

def test_raising_daily_rate_raises_cost(analysis: AnalysisResult, cfg: EngineConfig, rec: Recommendation) -> None:
    pricier = recommend(analysis, cfg=cfg.model_copy(update={"daily_rate_jpy": cfg.daily_rate_jpy * 1.5}), overrides={}, sensitivity=False)
    for name in rec.modules:
        for a, b in zip(eligible(rec, name), eligible(pricier, name), strict=True):
            assert b.effort_days == a.effort_days  # effort is rate-independent
            assert b.cost_jpy is not None and a.cost_jpy is not None and b.cost_jpy > a.cost_jpy
    for p in rec.estate:
        assert pricier.estate[p].total_cost_jpy > rec.estate[p].total_cost_jpy


def test_low_confidence_increases_effort(cfg: EngineConfig) -> None:
    high_cfg, low_cfg = load_config(), load_config()
    high_cfg.coverage.high_min_java_share = 0.1
    low_cfg.coverage.high_min_java_share, low_cfg.coverage.medium_min_java_share = 0.95, 0.9
    high = recommend(analyze(FIXTURE, cfg=high_cfg), cfg=cfg, overrides={}, sensitivity=False)
    low = recommend(analyze(FIXTURE, cfg=low_cfg), cfg=cfg, overrides={}, sensitivity=False)
    for name in high.modules:
        assert high.modules[name].confidence == "high" and low.modules[name].confidence == "low"
        for h, lo in zip(eligible(high, name), eligible(low, name), strict=True):
            assert lo.effort_days is not None and h.effort_days is not None and lo.effort_days > h.effort_days
            assert lo.effort_days == pytest.approx(h.effort_days * cfg.coverage_uncertainty_buffer["low"], rel=1e-3)
            assert lo.risk_score is not None and h.risk_score is not None and lo.risk_score > h.risk_score


def test_retire_is_ineligible_for_a_used_module_and_explains_why(rec: Recommendation) -> None:
    for name, m in rec.modules.items():
        retire = next(o for o in m.options if o.strategy == "retire")
        assert not retire.eligible and retire.cost_jpy is None and retire.effort_days is None
        assert retire.ineligible_reason and "in use" in retire.ineligible_reason
        for choice in m.choices.values():
            assert choice.chosen != "retire", name
            assert "retire" not in [s.strategy for s in choice.ranking]


def test_retire_is_allowed_for_an_unused_module_on_every_inbound_type(tmp_path: Path, cfg: EngineConfig) -> None:
    pkg = tmp_path / "src/main/java/com/example/legacy/orphan"
    pkg.mkdir(parents=True)
    (pkg / "Dead.java").write_text("package com.example.legacy.orphan;\npublic class Dead { int f() { return 1; } }\n")
    rec = recommend(analyze(tmp_path, name="orphan"), cfg=cfg, overrides={}, sensitivity=False)
    module = rec.modules["orphan"]
    assert module.inbound_references == {"java_cross_module": 0, "service": 0, "controller": 0}
    retire = next(o for o in module.options if o.strategy == "retire")
    assert retire.eligible and retire.cost_jpy is not None
    assert module.choices["minimize_cost"].chosen == "retire"


def test_a_module_used_only_through_services_or_controllers_cannot_retire(analysis: AnalysisResult, rec: Recommendation) -> None:
    party = rec.modules["party"].inbound_references  # fixture: reached through services.xml and controller.xml
    assert party["service"] > 0 and party["controller"] > 0
    assert not next(o for o in rec.modules["party"].options if o.strategy == "retire").eligible


def test_presets_produce_different_recommendations_on_the_fixture(rec: Recommendation) -> None:
    by_profile = {p: tuple(sorted(rec.estate[p].strategy_by_module.items())) for p in PRESETS}
    assert len(set(by_profile.values())) >= 2
    assert rec.estate["long_term_value"].strategy_by_module != rec.estate["minimize_cost"].strategy_by_module
    assert set(rec.estate) == set(PRESETS)


def test_rearchitect_without_tests_adds_a_safety_net_line(rec: Recommendation) -> None:
    def lines(module: str) -> list[str]:
        return [x.label for x in next(o for o in rec.modules[module].options if o.strategy == "rearchitect").effort_lines]

    assert "Build safety-net tests first" in lines("order")  # no tests
    assert "Build safety-net tests first" not in lines("party")  # has tests
    for strategy in ("rehost", "replatform", "refactor"):
        order_lines = next(o for o in rec.modules["order"].options if o.strategy == strategy).effort_lines
        assert [x.label for x in order_lines] == ["Core work"]


def test_untested_modules_have_the_worst_test_evidence_component(rec: Recommendation) -> None:
    def norm(module: str) -> float:
        return next(c.normalized for c in rec.modules[module].health.components if c.key == "test_evidence")

    assert norm("order") == 1.0 and norm("common") == 1.0
    assert norm("billing") < 1.0 and norm("party") < 1.0


# --- close calls --------------------------------------------------------------------------------------------

def test_close_call_flag_follows_the_configured_margin(analysis: AnalysisResult, cfg: EngineConfig) -> None:
    always = recommend(analysis, cfg=cfg.model_copy(update={"close_call_margin": 1000.0}), overrides={}, sensitivity=False)
    never = recommend(analysis, cfg=cfg.model_copy(update={"close_call_margin": 0.0}), overrides={}, sensitivity=False)
    assert all(c.close_call for m in always.modules.values() for c in m.choices.values())
    assert not any(c.close_call for m in never.modules.values() for c in m.choices.values())


# --- sensitivity: the flip point must actually flip ---------------------------------------------------------

def _recompute(analysis: AnalysisResult, cfg: EngineConfig, parameter: str, value: float, weights: Priorities) -> dict[str, str]:
    if parameter == "daily_rate_jpy":
        cfg = cfg.model_copy(update={"daily_rate_jpy": value})
    elif parameter.startswith("base_days_per_kloc."):
        cfg = cfg.model_copy(update={"base_days_per_kloc": {**cfg.base_days_per_kloc, parameter.split(".")[1]: value}})
    else:
        weights = _reweighted(weights, parameter.split(".")[1], value)
    rec = recommend(analysis, cfg=cfg, profile=_as_profile(weights), overrides={}, sensitivity=False)
    return {m: r.choices[rec.meta.selected_profile].chosen for m, r in rec.modules.items()}


def _as_profile(w: Priorities) -> str:
    return f"cost={w.cost!r},risk={w.risk!r},speed={w.speed!r},long_term_value={w.long_term_value!r}"


def test_every_reported_flip_point_actually_flips(analysis: AnalysisResult, cfg: EngineConfig, rec: Recommendation) -> None:
    selected = cfg.priorities.presets[rec.meta.selected_profile]
    checked = 0
    for name, m in rec.modules.items():
        base = m.choices[rec.meta.selected_profile].chosen
        for f in m.sensitivity:
            if f.flip_value is None:
                continue
            direction = 1.0 if f.flip_value > f.current_value else -1.0
            span = abs(f.flip_value - f.current_value)
            before = f.flip_value - direction * span * 1e-4
            after = f.flip_value + direction * span * 1e-4
            assert _recompute(analysis, cfg, f.parameter, before, selected)[name] == base, (name, f.parameter, "before")
            assert _recompute(analysis, cfg, f.parameter, after, selected)[name] == f.new_strategy, (name, f.parameter)
            assert f.new_strategy != base
            checked += 1
    assert checked > 0


def test_sensitivity_covers_rate_base_days_and_priorities(rec: Recommendation, cfg: EngineConfig) -> None:
    expected = ({"daily_rate_jpy"} | {f"base_days_per_kloc.{s}" for s in cfg.strategies}
                | {f"priority.{c}" for c in CRITERIA})
    for m in rec.modules.values():
        assert {f.parameter for f in m.sensitivity} == expected
        changes = [f.change_pct for f in m.sensitivity if f.change_pct is not None]
        assert changes == sorted(changes)  # smallest change first
        assert all(f.note for f in m.sensitivity)


# --- criticality: the tool proposes, the consultant confirms --------------------------------------------------

def test_override_takes_precedence_over_the_heuristic(analysis: AnalysisResult, cfg: EngineConfig, rec: Recommendation) -> None:
    proposed = rec.modules["common"].criticality
    assert proposed.source == "heuristic" and proposed.override_reason is None
    forced = 1 if proposed.value != 1 else 3
    over = {"common": Override(module="common", criticality=forced, reason="Client confirmed in workshop on 2026-10-01")}
    result = recommend(analysis, cfg=cfg, overrides=over, sensitivity=False)
    c = result.modules["common"].criticality
    assert (c.value, c.source, c.status) == (forced, "override", "confirmed_by_override")
    assert c.heuristic_value == proposed.value and c.override_reason == "Client confirmed in workshop on 2026-10-01"
    assert result.modules["billing"].criticality.source == "heuristic"
    # the overridden value is what the risk model uses
    risk = {p.key: p.measure for p in eligible(result, "common")[0].risk_components}["criticality"]
    assert risk == (forced - 1) / 2.0


def test_override_requires_a_written_reason_and_a_known_module(tmp_path: Path, analysis: AnalysisResult, cfg: EngineConfig) -> None:
    with pytest.raises(ValueError, match="reason"):
        Override(module="order", criticality=3, reason="")
    with pytest.raises(ValueError, match="criticality"):
        Override(module="order", criticality=4, reason="a perfectly good reason")
    with pytest.raises(ValueError, match="unknown modules"):
        recommend(analysis, cfg=cfg, overrides={"nope": Override(module="nope", criticality=2, reason="valid long reason")})
    path = tmp_path / "o.yaml"
    path.write_text("analyses:\n  demo:\n    - module: order\n      criticality: 3\n      reason: Revenue critical per client\n")
    assert load_overrides("demo", path)["order"].criticality == 3
    assert load_overrides("other", path) == {}


# --- priorities -----------------------------------------------------------------------------------------------

def test_priorities_must_sum_to_one(cfg: EngineConfig) -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        Priorities(cost=0.5, risk=0.5, speed=0.5, long_term_value=0.5)
    for name, preset in cfg.priorities.presets.items():
        assert sum(getattr(preset, c) for c in CRITERIA) == pytest.approx(1.0), name
    name, custom = parse_profile("cost=0.4,risk=0.3,speed=0.2,long_term_value=0.1", cfg)
    assert name == "custom" and custom.cost == 0.4
    with pytest.raises(ValueError, match="profile must be"):
        parse_profile("cost=0.9,risk=0.9,speed=0,long_term_value=0", cfg)
    with pytest.raises(ValueError, match="profile must be"):
        parse_profile("nonsense", cfg)


def test_custom_profile_is_included_and_selected(analysis: AnalysisResult, cfg: EngineConfig) -> None:
    result = recommend(analysis, cfg=cfg, profile="cost=0.1,risk=0.1,speed=0.1,long_term_value=0.7", overrides={},
                       sensitivity=False)
    assert result.meta.selected_profile == "custom" and set(result.estate) == set(PRESETS) | {"custom"}
    assert result.estate["custom"].strategy_by_module == result.estate["long_term_value"].strategy_by_module


def test_changing_priorities_changes_the_recommendation(rec: Recommendation) -> None:
    for name, m in rec.modules.items():
        assert m.choices["minimize_cost"].chosen != m.choices["long_term_value"].chosen, name


def test_assumptions_are_echoed_and_labelled_illustrative(rec: Recommendation) -> None:
    assert rec.assumptions["illustrative"] is True and "ILLUSTRATIVE" in rec.assumptions["notice"]
    assert rec.assumptions["config"]["daily_rate_jpy"] == 80000
    assert any("ILLUSTRATIVE" in n for n in rec.meta.notes)


# --- schema and CLI -------------------------------------------------------------------------------------------

def test_recommendation_roundtrips_through_the_schema(rec: Recommendation) -> None:
    assert Recommendation.model_validate_json(rec.model_dump_json()) == rec


def test_cli_writes_recommendation_json(tmp_path: Path) -> None:
    analysis_path = tmp_path / "legacy-sample.json"
    analysis_path.write_text(analyze(FIXTURE, name="legacy-sample").model_dump_json())
    code = cli_main([str(analysis_path), "--profile", "minimize_risk", "--out", str(tmp_path),
                     "--overrides", str(tmp_path / "none.yaml")])
    assert code == 0
    out = json.loads((tmp_path / "legacy-sample.recommendation.json").read_text())
    assert out["meta"]["selected_profile"] == "minimize_risk" and set(out["modules"]) == {"billing", "common", "order", "party"}
    assert cli_main([str(tmp_path / "missing.json")]) == 2
    assert cli_main([str(analysis_path), "--profile", "bogus", "--out", str(tmp_path)]) == 2
