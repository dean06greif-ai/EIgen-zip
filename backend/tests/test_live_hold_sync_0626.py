"""Regressionstests 06/2026: Live-Regime = Lab-Regime (Hold-Sperre eingerastet, Makro-Warmup),
Schalter-Vergleich mit/ohne Makro-Filter, KI-Trader blockiert nicht beim Kaltstart, Worker-Standby.
Rein (ohne DB/Netz)."""
import asyncio
import importlib.util
import os
from pathlib import Path

import numpy as np

from services import regime as rg
from services import regime_engine as eng
from services import regime_hold
from services import regime_live_history as lh
from services import regime_macro_filter as mf
from services import regime_opt
from services import regime_lab as lab
from services import structural_regime as sr
from strategies.registry import registry


def _hold(ids, start, hold, cur=None, age=0):
    """Referenz: Hold-Sperre wie in regime_reactive.classify, ab `start` mit Startzustand."""
    out, last = list(ids), start - age
    for i in range(start, len(ids)):
        if cur is None:
            cur, last = ids[i], i
        elif ids[i] != cur and i - last >= hold:
            cur, last = ids[i], i
        out[i] = cur
    return out


def test_sync_index_trivial_cases():
    assert regime_hold.sync_index([1, 1, 2], 0, 1) == 0
    assert regime_hold.sync_index([1, 1, 2], 5, 4) is None
    assert regime_hold.sync_index([0, 1] * 20, 0, 6) is None


def test_sync_index_means_start_independent():
    rng = np.random.default_rng(7)
    for hold in (3, 8, 20):
        ids = np.repeat(rng.integers(0, 3, 120), rng.integers(1, 14, 120))[:900]
        k = regime_hold.sync_index(ids, 0, hold)
        assert k is not None
        ref = _hold(ids, 0, hold)
        for cur in (0, 1, 2, 7):
            for age in (0, hold // 2, hold):
                assert _hold(ids, 0, hold, cur, age)[k:] == ref[k:]


def test_unsynced_window_is_detected():
    hold = 10
    ids = np.array(([0] * 4 + [1] * 4) * 30)          # Wechsel alle 4 Kerzen, Sperre 10
    assert regime_hold.sync_index(ids, 0, hold) is None
    ids2 = np.concatenate([ids, [2] * 25, [0] * 4])    # ruhige Strecke -> rastet ein
    assert regime_hold.sync_index(ids2, 0, hold) is not None


def test_live_history_covers_macro_and_jump_warmup():
    base = eng.resolve_config({"detector": "kombi", "regime_mode": 3}, "4h")
    day = eng.resolve_config({**base, "macro_filter": "soft", "macro_scale": "day"}, "4h")
    week = eng.resolve_config({**base, "macro_filter": "strict", "macro_scale": "week"}, "4h")
    assert mf.live_warmup_bars(base) == 0
    assert mf.live_warmup_bars(day) == 5 * 45 * 6 and mf.live_warmup_bars(week) == 5 * 60 * 6
    assert mf.warmup_bars(day) == 3 * 45 * 6, "Lab-Aufwärmphase (fail-open) bleibt unverändert"
    assert eng.required_history_days(day, 30) >= 225 and eng.required_history_days(week, 30) >= 300
    jump = eng.resolve_config({"detector": "jump", "jump_slow_days": 10, "regime_mode": 3}, "4h")
    assert eng.required_history_days(jump, 30) >= 50


def _candles(days=420, bpd=6, seed=3):
    rng = np.random.default_rng(seed)
    n = days * bpd
    drift = np.repeat(rng.choice([-1, 0, 1], size=n // (bpd * 25) + 1), bpd * 25)[:n] * 0.004
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.012, n)))
    step = 86_400_000 // bpd
    return [{"timestamp": 1_600_000_000_000 + i * step, "open": float(c), "high": float(c * 1.004),
             "low": float(c * 0.996), "close": float(c), "volume": 1.0} for i, c in enumerate(close)]


def test_load_synced_extends_until_label_matches_lab():
    cs = _candles()
    model = eng.build_model({"X": cs}, "4h", {"detector": "jump", "jump_slow_days": 10,
                                              "jump_fast_days": 1, "jump_penalty_days": 0.5,
                                              "regime_mode": 3})
    full = rg.classify_series(model, cs, "4h", 0.7, 2.0)
    base = eng.required_history_days(model["config"], 30)
    lh._DAYS.clear()
    asked = []

    async def load(days):
        asked.append(days)
        return cs[-(days * 6 + 1):]
    candles, days, ok = asyncio.run(lh.load_synced(model, "X", base, load, 2.0))
    assert asked[0] == base and days == asked[-1] <= lh.MAX_DAYS
    if ok:
        assert rg.current_regime(model, candles, "4h", 0.7, 2.0)["regime"] == full[-1]
        asked.clear()
        asyncio.run(lh.load_synced(model, "X", base, load, 2.0))
        assert asked == [days], "gefundene Länge wird gemerkt"
    else:
        assert days == lh.MAX_DAYS


def test_load_synced_legacy_model_unchanged():
    async def load(days):
        return [{"timestamp": i} for i in range(60)]
    candles, days, ok = asyncio.run(lh.load_synced({"centroids": [[0, 0, 0, 0]]}, "Y", 30, load))
    assert days == 30 and ok is None and len(candles) == 60


def test_walkforward_reports_macro_switch_compare(monkeypatch):
    cs = _candles(days=300)
    train_end = cs[len(cs) // 2]["timestamp"]
    model = eng.build_model({"BTCUSDT": cs}, "4h", {"detector": "kombi", "regime_mode": 3})
    rid = model["regimes"][0]["id"]
    doc = {"id": "ra_ms", "timeframe": "4h", "days": 300, "symbols": ["BTCUSDT"],
           "combined": {"model": model}, "bounds": {"BTCUSDT": {"train_end_ts": train_end}},
           "settings": {"train_pct": 50},
           "assignments": {f"combined:{rid}": {"regime_id": rid, "strategy_id": "nnfx_trend",
                                               "regime_label": "R"}}}

    async def fake_hist(*a, **k):
        return {"BTCUSDT": cs}

    async def fake_eval(strategy, segments, *a, **k):
        rows = [{"symbol": "BTCUSDT", "opened_ts": c["timestamp"], "closed": c["timestamp"],
                 "pnl": 1.0, "regime": rid} for c in cs[len(cs) // 2 + 1::8]]
        return {"trades": len(rows), "pnl": float(len(rows)), "win_rate": 100.0}, rows
    monkeypatch.setattr(lab, "fetch_histories", fake_hist)
    monkeypatch.setattr(regime_opt.dyn, "eval_dynamic", fake_eval)
    lab.JOBS["wf_ms"] = {"id": "wf_ms", "status": "running", "cancel": False}
    try:
        asyncio.run(regime_opt.run_walkforward("wf_ms", {"analysis_doc": doc, "scope": "combined"},
                                               registry, {}, {"max_capital": 100}, None))
        job = lab.JOBS["wf_ms"]
        assert job["status"] == "done", job.get("error")
        alt, base = job["result"]["regime_split_macro"], job["result"]["regime_split"]
        assert alt["alt_has_macro"] is True and alt["active_label"] == "kein Makro-Filter"
        assert "Tages-Skala" in alt["macro_label"]
        assert [s["regime"] for s in alt["strategies"]] == [s["regime"] for s in base["strategies"]]
        tot = lambda x: [s["trades_in"] + s["trades_out"] for s in x["strategies"]]  # noqa: E731
        assert tot(alt) == tot(base), "dieselben Trades, nur anders aufgeteilt"
    finally:
        lab.JOBS.pop("wf_ms", None)


def test_structural_resolve_does_not_block_on_cold_history(monkeypatch):
    doc = {"id": "ra_s", "release": {"stage": "active"}}

    async def fake_doc(symbol, band=None):
        return doc

    async def fake_key(symbol, d):
        return symbol

    async def slow(symbol, d):
        await asyncio.sleep(0.3)
        return {"state": "ok", "direction": "up", "label": "x"}

    async def no_record(*a, **k):
        return None
    from services import regime_cockpit
    monkeypatch.setattr(sr, "_doc_for", fake_doc)
    monkeypatch.setattr(sr, "_cache_key", fake_key)
    monkeypatch.setattr(sr, "_compute", slow)
    monkeypatch.setattr(sr, "regime_band", lambda d: "swing")
    monkeypatch.setattr(regime_cockpit, "record_structural", no_record)
    monkeypatch.setattr(sr, "SOFT_TIMEOUT_S", 0.05)
    sr._cache.pop("ZZZUSDT", None)
    sr._locks.pop("ZZZUSDT", None)

    async def run():
        first = await sr.resolve("ZZZUSDT")
        await asyncio.sleep(0.5)
        return first, await sr.resolve("ZZZUSDT")
    try:
        first, second = asyncio.run(run())
        assert first["state"] == "stale", "Kaltstart: Aufrufer bekommt sofort einen vorläufigen Stand"
        assert second["state"] == "ok" and second["direction"] == "up", "Hintergrund füllt den Cache"
    finally:
        sr._cache.pop("ZZZUSDT", None)
        sr._locks.pop("ZZZUSDT", None)


def test_worker_keep_awake_is_safe_off_windows(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "local_worker" / "worker.py"
    src = path.read_text(encoding="utf-8")
    assert "SetThreadExecutionState" in src and "keep_awake()" in src
    start = src.index("def keep_awake")
    ns = {"os": os}
    exec(src[start:src.index("# ---------------- Heartbeat")], ns)  # noqa: S102 – nur die reine Funktion
    if os.name != "nt":
        assert ns["keep_awake"]() is False
    assert importlib.util.find_spec("ctypes") is not None
