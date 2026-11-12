"""Makro-Bezug der Endlos-Suche (Autopilot) – Brücke zu Abschnitt 0 (Regime-Assistent).

Drei Ebenen, klar getrennt:
  Makro    – festes Rezept je Anlageklasse (services/regime_hierarchy, z.B. Krypto 1d),
             wird NICHT gesucht (kein Such-Overfitting), dient als Filter.
  Haupt    – die Erkennung, die der Autopilot findet (Timeframe = gewählter bzw.
             bester TF der Timeframe-Kette, immer UNTER dem Makro-TF).
  Handel   – kleinere Timeframes (5m–1h) für das Timing der Strategien.

Nach der Suche wird die beste Haupt-Erkennung einmal gegen die Makro-Ebene
gemessen (Nutzen-Note „nur Haupt“ vs. „Makro × Haupt“, Konflikt-Anteil).
Reine Auswertung: ändert weder Suche noch Score – fail-open.
"""
import statistics
from typing import Dict, List, Optional

import numpy as np

COMBINED_TOLERANCE = 3.0    # wie regime_assistant.summarize: Kombination bevorzugen


def macro_minutes(symbols: List[str]) -> Optional[int]:
    """Kleinster Makro-Timeframe (Minuten) der Anlageklassen der Symbole."""
    from services import regime_hierarchy as rh
    from services import setup_asset_class as ac
    from services.timeframes import tf_minutes
    mins = [tf_minutes(rh.recipe_for(ac.asset_class_of(s))["macro_tf"]) for s in symbols or []]
    mins = [m for m in mins if m]
    return min(mins) if mins else None


def direction_series(candles: List[Dict], engine_config: Dict, tf: str) -> np.ndarray:
    """Kausale Live-Richtung der gefundenen Erkennung je Kerze (-1/0/1, -9 = Warmup)."""
    from services import market_context as mc
    from services import regime_engine as eng
    cfg = eng.resolve_config(dict(engine_config or {}), tf, len(candles))
    ids, _conf = eng.classify_arrays(eng.compute_matrix(candles, cfg), cfg)
    names = {"down": -1, "sideways": 0, "up": 1}
    mode = cfg.get("regime_mode")
    return np.array([names.get(mc.direction_from_regime_id(int(r), mode), -9) if r >= 0 else -9
                     for r in ids], dtype=int)


def conflict_pct(primary: np.ndarray, macro: np.ndarray) -> Optional[float]:
    """Anteil Kerzen, in denen Haupt und Makro in GEGENSÄTZLICHE Richtung zeigen (rein)."""
    known = (primary != -9) & (macro != -9)
    if not known.any():
        return None
    p, m = primary[known], macro[known]
    return round(float(np.mean((p * m) == -1)) * 100, 1)


def evaluate_symbol(symbol: str, candles: List[Dict], engine_config: Dict, tf: str) -> Optional[Dict]:
    from services import regime_hierarchy as rh
    from services import regime_usefulness as ru
    from services import setup_asset_class as ac
    from services.timeframes import tf_minutes
    rc = rh.recipe_for(ac.asset_class_of(symbol))
    if not tf_minutes(tf) or tf_minutes(rc["macro_tf"]) <= tf_minutes(tf):
        return None
    macro_c = rh.aggregate(candles, rc["macro_tf"], tf)
    if len(macro_c) < 30:
        return None
    ml = rh.classify_layer(macro_c, rc["macro"], rc["macro_tf"])
    macro = rh.align_macro(candles, macro_c, ml["series"], tf_minutes(tf) * 60000,
                           tf_minutes(rc["macro_tf"]) * 60000)
    primary = direction_series(candles, engine_config, tf)
    known = np.where((primary != -9) & (macro != -9))[0]
    if not len(known):
        return None
    start = int(known[0])
    closes = [float(c["close"]) for c in candles]
    bpd = 1440.0 / tf_minutes(tf)
    own = ru.evaluate(closes, primary, bpd, start)["score"]
    comb = ru.evaluate(closes, rh.combined_series(macro, primary), bpd, start)["score"]
    return {"symbol": symbol, "macro_tf": rc["macro_tf"], "primary": own, "combined": comb,
            "conflict_pct": conflict_pct(primary, macro), "macro_now": ml.get("direction")}


def summarize(rows: List[Dict]) -> Dict:
    """Median je Variante + Urteil (rein)."""
    def med(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None
    own, comb, conf = med("primary"), med("combined"), med("conflict_pct")
    if own is None or comb is None:
        verdict, text = "unknown", "Zu wenig Daten für den Makro-Vergleich."
    elif comb >= own - COMBINED_TOLERANCE:
        verdict, text = "use_macro", ("Makro × Haupt ist mindestens gleich gut – Makro-Filter "
                                      "(Abschnitt 0) zusammen mit dieser Erkennung nutzen.")
    else:
        verdict, text = "primary_only", ("Haupt-Erkennung allein trennt besser – Makro nur als "
                                         "Größen-Faktor nutzen, nicht als harter Filter.")
    return {"primary": own, "combined": comb, "conflict_pct": conf,
            "verdict": verdict, "text": text, "per_symbol": rows}


def evaluate(histories: Dict[str, List[Dict]], engine_config: Dict, tf: str) -> Optional[Dict]:
    """Makro-Check der besten Erkennung über alle Symbole (None = nicht anwendbar)."""
    rows = []
    for sym, candles in (histories or {}).items():
        try:
            r = evaluate_symbol(sym, candles, engine_config, tf)
        except Exception:  # noqa: BLE001 – fail-open je Symbol
            r = None
        if r:
            rows.append(r)
    if not rows:
        return None
    out = summarize(rows)
    out["timeframe"] = tf
    out["macro_tf"] = rows[0]["macro_tf"]
    return out
