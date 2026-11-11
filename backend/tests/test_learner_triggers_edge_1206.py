"""Edge cases for learner triggers (12/2026): fail-open, throttle, disabled, restart state, freshness."""
import asyncio
import time

from services import learning_triggers as lt
from tests.test_learner_triggers_1206 import _DB, _learner


# fresh_inputs: lesson_impact raising -> hinderlich 0 (fail-open)
def test_fresh_inputs_lesson_impact_raises(monkeypatch):
    from services import lesson_impact

    async def boom(days=90):
        raise RuntimeError("x")
    monkeypatch.setattr(lesson_impact.lesson_impact, "report", boom)
    fi = asyncio.run(lt.fresh_inputs(_DB(trades=3), None))
    assert fi["trades"] == 3 and fi["hinderlich"] == 0 and fi["hinderlich_titles"] == []


# fresh_inputs: no since -> no time filter on queries
def test_fresh_inputs_no_since_no_filter():
    db = _DB()
    asyncio.run(lt.fresh_inputs(db, None))
    assert "closed_at" not in db.auto_trades.queries[0]
    assert "reviewed_at" not in db.ai_lesson_cf.queries[0]


# Prompt-Schalter aus (Standard) -> Bilanz zählt trotzdem für den Lern-Auslöser
def test_hinderlich_not_gated_by_prompt_flag(monkeypatch):
    from services import lesson_impact

    async def rep(days=90):
        return {"rows": [{"id": "L1", "verdict": "hinderlich"}]}
    monkeypatch.setattr(lesson_impact.lesson_impact, "report", rep)
    fi = asyncio.run(lt.fresh_inputs(_DB(), None, {"lesson_impact_in_prompt": False}))
    assert fi["hinderlich"] == 1 and fi["hinderlich_titles"] == ["L1"]


def test_missed_text_empty():
    assert asyncio.run(lt.missed_text(_DB(), None)) == ""


def test_decide_missed_priority_and_gap_boundaries():
    now = 1e6
    assert lt.decide({"missed": 1, "hinderlich": 1}, now, 0, 0) == "missed_trade"
    # missed blocked by gap -> falls through to reevaluate
    assert lt.decide({"missed": 1, "hinderlich": 1}, now, now - 60, 0) == "reevaluate"
    assert lt.decide({"missed": 1}, now, now - lt.MISSED_GAP_SEC, 0) is None
    assert lt.decide({"missed": 1}, now, now - lt.MISSED_GAP_SEC - 1, 0) == "missed_trade"


# learning disabled -> no run, no reeval
def test_disabled_no_run(monkeypatch):
    from services import ai_learning
    calls = []

    async def fresh(db, since, cfg=None):
        calls.append("fresh")
        return {"trades": 0, "missed": 5, "hinderlich": 1, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB(), {"learning_enabled": False})

    async def rl(trigger="manual"):
        calls.append(trigger)
    lr.run_learning = rl
    lr.reevaluate_lessons = rl
    asyncio.run(lr._learn_from_missed_or_stale(1e9))
    assert calls == []


# exceptions in trigger path never propagate
def test_never_raises(monkeypatch):
    from services import ai_learning

    async def fresh(db, since, cfg=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())
    asyncio.run(lr._learn_from_missed_or_stale(1e9))


# tick: no new trades -> fresh check once, then throttled for 15 min
def test_tick_throttle(monkeypatch):
    lr = _learner(_DB())
    calls = []

    async def sync():
        return []

    async def miss(now):
        calls.append(now)
    lr.sync_outcomes = sync
    lr._learn_from_missed_or_stale = miss
    asyncio.run(lr.tick())
    lr._last_tick = 0  # bypass 30s throttle
    asyncio.run(lr.tick())
    assert len(calls) == 1
    lr._last_tick = 0
    lr._last_fresh_check = time.time() - lt.CHECK_EVERY_SEC - 1
    asyncio.run(lr.tick())
    assert len(calls) == 2


# load_state restores _last_learn_ts from updated_at
def test_load_state_restores_ts():
    class S:
        async def find_one(self, q):
            return {"lessons": [], "updated_at": "2026-01-01T00:00:00+00:00"}
    db = _DB()
    db.settings = S()
    lr = _learner(db)
    asyncio.run(lr.load_state())
    assert abs(lr._last_learn_ts - 1767225600.0) < 1


# daily freshness: missed>0 but trades==0 -> NOT skipped
def test_daily_not_skipped_when_missed(monkeypatch):
    from services import ai_learning

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 1, "hinderlich": 0, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())
    lr._last_learn_ts = 1.0

    async def gs():
        raise RuntimeError("stop-after-freshness")
    lr.gather_stats = gs
    r = asyncio.run(lr.run_learning("daily"))
    assert r["status"] == "error"  # passed freshness gate


def test_daily_skipped_when_nothing(monkeypatch):
    from services import ai_learning

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 0, "hinderlich": 2, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())
    lr._last_learn_ts = 1.0
    assert asyncio.run(lr.run_learning("daily_summary"))["status"] == "skipped"


# FINDING: failed missed_trade run does not advance _last_learn_ts -> retried every 15 min
def test_failed_missed_run_backs_off(monkeypatch):
    from services import ai_learning

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 2, "hinderlich": 0, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())
    n = []

    async def gs():
        n.append(1)
        raise RuntimeError("LLM/provider down")
    lr.gather_stats = gs
    asyncio.run(lr._learn_from_missed_or_stale(1e9))
    asyncio.run(lr._learn_from_missed_or_stale(1e9 + lt.CHECK_EVERY_SEC + 1))
    assert len(n) == 1  # Backoff: Fehlversuch zählt wie ein Lauf (MISSED_GAP_SEC)
    asyncio.run(lr._learn_from_missed_or_stale(1e9 + lt.MISSED_GAP_SEC + 1))
    assert len(n) == 2
