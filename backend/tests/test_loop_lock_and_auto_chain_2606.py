"""Regression 06/2026: Lock über mehrere Event-Loops (lokaler Worker), Vollautomatik-Kette,
Champion-Modus."""
import asyncio
import pathlib

import pytest

from core.loop_lock import LoopLock
from services import job_series, regime_auto_chain as chain, regime_autopilot

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"


async def _contend(lock):
    async def hold():
        async with lock:
            await asyncio.sleep(0.01)
    await asyncio.gather(hold(), hold(), hold())


def test_plain_asyncio_lock_breaks_across_loops():
    """Ursache des Worker-Fehlers: Sperre bindet sich an den Loop des ersten Jobs."""
    lock = asyncio.Lock()
    asyncio.run(_contend(lock))
    with pytest.raises(RuntimeError, match="different event loop"):
        asyncio.run(_contend(lock))


def test_loop_lock_works_in_every_loop_and_excludes():
    lock = LoopLock()
    for _ in range(3):
        asyncio.run(_contend(lock))

    async def exclusive():
        active, peak = 0, 0

        async def job():
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.005)
                active -= 1
        await asyncio.gather(*[job() for _ in range(5)])
        return peak
    assert asyncio.run(exclusive()) == 1


def test_candle_cache_lock_survives_two_worker_jobs():
    from services import candle_cache as cc
    assert isinstance(cc._LOCK, LoopLock)
    asyncio.run(_contend(cc._LOCK))
    asyncio.run(_contend(cc._LOCK))


@pytest.mark.parametrize("mod", ["candle_cache", "structural_regime", "regime_gate", "regime_hierarchy"])
def test_worker_modules_have_no_loop_bound_lock(mod):
    assert "asyncio.Lock()" not in (SERVICES / f"{mod}.py").read_text(encoding="utf-8")


def _doc(n=3, train=75, engine="v2"):
    return {"id": "a1", "name": "Gruppe", "symbols": [f"C{i}USDT" for i in range(n)], "timeframe": "1h",
            "days": 720, "settings": {"engine": engine, "train_pct": train, "engine_config": {"detector": "kombi"}},
            "combined": {"model": {"config": {"detector": "kombi", "kombi_thr": 0.3}}}}


def test_followup_body_carries_auto_next_and_can_be_disabled():
    res = {"improved": True, "best": {"engine_config": {"detector": "ema"}}, "symbols": ["BTCUSDT"]}
    assert regime_autopilot.followup_analysis_body(res, {})["auto_next"] == list(chain.STEPS)
    assert regime_autopilot.followup_analysis_body(res, {"auto_next": False})["auto_next"] == []
    assert regime_autopilot.followup_analysis_body(res, {"auto_chain": False}) is None


def test_plan_group_queues_ablation_and_pooling_then_fair_later():
    p = chain.plan(_doc(), {"auto_next": list(chain.STEPS), "execution": "local", "worker_id": "w1"})
    assert [i["kind"] for i in p["items"]] == ["regime_ablation", "regime_pooling"]
    assert p["fair_now"] is False
    abl, pool = p["items"][0]["body"], p["items"][1]["body"]
    assert abl["execution"] == "local" and abl["worker_id"] == "w1" and abl["timeframe"] == "1h"
    assert pool["analysis_id"] == "a1" and pool["auto_next"] == ["fair"]
    for it in p["items"]:
        assert it["kind"] in job_series.KINDS and job_series.validate_body(it["kind"], it["body"]) is None


def test_plan_single_coin_skips_pooling_with_reason_and_runs_fair_now():
    p = chain.plan(_doc(n=1), {"auto_next": list(chain.STEPS)})
    assert [i["kind"] for i in p["items"]] == ["regime_ablation"]
    assert p["fair_now"] is True and p["pooling_skipped"]


def test_plan_without_auto_next_is_noop_backwards_compatible():
    assert chain.plan(_doc(), {}) == {"items": [], "fair_now": False, "pooling_skipped": []}
    assert chain.steps_of({"auto_next": ["x", "fair"]}) == ["fair"]
    assert asyncio.run(chain.after_item(None, {"status": "done", "kind": "regime_analysis", "body": {}})) == {}


def test_champion_state_route_registered_before_catch_all():
    from routers import regime_champions
    paths = [r.path for r in regime_champions.router.routes]
    assert "/api/regime-lab/champions/state" in paths and "/api/regime-lab/champions/mode" in paths


def test_candle_cache_lock_two_worker_threads_at_once():
    """Auto-Update + Regime-Job gleichzeitig (je eigener Thread/Loop) – genau der Worker-Fall."""
    import threading
    import time
    from services import candle_cache as cc
    out = {}

    def run(name):
        try:
            asyncio.run(_contend(cc._LOCK))
            out[name] = "ok"
        except Exception as e:  # noqa: BLE001
            out[name] = str(e)
    threads = [threading.Thread(target=run, args=(n,)) for n in ("a", "b")]
    threads[0].start()
    time.sleep(0.005)
    threads[1].start()
    for t in threads:
        t.join()
    run("later")
    assert out == {"a": "ok", "b": "ok", "later": "ok"}
