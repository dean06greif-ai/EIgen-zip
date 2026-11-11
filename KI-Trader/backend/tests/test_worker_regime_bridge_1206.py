"""12/2026: Worker-Kerzen (GOLDUSDT/-1121), Auto-Update, Makro-Check, TF-Kette unter Makro, Copilot-Weg."""
import asyncio

import numpy as np
import pytest

from core import instruments
from services import history_sources as hs
from services import local_exec
from services import notifications
from services import regime_copilot_knowledge as rck
from services import regime_macro_check as mc
from services import regime_tf_chain as tfc
from services import setup_asset_class as ac


def test_canonical_aliases():
    assert instruments.canonical("GOLDUSDT") == "GOLD"
    assert instruments.canonical("xauusdt") == "GOLD"
    assert instruments.canonical("SILVERUSDT") == "SILVER"
    assert instruments.canonical("CLUSDT") == "OIL"
    assert instruments.canonical("BTCUSDT") == "BTCUSDT"
    assert instruments.canonical("QQQUSDT") == "QQQUSDT"
    assert instruments.canonical("FOOUSDT") == "FOOUSDT"


def test_resolve_alias_uses_instrument_source():
    assert hs._resolve("GOLDUSDT") == hs._resolve("GOLD")
    assert hs._resolve("GOLDUSDT")[0] != "binance"
    assert hs.has_backup("GOLDUSDT")
    assert ac.asset_class_of("GOLDUSDT") == ac.asset_class_of("GOLD")


def test_binance_invalid_symbol_fails_fast(monkeypatch):
    calls = []

    async def fake(session, url, params, timeout=30):
        calls.append(url)
        raise RuntimeError('HTTP 400: {"code":-1121,"msg":"Invalid symbol."}')
    monkeypatch.setattr(hs, "_get_json_checked", fake)
    with pytest.raises(hs.SymbolUnavailable):
        asyncio.run(hs.fetch_binance(None, "FOOUSDT", 0, 10 * hs.MINUTE))
    assert len(calls) == 1


def test_unknown_symbol_falls_back_to_bitunix(monkeypatch):
    async def bad(*a, **k):
        raise hs.SymbolUnavailable("x")

    async def bitunix(session, ref, s, e, job=None, pace=0.12):
        return [np.array([[0, 1, 1, 1, 1, 1]], dtype=float)]
    monkeypatch.setitem(hs.SOURCES, "binance", bad)
    monkeypatch.setattr(hs, "fetch_bitunix", bitunix)
    assert len(asyncio.run(hs.fetch_blocks(None, "FOOUSDT", 0, hs.MINUTE))) == 1

    async def none(*a, **k):
        return []
    monkeypatch.setattr(hs, "fetch_bitunix", none)
    with pytest.raises(hs.SymbolUnavailable):
        asyncio.run(hs.fetch_blocks(None, "FOOUSDT", 0, hs.MINUTE))


def test_auto_update_progress_never_cancelled():
    assert asyncio.run(local_exec.apply_progress("auto-abc12345", {"progress": 5})) == {}


def test_notify_config_without_db_is_default():
    notifications._cfg_cache = None
    cfg = asyncio.run(notifications.get_config(None))
    assert cfg == dict(notifications.DEFAULT_CONFIG)


def test_tf_chain_stays_below_macro():
    crypto = mc.macro_minutes(["BTCUSDT"])
    assert crypto == 1440
    assert tfc.build_chain("4h", crypto) == ["4h", "2h", "8h"]
    assert tfc.build_chain("1h") == ["1h", "30m", "2h", "4h"]        # unverändert ohne Deckel
    assert tfc.build_chain("1h", crypto) == ["1h", "30m", "2h", "4h"]
    assert "1d" in tfc.build_chain("8h", mc.macro_minutes(["GOLD"]))  # Rohstoffe: Makro 1w


def test_conflict_and_summary():
    p = np.array([1, 1, -1, 0, -9])
    m = np.array([1, -1, 1, 1, 1])
    assert mc.conflict_pct(p, m) == 50.0
    s = mc.summarize([{"primary": 50, "combined": 48, "conflict_pct": 10}])
    assert s["verdict"] == "use_macro"
    s = mc.summarize([{"primary": 60, "combined": 40, "conflict_pct": 30}])
    assert s["verdict"] == "primary_only"
    assert mc.summarize([])["verdict"] == "unknown"


def _candles(n, step_ms=3_600_000, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n) + 0.0004 * np.sin(np.arange(n) / 300)))
    return [{"timestamp": i * step_ms, "open": c, "high": c * 1.004, "low": c * 0.996,
             "close": c, "volume": 1.0} for i, c in enumerate(close)]


def test_macro_check_evaluate_runs_on_real_engine():
    out = mc.evaluate({"BTCUSDT": _candles(24 * 400)}, {"detector": "kombi", "regime_mode": 3}, "1h")
    assert out is not None and out["macro_tf"] == "1d"
    assert out["verdict"] in ("use_macro", "primary_only", "unknown")
    # Haupt-TF auf/über Makro -> nicht anwendbar
    assert mc.evaluate({"BTCUSDT": _candles(400, 86_400_000)}, {"detector": "kombi"}, "1d") is None


def test_copilot_search_path_and_next_steps():
    txt = rck.static_knowledge()
    assert "DREI EBENEN" in txt and "MAKRO-CHECK" in txt
    assert "noch kein Autopilot-Lauf" in rck.search_lines([])[0]
    run = {"result": {"symbols": ["BTCUSDT"], "timeframe": "2h", "stop_reason": "plateau",
                      "best": {"score": 71.2, "detector": "kombi",
                               "metrics": {"holdout_reference_f1_pct": 53.0}},
                      "tf_chain": {"changed_timeframe": True, "selected_timeframe": "1h"},
                      "macro_check": {"verdict": "use_macro", "primary": 50, "combined": 52,
                                      "conflict_pct": 8}}}
    line = rck.search_lines([run])[0]
    assert "TF 2h (Kette, statt 1h)" in line and "Makro-Check use_macro" in line
    steps = " ".join(rck.next_steps([run], 0))
    assert "Ziel-F1 erreicht" in steps and "Makro-Filter" in steps and "keine Freigabe" in steps


# ---- Abschnitt 0 als Regime-Lab-Job (Haupt-Balken, lokal, Pause/Abbruch) ----
def _assistant_env(monkeypatch, cancel_after=None):
    from services import regime_assistant as ra
    from services import regime_lab as lab
    calls = []

    async def fake_hist(symbols, days, tf, job=None, **k):
        calls.append(symbols[0])
        if cancel_after is not None and len(calls) > cancel_after:
            job["cancel"] = True
        return {symbols[0]: _candles(24 * 200, 3_600_000 * 8)}
    monkeypatch.setattr(lab, "fetch_histories", fake_hist)
    return ra, lab, calls


def test_assistant_job_local_returns_doc(monkeypatch):
    ra, lab, calls = _assistant_env(monkeypatch)
    jid = lab.create_job(ra.JOB_KIND, {"asset_class": "crypto"})
    asyncio.run(ra.run_job(jid, {"asset_class": "crypto", "symbols": ["ETHUSDT", "BTCUSDT"], "days": 365}, None))
    job = lab.JOBS[jid]
    assert job["status"] == "done", job.get("error")
    assert calls[0] == "BTCUSDT"                      # Leitmarkt zuerst
    doc = job["result"]["doc"]
    assert doc["execution"] == "local" and len(doc["results"]) == 2 and doc["summary"]["light"]
    assert ra.running() is None


def test_assistant_job_cancel(monkeypatch):
    ra, lab, _ = _assistant_env(monkeypatch, cancel_after=0)
    jid = lab.create_job(ra.JOB_KIND, {"asset_class": "crypto"})
    asyncio.run(ra.run_job(jid, {"asset_class": "crypto", "symbols": ["BTCUSDT", "ETHUSDT"]}, None))
    assert lab.JOBS[jid]["status"] == "cancelled"


def test_assistant_worker_result_is_persisted(monkeypatch):
    from services import regime_assistant as ra
    from services import regime_lab as lab
    saved = []

    async def fake_persist(db, doc):
        saved.append(doc)
    monkeypatch.setattr(ra, "persist", fake_persist)
    job = {"result": {"kind": "assistant", "doc": {"id": "x", "asset_class": "crypto"}}}
    asyncio.run(lab.persist_worker_result(object(), "x", job))
    assert saved and "doc" not in job["result"]
    assert local_exec.FN_MIN_VERSION["assistant"] == (1, 25)


def test_worker_dispatches_assistant():
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2] / "local_worker" / "worker.py").read_text(encoding="utf-8")
    assert 'fn == "assistant"' in src and "regime_assistant.run_job" in src
    ver = tuple(int(x) for x in re.search(r'VERSION = "([\d.]+)"', src).group(1).split("."))
    assert ver >= (1, 25, 0)


def test_assistant_route_cloud_and_local(monkeypatch):
    from fastapi import HTTPException
    from core import state
    from routers import regime_assistant as rra
    from services import ram_queue
    from services import regime_lab as lab
    submitted = []
    monkeypatch.setattr(state, "db", object(), raising=False)
    monkeypatch.setattr(ram_queue, "submit", lambda jobs, jid, f, kind="": submitted.append(jid) or False)
    monkeypatch.setattr(lab, "JOBS", {})
    d = asyncio.run(rra.run({"asset_class": "forex"}, True))
    assert d["execution"] == "cloud" and submitted == [d["job_id"]]
    assert lab.JOBS[d["job_id"]]["kind"] == "assistant"
    assert asyncio.run(rra.job_status(d["job_id"]))["kind"] == "assistant"
    with pytest.raises(HTTPException) as e:                       # ein Lab-Job zur Zeit
        asyncio.run(rra.run({"asset_class": "crypto"}, True))
    assert e.value.status_code == 409
    lab.JOBS[d["job_id"]]["status"] = "done"
    monkeypatch.setattr(local_exec, "worker_online", lambda: False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(rra.run({"asset_class": "indices", "execution": "local"}, True))
    assert e.value.status_code == 503
