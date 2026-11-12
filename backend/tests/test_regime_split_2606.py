"""Regression 06/2026: Regime als Strategie-Schalter (Trades im eigenen Regime vs. außerhalb)."""
import numpy as np

from services import regime_split as rs

SEGS = {"BTCUSDT": [{"start_ts": i * 1000, "regime": i % 2} for i in range(60)]}


def _rows(mu_in, mu_out, own=0, seed=1):
    rng = np.random.default_rng(seed)
    return [{"symbol": "BTCUSDT", "opened_ts": i * 1000 + 500,
             "pnl": float(rng.normal(mu_in if i % 2 == own else mu_out, 1.0))} for i in range(60)]


def test_regime_at_and_iso_timestamps():
    sp = rs.spans(SEGS)["BTCUSDT"]
    assert rs.regime_at(sp, 500) == 0 and rs.regime_at(sp, 1500) == 1 and rs.regime_at(sp, -1) is None
    assert rs.trade_ts({"opened": "1970-01-01T00:00:02+00:00"}) == 2000 and rs.trade_ts({}) is None


def test_strategy_clearly_better_in_own_regime_is_carried():
    out = rs.evaluate({0: _rows(1.5, -0.5)}, SEGS, {0: "Aufwärts"})
    s = out["strategies"][0]
    assert s["trades_in"] == 30 and s["trades_out"] == 30 and s["t"] > rs.T_GOOD
    assert s["verdict"] == "Regime trägt" and out["ok"] is True and s["label"] == "Aufwärts"


def test_same_everywhere_is_no_difference():
    out = rs.evaluate({0: _rows(0.3, 0.3, seed=4)}, SEGS)
    assert out["strategies"][0]["verdict"] == "kein Unterschied" and out["ok"] is False


def test_too_few_trades_gives_no_verdict():
    out = rs.evaluate({0: _rows(1.5, -0.5)[:8]}, SEGS)
    assert out["strategies"][0]["t"] is None and out["ok"] is False and "kein Urteil" in out["text"]
