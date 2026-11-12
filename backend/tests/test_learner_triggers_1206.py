"""12/2026: Learner lernt auch aus verpassten guten Trades und prüft hinderliche Lektionen."""
import asyncio

from services import learning_triggers as lt


async def _aw(v):
    return v


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return self.rows[:n]


class _Coll:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def count_documents(self, q):
        self.queries.append(q)
        return len(self.rows)

    def find(self, q, proj=None):
        self.queries.append(q)
        return _Cur(list(self.rows))


class _DB:
    def __init__(self, trades=0, missed=None):
        self.auto_trades = _Coll([{}] * trades)
        self.ai_lesson_cf = _Coll(missed or [])


def test_decide_rules():
    now = 100_000.0
    assert lt.decide({"missed": 2}, now, 0, 0) == "missed_trade"
    assert lt.decide({"missed": 2, "hinderlich": 0}, now, now - 60, 0) is None
    assert lt.decide({"missed": 0, "hinderlich": 1}, now, 0, 0) == "reevaluate"
    assert lt.decide({"missed": 0, "hinderlich": 1}, now, 0, now - 3600) is None
    assert lt.decide({}, now, 0, 0) is None


def test_idle_reason_texts():
    assert lt.idle_reason({"trades": 0, "missed": 0, "hinderlich": 0}).startswith("wartet:")
    assert "verpasste" in lt.idle_reason({"missed": 3})


def test_fresh_inputs_and_missed_text(monkeypatch):
    from services import lesson_impact

    async def rows(cfg, days=90):
        return [{"title": "Kein Long bei hoher Vola", "verdict": "hinderlich"}, {"verdict": "edge"}]
    monkeypatch.setattr(lesson_impact.lesson_impact, "report", lambda days=90: _aw({"rows": [{"title": "Kein Long bei hoher Vola", "verdict": "hinderlich"}, {"verdict": "edge"}]}))
    db = _DB(trades=0, missed=[{"symbol": "BTCUSDT", "action": "LONG", "horizon": "scalp",
                               "r": 1.4, "blocked_by": ["L1"]}])
    fi = asyncio.run(lt.fresh_inputs(db, "2026-12-01T00:00:00+00:00"))
    assert fi["trades"] == 0 and fi["missed"] == 1 and fi["hinderlich"] == 1
    q = db.ai_lesson_cf.queries[0]
    assert q["r"] == {"$gte": lt.MISSED_R_MIN} and "reviewed_at" in q
    txt = asyncio.run(lt.missed_text(db, None))
    assert "VERPASSTE GUTE TRADES" in txt and "+1.40 R" in txt and "L1" in txt


def _learner(db, cfg=None):
    from services.ai_learning import AILearning
    eng = type("E", (), {"config": cfg or {}, "key": "k", "db": db})()
    return AILearning(eng)


def test_learner_runs_on_missed_trade_without_new_trades(monkeypatch):
    from services import ai_learning
    calls = []

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 2, "hinderlich": 0, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())

    async def run_learning(trigger="manual"):
        calls.append(trigger)
    lr.run_learning = run_learning
    lr.learning_now = False
    lr._last_learn_ts = 0.0
    lr._last_reeval_ts = 0.0
    asyncio.run(lr._learn_from_missed_or_stale(1e9))
    assert calls == ["missed_trade"] and "verpasste" in lr.idle_reason


def test_learner_reevaluates_hinderlich_once(monkeypatch):
    from services import ai_learning
    calls = []

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 0, "hinderlich": 1, "hinderlich_titles": ["X"]}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())

    async def reeval(reason=""):
        calls.append(reason)
    lr.reevaluate_lessons = reeval
    lr.learning_now = False
    lr._last_learn_ts = 0.0
    lr._last_reeval_ts = 0.0
    asyncio.run(lr._learn_from_missed_or_stale(1e9))
    asyncio.run(lr._learn_from_missed_or_stale(1e9 + 60))
    assert len(calls) == 1 and "X" in calls[0]


def test_learner_idle_reason_when_nothing_new(monkeypatch):
    from services import ai_learning

    async def fresh(db, since, cfg=None):
        return {"trades": 0, "missed": 0, "hinderlich": 0, "hinderlich_titles": []}
    monkeypatch.setattr(ai_learning.learning_triggers, "fresh_inputs", fresh)
    lr = _learner(_DB())
    lr.learning_now = False
    asyncio.run(lr._learn_from_missed_or_stale(1e9))
    assert lr.idle_reason.startswith("wartet:")
    assert lr.summary()["idle_reason"].startswith("wartet:")
