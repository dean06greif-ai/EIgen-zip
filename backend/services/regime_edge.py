"""Handelbarer Edge einer Regime-Erkennung (rein, testbar).

Statt überlappender „Rendite danach je Kerze“ wird jede LIVE-Trendphase als EIN
Trade gezählt: Einstieg am Schluss der Kerze, an der die Phase erkannt wird,
Ausstieg am Schluss der Kerze, an der sie endet – in Phasen-Richtung, abzüglich
Kosten. Phasen überlappen nicht, also sind es unabhängige Beobachtungen; der
t-Wert sagt ehrlich, ob der Ø-Ertrag von Zufall unterscheidbar ist.

Richtung: -1 ab, 0 seitwärts, +1 auf; alles andere = unbekannt.
"""
import math
from typing import Dict, List, Optional, Sequence

import numpy as np

COST_PCT = 0.12      # Hin- und Rückweg (2 × 0,06 % Taker) je Phasen-Trade
MIN_PHASES = 8       # darunter kein t-Wert – zu wenige unabhängige Trades
T_GOOD = 2.0         # ab hier ist der Edge statistisch belastbar


def phase_returns(close: Sequence[float], direction: Sequence[int],
                  cost_pct: float = COST_PCT) -> List[float]:
    """Netto-Ertrag (%) je abgeschlossener Trendphase."""
    c = np.asarray(close, dtype=float)
    d = np.asarray(direction, dtype=int)
    n = min(len(c), len(d))
    out, s = [], 0
    while s < n:
        e = s + 1
        while e < n and d[e] == d[s]:
            e += 1
        if d[s] in (-1, 1) and e < n and c[s] > 0:
            out.append(float(d[s]) * (c[e] / c[s] - 1.0) * 100.0 - cost_pct)
        s = e
    return out


def stats(rets: List[float]) -> Dict:
    n = len(rets)
    if not n:
        return {"phases": 0, "phase_pct": None, "hit_pct": None, "t": None, "sum_pct": None}
    a = np.asarray(rets, dtype=float)
    sd = float(np.std(a, ddof=1)) if n > 1 else 0.0
    t = float(np.mean(a)) / (sd / math.sqrt(n)) if n >= MIN_PHASES and sd > 0 else None
    return {"phases": n, "phase_pct": round(float(np.mean(a)), 3),
            "hit_pct": round(float(np.mean(a > 0)) * 100.0, 1),
            "t": None if t is None else round(t, 2), "sum_pct": round(float(np.sum(a)), 2)}


def verdict(t: Optional[float]) -> str:
    if t is None:
        return "zu wenige Phasen"
    return "belastbar" if t >= T_GOOD else "schwach" if t > 0 else "kein Edge"


def compute(close: Sequence[float], direction: Sequence[int], split: Optional[int] = None) -> Dict:
    """Edge gesamt sowie getrennt Training (vor split) / Holdout (ab split)."""
    out = {"overall": stats(phase_returns(close, direction))}
    if split is not None and 0 < split < len(close):
        out["train"] = stats(phase_returns(close[:split], direction[:split]))
        out["holdout"] = stats(phase_returns(close[split:], direction[split:]))
    return out
