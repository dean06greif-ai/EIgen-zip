"""E2E-Kettenprüfung mit echten Kerzen: Regime-Lab-Modell -> Live-Klassifikation (KI-Trader /
dynamische Strategie) -> Walk-Forward -> Signal-Auslösung, je einmal ohne/mit Makro-Filter.
Aufruf: python scripts/e2e_regime_chain.py BTCUSDT [4h] [720]   -> /tmp/majors/e2e_<coin>.json"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
for k, v in (("ADMIN_PASSWORD", "x"), ("ADMIN_USER", "Admin"), ("JWT_SECRET", "x")):
    os.environ.setdefault(k, v)

CONF_MIN, MIN_HOLD = 0.7, 2.0


def variants(best_cfg):
    from services import regime_macro_filter as mf
    base = mf.strip(best_cfg or {"detector": "reactive"})
    return {"ohne": base, "soft_day": mf.with_filter(base, "soft", "day"),
            "strict_week": mf.with_filter(base, "strict", "week")}


def live_contract(model, candles, tf, full):
    """Live-Fenster wie im Betrieb (Detektor-Warmup, verlängert bis die Hold-Sperre eingerastet
    ist) und Präfix (Kausalität) gegen die Lab-Labels."""
    from services import regime as rg, regime_engine as eng, regime_live_history as lh
    cfg = model["config"]
    bpd = float(cfg["bars_per_day"])
    need_days = eng.required_history_days(cfg, 30)
    cuts = list(range(len(candles) - 1, len(candles) - 240, -6))
    fixed_ok = live_ok = synced_n = prefix_ok = 0
    used = []
    t0 = time.time()
    for k in cuts:
        async def load(days, _k=k):
            return candles[max(_k + 1 - (int(days * bpd) + 1), 0):_k + 1]
        lh._DAYS.clear()
        fixed = asyncio.run(load(need_days))
        fixed_ok += int(rg.current_regime(model, fixed, tf, CONF_MIN, MIN_HOLD).get("regime") == full[k])
        win, days, ok = asyncio.run(lh.load_synced(model, "e2e", need_days, load, MIN_HOLD))
        live_ok += int(rg.current_regime(model, win, tf, CONF_MIN, MIN_HOLD).get("regime") == full[k])
        synced_n += int(bool(ok))
        used.append(days)
    ms = (time.time() - t0) / max(len(cuts), 1) * 1000
    for k in cuts[:12]:
        prefix_ok += int(rg.classify_series(model, candles[:k + 1], tf, CONF_MIN, MIN_HOLD)[-1] == full[k])
    pct = lambda x, n: round(100 * x / max(n, 1), 1)  # noqa: E731
    return {"need_days": need_days, "cuts": len(cuts),
            "fixed_window_match_pct": pct(fixed_ok, len(cuts)),
            "live_match_pct": pct(live_ok, len(cuts)), "synced_pct": pct(synced_n, len(cuts)),
            "days_used_median": sorted(used)[len(used) // 2], "days_used_max": max(used),
            "prefix_match_pct": pct(prefix_ok, min(len(cuts), 12)), "ms_per_refresh": round(ms, 1)}


def structural(model, candles, tf, sym):
    from datetime import datetime, timezone
    from services import structural_regime as sr, regime_engine as eng
    need = int(eng.required_history_days(model["config"], 30) * float(model["config"]["bars_per_day"])) + 1
    now = datetime.fromtimestamp(candles[-1]["timestamp"] / 1000 + 3600, tz=timezone.utc)
    ids = [r["id"] for r in model["regimes"]]
    ok = sr.context_from_model(model, candles[-need:], tf, "e2e", "active", ids, sym, now)
    short = sr.context_from_model(model, candles[-200:], tf, "e2e", "active", ids, sym, now)
    pick = lambda c: {k: c.get(k) for k in ("state", "direction", "label", "reason", "since_days")}  # noqa: E731
    return {"full_history": pick(ok), "zu_kurz_200_kerzen": pick(short)}


def assignments_for(model):
    from services import market_context as mc
    mode = model["config"].get("regime_mode")
    out = {}
    for r in model["regimes"]:
        d = mc.direction_from_regime_id(r["id"], mode)
        sid = "nnfx_reversion" if d == "sideways" else "nnfx_trend"
        out[f"combined:{r['id']}"] = {"regime_id": r["id"], "strategy_id": sid, "regime_label": r.get("label")}
    return out


async def walkforward(model, candles, tf, sym, days):
    from services import regime_lab as lab, regime_opt, regime_split
    from strategies.registry import registry
    k = int(len(candles) * 0.75)
    doc = {"id": "e2e_" + sym, "timeframe": tf, "days": days, "symbols": [sym],
           "combined": {"model": model},
           "bounds": {sym: {"train_end_ts": candles[k]["timestamp"]}},
           "settings": {"train_pct": 75}, "assignments": assignments_for(model)}

    async def hist(*a, **kw):
        return {sym: candles}
    orig = lab.fetch_histories
    lab.fetch_histories = hist
    jid = "e2e_wf_" + sym
    lab.JOBS[jid] = {"id": jid, "status": "running", "cancel": False}
    try:
        await regime_opt.run_walkforward(jid, {"analysis_doc": doc, "scope": "combined"},
                                         registry, {}, {"max_capital": 100}, None)
    finally:
        lab.fetch_histories = orig
    job = lab.JOBS.pop(jid)
    res = job.get("result") or {}
    assigned = {a["regime_id"] for a in doc["assignments"].values()}
    pts = res.get("points") or []
    slim = lambda s: s and {"text": s.get("text"), "macro_label": s.get("macro_label"),  # noqa: E731
                            "strategies": s.get("strategies")}
    return {"status": job.get("status"), "error": job.get("error"),
            "trades": (res.get("dynamic_test") or {}).get("trades"),
            "pnl": (res.get("dynamic_test") or {}).get("pnl"),
            "switches": res.get("switches"), "untraded_bars": res.get("untraded_bars"),
            "trades_outside_assigned": sum(1 for p in pts if p.get("regime") not in assigned),
            "trades_before_holdout": sum(1 for p in pts if regime_split._ms(p.get("t")) is not None
                                         and regime_split._ms(p.get("t")) <= candles[k]["timestamp"]),
            "regime_split": slim(res.get("regime_split")),
            "regime_split_macro": slim(res.get("regime_split_macro"))}


def signal_chain(model, candles, sym, tf):
    """Dynamische Strategie: Zustand -> Plan -> Sub-Strategie -> Signal (gemappt / unbelegt / Entwurf)."""
    from core.state import scanner
    from services import dynamic_runtime as rt
    from strategies.dynamic_regime_strategy import DynamicRegimeStrategy
    from strategies.registry import registry
    rids = [r["id"] for r in model["regimes"]]
    doc = {"id": "dyn_e2e", "name": "E2E", "timeframe": tf, "model": model, "symbols": [sym],
           "regime_strategies": {str(r): "nnfx_trend" for r in rids[:-1]}, "settings": {}}
    st = DynamicRegimeStrategy(doc)
    sub = registry.get("nnfx_trend")
    direct = sub.analyze(candles[-600:], sym, sub.get_params(scanner.settings, sym)) or {}
    out = {}
    rt.STATE["dyn_e2e"] = {sym: {"regime": rids[0], "label": "A", "confidence": 90}}
    r = st.analyze(candles[-600:], sym, {})
    out["gemappt_signal_gleich_substrategie"] = r.get("signal_type") == direct.get("signal_type")
    out["gemappt_sub"] = (r.get("dynamic") or {}).get("sub_strategy_id")
    rt.STATE["dyn_e2e"] = {sym: {"regime": rids[-1], "label": "Z", "confidence": 90}}
    r = st.analyze(candles[-600:], sym, {})
    out["unbelegt_kein_signal"] = r.get("signal_type") is None and "nicht gehandelt" in (r["dynamic"].get("status") or "")
    rt.STATE["dyn_e2e"] = {}
    r = st.analyze(candles[-600:], sym, {})
    out["unbekannt_kein_signal"] = r.get("signal_type") is None
    rt.STATE.pop("dyn_e2e", None)
    return out


def run_sync(fn, *a):
    """Synchrone Prüfungen außerhalb des Event-Loops (sie nutzen selbst asyncio.run)."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(fn, *a).result()


async def main(sym, tf, days):
    from services import regime as rg, regime_engine as eng, regime_lab as lab
    best = None
    p = Path(f"/tmp/majors/{sym}.json")
    if p.is_file():
        best = ((json.loads(p.read_text()).get("result") or {}).get("best_engine_config"))
    job = {"id": "e2e", "status": "running", "cancel": False}
    candles = (await lab.fetch_histories([sym], days, tf, job))[sym]
    report = {"symbol": sym, "timeframe": tf, "bars": len(candles), "variants": {}}
    for name, cfg in variants(best).items():
        model = eng.build_model({sym: candles}, tf, cfg)
        full = rg.classify_series(model, candles, tf, CONF_MIN, MIN_HOLD)
        row = {"macro": {k: model["config"].get(k) for k in ("macro_filter", "macro_scale")},
               "regimes": [r.get("label") for r in model["regimes"]],
               "labels_known_pct": round(100 * sum(1 for x in full if x is not None) / len(full), 1),
               "live_contract": run_sync(live_contract, model, candles, tf, full),
               "structural": structural(model, candles, tf, sym)}
        try:
            row["walkforward"] = await walkforward(model, candles, tf, sym, days)
        except Exception as e:  # noqa: BLE001
            row["walkforward"] = {"status": "exception", "error": repr(e)[:300]}
        try:
            row["signal_chain"] = signal_chain(model, candles, sym, tf)
        except Exception as e:  # noqa: BLE001
            row["signal_chain"] = {"error": repr(e)[:300]}
        report["variants"][name] = row
    Path("/tmp/majors").mkdir(exist_ok=True)
    Path(f"/tmp/majors/e2e_{sym}.json").write_text(json.dumps(report, default=str, indent=1))
    print(json.dumps(report, default=str, indent=1))


if __name__ == "__main__":
    a = sys.argv
    asyncio.run(main(a[1], a[2] if len(a) > 2 else "4h", int(a[3]) if len(a) > 3 else 720))
