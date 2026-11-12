"""Regression 06/2026: handelbarer Edge je Phase, strengere Nutzen-Note, Freigabe-Signifikanz."""
import numpy as np
import pytest

from services import regime_autopilot as ap
from services import regime_edge as edge
from services import regime_release as rr
from services import regime_usefulness as ru
from services import regime_utility


def _market(n=40, leg=30, seed=1):
    rng = np.random.default_rng(seed)
    close, d, p = [], [], 100.0
    for i in range(n):
        s = 1 if i % 2 == 0 else -1
        for _ in range(leg):
            p *= 1 + s * 0.004 + rng.normal(0, 0.002)
            close.append(p)
            d.append(s)
    return close, d


def test_phase_returns_one_trade_per_closed_phase():
    close = [100, 110, 121, 110, 100]
    got = edge.phase_returns(close, [1, 1, 1, -1, -1], cost_pct=0.0)
    assert got == pytest.approx([10.0])          # Einstieg 100, Ausstieg beim Wechsel 110; offene Phase zählt nicht
    assert edge.phase_returns(close, [0, 0, 0, 0, 0]) == []
    assert edge.phase_returns(close, [1, 1, 1, -1, -1], cost_pct=0.5) == pytest.approx([9.5])


def test_edge_lagged_trend_labels_significant_random_not():
    close, d = _market()
    lagged = [d[0]] * 5 + d[:-5]                 # Erkennung 5 Kerzen zu spät – trotzdem Edge
    good = edge.stats(edge.phase_returns(close, lagged))
    assert good["phases"] >= 30 and good["t"] > edge.T_GOOD and good["phase_pct"] > 0
    rng = np.random.default_rng(7)
    rnd = edge.stats(edge.phase_returns(close, list(rng.choice([-1, 1], len(close)))))
    assert rnd["t"] is None or rnd["t"] < edge.T_GOOD
    assert edge.verdict(good["t"]) == "belastbar" and edge.verdict(None) == "zu wenige Phasen"


def test_edge_needs_min_phases_and_splits_train_holdout():
    close, d = _market(n=4)
    assert edge.stats(edge.phase_returns(close, d))["t"] is None
    close, d = _market()
    out = edge.compute(close, d, split=len(close) // 2)
    assert set(out) == {"overall", "train", "holdout"} and out["holdout"]["phases"] > 0


def test_usefulness_stability_without_predictive_value_scores_zero():
    stab = {"avg_phase_days": 30.0, "pingpong_pct": 0.0}
    assert ru.score([{"separation_z": 0.0, "sign_hit_pct": 50.0}], stab) == 0.0      # vorher 35 Punkte
    assert ru.score([{"separation_z": 0.3, "sign_hit_pct": 58.0}], stab) == 100.0


def test_autopilot_score_rewards_train_edge_only():
    m = {"inner_direction_pct": 60.0, "train_direction_pct": 60.0}
    base = ap.score_breakdown(m, 0, 0)
    up = ap.score_breakdown({**m, "edge_train_t": 2.0}, 0, 0)
    down = ap.score_breakdown({**m, "edge_train_t": -9.0}, 0, 0)
    assert base["edge_points"] == 0.0
    assert up["total"] == pytest.approx(base["total"] + 2.0 * ap.EDGE_WEIGHT)
    assert down["total"] == pytest.approx(base["total"] - ap.EDGE_T_CAP * ap.EDGE_WEIGHT)
    assert ap.score_breakdown({**m, "edge_t": 9.0}, 0, 0)["total"] == base["total"]  # Holdout nie im Score


def test_utility_summary_exposes_edge_keys():
    s = regime_utility.summary({"edge": {"train": {"t": 2.5}, "holdout": {"t": 1.2, "phase_pct": 0.8, "phases": 12, "hit_pct": 58.0},
                                         "overall": {"t": 2.0}}})
    assert s["edge_train_t"] == 2.5 and s["edge_t"] == 1.2 and s["edge_basis"] == "holdout" and s["edge_phases"] == 12
    assert regime_utility.summary({})["edge_t"] is None


def test_activation_reports_sampling_noise_without_blocking():
    thin = [{"regime": "bulle", "trades": 10, "avg_reward": 0.3}, {"regime": "bär", "trades": 10, "avg_reward": 0.0}]
    ok, _, info = rr.validate_activation(thin, min_trades=10)
    assert ok is True and info["significant"] is False and info["noise_floor_r"] == 0.89
    solid = [{"regime": "bulle", "trades": 100, "avg_reward": 0.5}, {"regime": "bär", "trades": 100, "avg_reward": 0.0}]
    assert rr.validate_activation(solid, min_trades=10)[2]["significant"] is True
