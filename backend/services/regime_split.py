"""Trägt das Regime als Strategie-Schalter? (rein, testbar)

Jede Regime-Strategie läuft im Walk-Forward ohnehin EINZELN über den ganzen
Holdout. Hier werden genau diese Trades nach dem Live-Regime bei Einstieg
geteilt: läuft die Strategie in IHREM Regime klar besser als außerhalb?
Nur dann bringt das Umschalten etwas. Welch-t-Wert: >= 2 belastbar.
"""
import math
from datetime import datetime
from typing import Dict, List, Optional

MIN_TRADES = 10
T_GOOD = 2.0


def _ms(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def trade_ts(row: Dict) -> Optional[int]:
    for k in ("opened_ts", "opened", "closed_ts", "closed"):
        t = _ms(row.get(k))
        if t is not None:
            return t
    return None


def spans(segs_by_symbol: Dict[str, List[Dict]]) -> Dict[str, List[tuple]]:
    """Segmente -> je Symbol sortierte (start_ts, regime)."""
    return {sym: sorted((int(s["start_ts"]), s["regime"]) for s in ss or [])
            for sym, ss in (segs_by_symbol or {}).items()}


def regime_at(sp: List[tuple], ts: int):
    cur = None
    for start, rid in sp:
        if start > ts:
            break
        cur = rid
    return cur


def _stat(v: List[float]) -> Dict:
    n = len(v)
    mean = sum(v) / n if n else 0.0
    var = sum((x - mean) ** 2 for x in v) / (n - 1) if n > 1 else 0.0
    return {"n": n, "mean": mean, "var": var}


def welch_t(a: List[float], b: List[float]) -> Optional[float]:
    sa, sb = _stat(a), _stat(b)
    if sa["n"] < MIN_TRADES or sb["n"] < MIN_TRADES:
        return None
    se = math.sqrt(sa["var"] / sa["n"] + sb["var"] / sb["n"])
    return round((sa["mean"] - sb["mean"]) / se, 2) if se > 0 else None


def split_strategy(rows: List[Dict], sp_by_symbol: Dict[str, List[tuple]], own) -> Dict:
    inside, outside = [], []
    for r in rows or []:
        ts = trade_ts(r)
        if ts is None:
            continue
        rid = regime_at(sp_by_symbol.get(r.get("symbol")) or [], ts)
        (inside if rid == own else outside).append(float(r.get("pnl") or 0))
    si, so = _stat(inside), _stat(outside)
    t = welch_t(inside, outside)
    return {"regime": own, "trades_in": si["n"], "trades_out": so["n"],
            "avg_in": round(si["mean"], 4) if si["n"] else None,
            "avg_out": round(so["mean"], 4) if so["n"] else None,
            "t": t, "verdict": verdict(t, si, so)}


def verdict(t: Optional[float], si: Dict, so: Dict) -> str:
    if t is None:
        return "zu wenige Trades"
    if t >= T_GOOD:
        return "Regime trägt" if si["mean"] > 0 else "besser, aber Verlust"
    return "kein Unterschied" if t > -T_GOOD else "außerhalb besser"


def evaluate(single_rows: Dict, segs_by_symbol: Dict[str, List[Dict]],
             labels: Optional[Dict] = None) -> Dict:
    """single_rows: regime_id -> Trades der Regime-Strategie über den ganzen Holdout."""
    sp = spans(segs_by_symbol)
    out = []
    for rid, rows in sorted((single_rows or {}).items(), key=lambda kv: str(kv[0])):
        row = split_strategy(rows, sp, rid)
        row["label"] = (labels or {}).get(rid) or f"#{rid}"
        out.append(row)
    judged = [r for r in out if r["t"] is not None]
    carried = [r for r in judged if r["verdict"] == "Regime trägt"]
    if not judged:
        text = "Zu wenige Holdout-Trades je Seite – noch kein Urteil möglich."
    elif len(carried) == len(judged):
        text = "Jede Strategie läuft in ihrem Regime belastbar besser – Umschalten lohnt sich."
    elif carried:
        text = (f"{len(carried)} von {len(judged)} Strategien profitieren belastbar vom Regime – "
                "nur diese umschalten, die übrigen ohne Regime-Bindung handeln.")
    else:
        text = ("Keine Strategie läuft in ihrem Regime belastbar besser als außerhalb – "
                "das Regime trägt hier nicht als Schalter.")
    return {"ok": bool(judged) and len(carried) == len(judged), "min_trades": MIN_TRADES,
            "t_good": T_GOOD, "strategies": out, "text": text}
