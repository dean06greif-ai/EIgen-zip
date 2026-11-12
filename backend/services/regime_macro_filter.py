"""Makro-Filter: übergeordnete Zeitebene als Rauschfilter der Haupt-Erkennung (rein).

Die Makro-Ebene ist ein festes Jump-Modell auf einer LANGSAMEN Zeitskala (in Tagen,
gleiche Rezepte wie Abschnitt 0 / services/regime_hierarchy). Weil die Jump-Features
in Tagen und vola-normiert gerechnet werden, braucht es keine Kerzen-Aggregation:
„Tages-Skala“ auf 1h-Kerzen entspricht einem 1D-Makro, ist aber live und im Lab
bit-gleich (kein Aggregations-Versatz, keine Zukunftsdaten).

Modi (Konfig-Schlüssel `macro_filter`, Standard "off" = bitgenau wie bisher):
  soft   – Trend gegen die Makro-Richtung wird seitwärts (Korrekturen ausblenden)
  strict – Trend nur, wenn Makro in DIESELBE Richtung zeigt (Makro seitwärts blockt auch)
Fail-open: in der Makro-Aufwärmphase wird nichts gefiltert.
"""
from typing import Dict, Optional

import numpy as np

MODES = ("off", "soft", "strict")
# Feste Skalen (nie gesucht -> kein Such-Overfitting), identisch zu Abschnitt 0
SCALES: Dict[str, Dict] = {
    "day": {"label": "Tages-Skala (≈ 1D-Makro)", "jump_fast_days": 7.0, "jump_slow_days": 45.0,
            "jump_penalty_days": 10.0},
    "week": {"label": "Wochen-Skala (≈ 1W-Makro)", "jump_fast_days": 14.0, "jump_slow_days": 60.0,
             "jump_penalty_days": 20.0},
}
KEYS = ("macro_filter", "macro_scale")
DEFAULTS = {"macro_filter": "off", "macro_scale": "day"}


def normalize(cfg: Dict) -> Dict:
    mode = str((cfg or {}).get("macro_filter") or "off").lower()
    scale = str((cfg or {}).get("macro_scale") or "day").lower()
    return {"macro_filter": mode if mode in MODES else "off",
            "macro_scale": scale if scale in SCALES else "day"}


def active(cfg: Optional[Dict]) -> bool:
    return normalize(cfg or {})["macro_filter"] != "off"


def jump_params(cfg: Dict) -> Dict:
    from services import regime_hierarchy as rh
    from services import regime_jump as rj
    s = SCALES[normalize(cfg)["macro_scale"]]
    jump = {k: s[k] for k in ("jump_fast_days", "jump_slow_days", "jump_penalty_days")}
    jump["jump_center"] = rh.noise_center(s["jump_fast_days"], s["jump_slow_days"])
    return rj.params({"bars_per_day": cfg.get("bars_per_day") or 24.0, **jump})


def warmup_bars(cfg: Dict) -> int:
    if not active(cfg):
        return 0
    return int(round(3 * jump_params(cfg)["slow_bars"]))


LIVE_WARMUP_MULT = 5    # Live-Historie: bei 3 Halbwertszeiten wich die Makro-Richtung noch in
                        # 10–30 % der Zeitpunkte vom Lab ab, ab 5 in 0 % (BTC/ETH/BNB 4h, 06/2026)


def live_warmup_bars(cfg: Dict) -> int:
    """Kerzen, die ein LIVE-Fenster braucht, damit die Makro-Richtung dem Lab entspricht."""
    if not active(cfg):
        return 0
    return int(round(LIVE_WARMUP_MULT * jump_params(cfg)["slow_bars"]))


def macro_direction(f: Dict, cfg: Dict) -> np.ndarray:
    """Kausale Makro-Richtung je Kerze (-1/0/1, -9 = Aufwärmphase)."""
    from services import regime_jump as rj
    close = np.asarray(f["close"], dtype=float)
    p = jump_params(cfg)
    dvol = np.nan_to_num(np.asarray(f["daily_vol_pct"], dtype=float), nan=2.0)
    dvol = np.where(dvol <= 0, 2.0, dvol)
    lab, _V = rj.online_filter(rj.losses(rj.features(close, dvol, p), p["c"]), p["lam"])
    out = lab.astype(int) - 1
    out[:min(warmup_bars(cfg), len(out))] = -9
    return out


def apply(live3: np.ndarray, f: Dict, cfg: Dict) -> np.ndarray:
    """live3 (0 ab, 1 seitwärts, 2 auf; <0 unbekannt) gegen die Makro-Ebene filtern."""
    mode = normalize(cfg)["macro_filter"]
    out = np.asarray(live3).copy()
    if mode == "off" or not len(out):
        return out
    m = macro_direction(f, cfg)
    live_dir = out.astype(int) - 1
    known = (out >= 0) & (m != -9) & (live_dir != 0)
    if mode == "soft":
        block = known & (live_dir * m == -1)
    else:
        block = known & (m != live_dir)
    out[block] = 1
    return out


def strip(cfg: Optional[Dict]) -> Dict:
    """Haupt-Erkennung ohne Makro-Filter (die Suche läuft immer nur auf der Haupt-Ebene)."""
    return {k: v for k, v in (cfg or {}).items() if k not in KEYS}


def with_filter(cfg: Dict, mode: str, scale: str) -> Dict:
    return {**strip(cfg), "macro_filter": mode, "macro_scale": scale}


def describe(cfg: Optional[Dict]) -> str:
    n = normalize(cfg or {})
    if n["macro_filter"] == "off":
        return "kein Makro-Filter"
    how = "gegen Makro → seitwärts" if n["macro_filter"] == "soft" else "nur mit Makro"
    return f"{SCALES[n['macro_scale']]['label']} · {how}"
