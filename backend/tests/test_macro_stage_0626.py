"""Regressionstests Makro-Filter + Makro-Stufe des Autopiloten (06/2026)."""
import asyncio

import numpy as np

from services import regime_autopilot as ap
from services import regime_engine as eng
from services import regime_macro_filter as mf
from services import regime_macro_stage as ms


def _candles(days=420, tf_h=1, seed=3):
    rng = np.random.default_rng(seed)
    n = int(days * 24 / tf_h)
    drift = np.repeat(rng.choice([-1, 0, 1], size=n // (24 * 30) + 1), 24 * 30)[:n] * 0.0006
    lr = drift + rng.normal(0, 0.006, n)
    close = 100 * np.exp(np.cumsum(lr))
    t0 = 1_600_000_000_000
    return [{"timestamp": t0 + i * 3600_000, "open": float(c), "high": float(c * 1.003),
             "low": float(c * 0.997), "close": float(c), "volume": 1.0} for i, c in enumerate(close)]


def _ids(cfg, candles):
    r = eng.resolve_config(cfg, "1h", len(candles))
    return eng.classify_arrays(eng.compute_matrix(candles, r), r)[0]


def test_filter_off_is_bit_identical():
    c = _candles()
    base = {"detector": "jump", "regime_mode": 3}
    assert np.array_equal(_ids(base, c), _ids({**base, "macro_filter": "off"}, c))


def test_resolve_normalizes_invalid_values():
    r = eng.resolve_config({"macro_filter": "xyz", "macro_scale": "month"}, "1h")
    assert r["macro_filter"] == "off" and r["macro_scale"] == "day"
    assert eng.resolve_config({}, "1h")["macro_filter"] == "off"


def test_apply_soft_and_strict(monkeypatch):
    live3 = np.array([2, 2, 0, 0, 1, 2, -1])
    macro = np.array([-1, 1, 1, 0, 1, -9, 1])
    monkeypatch.setattr(mf, "macro_direction", lambda f, cfg: macro)
    soft = mf.apply(live3, {}, {"macro_filter": "soft"})
    strict = mf.apply(live3, {}, {"macro_filter": "strict"})
    assert soft.tolist() == [1, 2, 1, 0, 1, 2, -1]
    assert strict.tolist() == [1, 2, 1, 1, 1, 2, -1]


def test_filter_changes_labels_and_warmup():
    c = _candles()
    base = {"detector": "jump", "regime_mode": 3}
    on = {**base, "macro_filter": "strict"}
    a, b = _ids(base, c), _ids(on, c)
    warm = mf.warmup_bars(eng.resolve_config(on, "1h", len(c)))
    assert np.array_equal(a[:warm], b[:warm])          # fail-open in der Aufwärmphase
    assert (b[warm:] != a[warm:]).any()
    assert eng.detector_warmup_bars(eng.resolve_config(on, "1h")) >= warm


def test_strip_and_warm_seeds_remove_macro_keys():
    cfg = {"detector": "jump", "macro_filter": "soft", "macro_scale": "week"}
    assert mf.strip(cfg) == {"detector": "jump"}
    seeds = ap.warm_seeds([{"engine_config": {**cfg, "jump_center": 0.4}, "source": "alt"}],
                          {"detector": "jump"}, True)
    assert seeds and "macro_filter" not in seeds[0]["engine_config"]


def _row(mode, scale, score, tt, ht, hp=20, bench=3):
    return {"mode": mode, "scale": scale, "score": score, "bench": bench,
            "edge": {"train": {"t": tt}, "holdout": {"t": ht, "phases": hp}}}


def test_decide_rules():
    base = _row("off", None, 60, 0.5, 0.2)
    # Training besser, Holdout bestätigt -> übernehmen
    d = ms.decide(base, [_row("soft", "day", 60, 1.5, 1.4)])
    assert d["adopted"] and d["mode"] == "soft"
    # Holdout nicht bestätigt
    assert ms.decide(base, [_row("soft", "day", 60, 1.5, 0.6)])["verdict"] == "not_confirmed"
    # Score fällt zu stark -> kein Kandidat
    assert ms.decide(base, [_row("soft", "day", 55, 2.0, 2.0)])["verdict"] == "no_gain"
    # Note (Benchmark) fällt -> kein Kandidat
    assert ms.decide(base, [_row("soft", "day", 60, 2.0, 2.0, bench=2)])["verdict"] == "no_gain"
    # zu wenige Holdout-Phasen
    assert ms.decide(base, [_row("soft", "day", 60, 2.0, 2.0, hp=3)])["verdict"] == "insufficient"
    # Auswahl nur nach Training-t, NICHT nach Holdout
    d = ms.decide(base, [_row("soft", "day", 60, 1.2, 3.0), _row("strict", "week", 60, 1.8, 0.1)])
    assert not d["adopted"] and "Wochen" in d["choice"]


def test_stage_run_end_to_end():
    c = _candles()
    hist = {"AAAUSDT": c, "BBBUSDT": _candles(seed=5)}
    bounds = {s: int(v[int(len(v) * 0.75) - 1]["timestamp"]) for s, v in hist.items()}
    calls = []

    async def ev(cfg, tf):
        calls.append(cfg.get("macro_filter"))
        return {"x": 1}

    async def to_thread(fn, *a):
        return fn(*a)

    best = {"engine_config": {"detector": "jump", "regime_mode": 3}, "metrics": {"x": 1}, "score": 50.0}
    out = asyncio.run(ms.run({"histories": hist, "bounds": bounds}, best, "1h", ev,
                             score_fn=lambda m: 50.0, bench_fn=lambda m: 1, to_thread=to_thread))
    rep = out["report"]
    assert calls == [m for m, _ in ms.CANDIDATES]
    assert len(rep["candidates"]) == 4 and rep["verdict"] in ("adopted", "no_gain", "not_confirmed", "insufficient")
    if out["best"]:
        assert out["best"]["engine_config"]["macro_filter"] in ("soft", "strict")
    else:
        assert rep["adopted"] is False


def test_stage_not_applicable_below_1h():
    async def ev(cfg, tf):
        raise AssertionError("darf nicht bewerten")
    best = {"engine_config": {"detector": "jump"}, "metrics": {}, "score": 1.0}
    out = asyncio.run(ms.run({"histories": {}, "bounds": {}}, best, "15m", ev,
                             score_fn=lambda m: 1.0, bench_fn=lambda m: 0, to_thread=None))
    assert out["best"] is None and out["report"]["verdict"] == "not_applicable"


def test_macro_filter_is_causal():
    c = _candles()
    on = {"detector": "jump", "regime_mode": 3, "macro_filter": "strict", "auto_adapt": False}
    full, part = _ids(on, c), _ids(on, c[:len(c) - 500])
    assert np.array_equal(full[:len(part)], part)
