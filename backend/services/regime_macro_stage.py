"""Makro-Stufe des Regime-Autopiloten: übergeordnete Zeitebene nur bei echtem Mehrwert.

Ablauf (nach der Haupt-Suche, ohne eigene Suche -> kein Such-Overfitting):
  1. Kandidaten = feste Liste (2 Skalen × 2 Modi, services/regime_macro_filter)
  2. AUSWAHL nur auf dem Training: Kandidat mit dem höchsten Edge-t (jede Live-
     Trendphase = 1 Trade nach Kosten, Phasen aller Symbole gepoolt), der den
     Auswahl-Score (innere Val. + Training) und die Benchmark-Stufe nicht senkt
  3. BESTÄTIGUNG einmalig im Holdout: Holdout-t ≥ T_MIN und ≥ Haupt-t + T_MARGIN,
     genug Holdout-Phasen. Sonst bleibt es bei der Haupt-Erkennung („kein Mehrwert“).
Fail-open: jeder Fehler -> Haupt-Erkennung bleibt unverändert.
"""
from typing import Callable, Dict, List, Optional

import numpy as np

from services import regime_edge
from services import regime_macro_filter as mf

CANDIDATES = (("soft", "day"), ("strict", "day"), ("soft", "week"), ("strict", "week"))
T_MARGIN = 0.5          # Holdout-Vorsprung (deckt 4 Kandidaten = Mehrfachtest ab)
T_MIN = 1.0             # Mindest-Holdout-t des Kandidaten
SCORE_TOLERANCE = 1.0   # Auswahl-Score darf höchstens so viel fallen
MIN_HOLDOUT_PHASES = regime_edge.MIN_PHASES
MIN_TF_MINUTES = 60     # darunter wird die Makro-Aufwärmphase (135–180 Tage) live zu teuer


def split_index(candles: List[Dict], bound_ts: Optional[int]) -> int:
    if bound_ts is None:
        return len(candles)
    for i, c in enumerate(candles):
        if int(c["timestamp"]) > bound_ts:
            return i
    return len(candles)


def pooled_edge(histories: Dict[str, List[Dict]], bounds: Dict, cfg: Dict, tf: str) -> Dict:
    """Edge Training/Holdout über alle Symbole (Phasen gepoolt) + je Symbol."""
    from services import regime_macro_check as mc
    tr_all, ho_all, per = [], [], []
    for sym, candles in (histories or {}).items():
        d = mc.direction_series(candles, cfg, tf)
        close = np.array([float(c["close"]) for c in candles])
        k = split_index(candles, bounds.get(sym))
        tr = regime_edge.phase_returns(close[:k], d[:k])
        ho = regime_edge.phase_returns(close[k:], d[k:])
        tr_all += tr
        ho_all += ho
        per.append({"symbol": sym, "train_t": regime_edge.stats(tr)["t"],
                    "holdout_t": regime_edge.stats(ho)["t"]})
    return {"train": regime_edge.stats(tr_all), "holdout": regime_edge.stats(ho_all), "per_symbol": per}


def _t(row: Dict, part: str) -> Optional[float]:
    return ((row or {}).get("edge") or {}).get(part, {}).get("t")


def decide(base: Dict, cands: List[Dict]) -> Dict:
    """Reine Entscheidung. Zeilen: {mode, scale, score, bench, edge{train,holdout}}."""
    bt, bh = _t(base, "train"), _t(base, "holdout")
    elig = [c for c in cands
            if _t(c, "train") is not None and (bt is None or _t(c, "train") > bt)
            and c.get("score") is not None and base.get("score") is not None
            and c["score"] >= base["score"] - SCORE_TOLERANCE
            and (c.get("bench") or 0) >= (base.get("bench") or 0)]
    if not elig:
        return {"adopted": False, "choice": None, "verdict": "no_gain",
                "text": "Kein Makro-Kandidat verbessert den Trainings-Edge ohne Score/Note zu senken – "
                        "Haupt-Erkennung allein bleibt (Makro bringt hier keinen Mehrwert)."}
    pick = max(elig, key=lambda c: _t(c, "train"))
    ht = _t(pick, "holdout")
    phases = ((pick.get("edge") or {}).get("holdout") or {}).get("phases") or 0
    label = mf.describe({"macro_filter": pick["mode"], "macro_scale": pick["scale"]})
    if ht is None or phases < MIN_HOLDOUT_PHASES:
        return {"adopted": False, "choice": label, "verdict": "insufficient",
                "text": f"„{label}“ wirkt im Training besser, aber im Holdout gibt es zu wenige Phasen "
                        "für eine Bestätigung – nicht übernommen."}
    need = max(T_MIN, (bh if bh is not None else 0.0) + T_MARGIN)
    if ht < need:
        return {"adopted": False, "choice": label, "verdict": "not_confirmed",
                "text": f"„{label}“ im Holdout nicht bestätigt (t {ht:.2f} < nötig {need:.2f}) – "
                        "Haupt-Erkennung allein bleibt."}
    return {"adopted": True, "choice": label, "verdict": "adopted", "mode": pick["mode"],
            "scale": pick["scale"],
            "text": f"Makro-Filter „{label}“ übernommen: Edge-t Training {bt} → {_t(pick, 'train')}, "
                    f"Holdout {bh} → {ht} (Auswahl nur auf Training, Holdout einmalig bestätigt)."}


async def run(ctx: Dict, best: Dict, tf: str, ev: Callable, score_fn: Callable,
              bench_fn: Callable, to_thread: Callable, progress: Callable = None) -> Dict:
    """Makro-Stufe ausführen. Rückgabe: {'report', 'best'} (best = neuer Bestwert oder None)."""
    from services.timeframes import tf_minutes
    if (tf_minutes(tf) or 0) < MIN_TF_MINUTES:
        return {"report": {"timeframe": tf, "adopted": False, "verdict": "not_applicable",
                           "base": None, "candidates": [],
                           "text": f"Makro-Stufe erst ab {MIN_TF_MINUTES // 60}h-Kerzen (Live-Historie "
                                   "für die langsame Makro-Ebene wäre sonst zu groß) – nicht geprüft."},
                "best": None}
    base_cfg = mf.strip(best["engine_config"])
    hist, bounds = ctx["histories"], ctx["bounds"]
    base = {"mode": "off", "scale": None, "score": best.get("score"),
            "bench": bench_fn(best.get("metrics")),
            "edge": await to_thread(pooled_edge, hist, bounds, base_cfg, tf)}
    rows, metrics = [], {}
    for i, (mode, scale) in enumerate(CANDIDATES):
        if progress:
            progress(f"Makro-Stufe {i + 1}/{len(CANDIDATES)}: {mf.describe({'macro_filter': mode, 'macro_scale': scale})}")
        cfg = mf.with_filter(base_cfg, mode, scale)
        m = await ev(cfg, tf)
        row = {"mode": mode, "scale": scale, "score": score_fn(m) if m else None,
               "bench": bench_fn(m) if m else 0, "edge": None}
        if m:
            row["edge"] = await to_thread(pooled_edge, hist, bounds, cfg, tf)
            metrics[(mode, scale)] = m
        rows.append(row)
    dec = decide(base, rows)
    slim = lambda r: {"mode": r["mode"], "scale": r["scale"], "score": r["score"],  # noqa: E731
                      "label": mf.describe({"macro_filter": r["mode"], "macro_scale": r["scale"]}),
                      "train_t": _t(r, "train"), "holdout_t": _t(r, "holdout"),
                      "train_phases": ((r.get("edge") or {}).get("train") or {}).get("phases"),
                      "holdout_phases": ((r.get("edge") or {}).get("holdout") or {}).get("phases")}
    # Holdout nur für den gewählten Kandidaten zeigen (kein manuelles Holdout-Shopping)
    cands = [slim(r) for r in rows]
    for c in cands:
        if c["label"] != dec.get("choice"):
            c["holdout_t"] = c["holdout_phases"] = None
    report = {"timeframe": tf, "base": slim(base), "candidates": cands,
              "t_margin": T_MARGIN, "t_min": T_MIN, **dec}
    new_best = None
    if dec["adopted"]:
        cfg = mf.with_filter(base_cfg, dec["mode"], dec["scale"])
        m = metrics[(dec["mode"], dec["scale"])]
        new_best = {"engine_config": cfg, "metrics": m, "score": score_fn(m)}
    return {"report": report, "best": new_best}
