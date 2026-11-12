"""Lern-Auslöser jenseits von Trade-Close (12/2026).

Der Learner lief nur nach geschlossenen KI-Trades – ohne Trades (z.B. 20 h) stand er
still, obwohl es Lernstoff gab:
  - verpasste gute Trades: von Lektionen blockierte HOLDs, die laut HOLD-Gegenprobe
    (services/lesson_counterfactual -> ai_lesson_cf) Gewinner geworden wären,
  - hinderliche Lektionen laut Lektions-Bilanz (services/lesson_impact).
Reine Entscheidung (`decide`) + dünne DB-Helfer. Kosten-Schutz über Mindestabstände.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MISSED_R_MIN = 0.5               # ab +0.5 R netto zählt ein verhinderter Trade als „verpasst gut“
MISSED_GAP_SEC = 6 * 3600        # max. 1 Lernlauf aus verpassten Trades je 6 h
REEVAL_GAP_SEC = 24 * 3600       # max. 1 automatische Neubewertung je 24 h
CHECK_EVERY_SEC = 900            # DB-Prüfung höchstens alle 15 min


def _missed_query(since_iso: Optional[str]) -> Dict:
    q = {"status": "done", "r": {"$gte": MISSED_R_MIN}}
    if since_iso:
        q["reviewed_at"] = {"$gt": since_iso}
    return q


async def fresh_inputs(db, since_iso: Optional[str], config: Optional[Dict] = None) -> Dict:
    """Neuer Lernstoff seit `since_iso`: geschlossene Trades, verpasste gute Trades,
    aktuell hinderliche Lektionen."""
    tq = {"strategy_id": "ai_trader", "status": "closed"}
    if since_iso:
        tq["closed_at"] = {"$gt": since_iso}
    trades = await db.auto_trades.count_documents(tq)
    missed = await db.ai_lesson_cf.count_documents(_missed_query(since_iso))
    hinder: List[str] = []
    try:
        from services.lesson_impact import lesson_impact
        # Bilanz unabhängig vom Prompt-Schalter lesen (der steuert nur den Analyse-Prompt)
        rows = (await lesson_impact.report()).get("rows") or []
        hinder = [r.get("title") or r.get("id") for r in rows if r.get("verdict") == "hinderlich"]
    except Exception as e:  # noqa: BLE001 – fail-open
        logger.debug(f"Lektions-Bilanz für Lern-Auslöser nicht lesbar: {e}")
    return {"trades": trades, "missed": missed, "hinderlich": len(hinder),
            "hinderlich_titles": [str(t) for t in hinder if t][:5]}


def decide(fresh: Dict, now: float, last_learn_ts: float, last_reeval_ts: float) -> Optional[str]:
    """Welcher Lauf ist fällig? (rein) – 'missed_trade', 'reevaluate' oder None."""
    if fresh.get("missed", 0) > 0 and now - last_learn_ts > MISSED_GAP_SEC:
        return "missed_trade"
    if fresh.get("hinderlich", 0) > 0 and now - last_reeval_ts > REEVAL_GAP_SEC:
        return "reevaluate"
    return None


def idle_reason(fresh: Dict, reeval_recent: bool = False) -> str:
    """Klartext für Supervisor/UI, warum gerade (nicht) gelernt wird (rein).
    `reeval_recent`: hinderliche Lektionen wurden im Mindestabstand schon neu bewertet."""
    pending = {k: fresh.get(k) for k in ("trades", "missed", "hinderlich")}
    if reeval_recent:
        pending["hinderlich"] = 0
    if not any(pending.values()):
        return ("wartet: seit dem letzten Lernlauf keine neuen KI-Trades, keine verpassten "
                "guten Trades und keine hinderlichen Lektionen – kein Fehler")
    parts = []
    if fresh.get("trades"):
        parts.append(f"{fresh['trades']} neue Trades")
    if fresh.get("missed"):
        parts.append(f"{fresh['missed']} verpasste gute Trades")
    if fresh.get("hinderlich"):
        parts.append(f"{fresh['hinderlich']} hinderliche Lektionen")
    return "Lernstoff vorhanden (" + ", ".join(parts) + ") – Lauf folgt nach Mindestabstand"


async def missed_text(db, since_iso: Optional[str], limit: int = 6) -> str:
    """Prompt-Block: verpasste gute Trades (von Lektionen verhindert, wären Gewinner)."""
    rows = await db.ai_lesson_cf.find(_missed_query(since_iso), {"_id": 0}).sort(
        "r", -1).limit(limit).to_list(limit)
    if not rows:
        return ""
    lines = [f"- {r.get('symbol')} {r.get('action')} ({r.get('horizon')}) wäre {r.get('r'):+.2f} R netto "
             f"geworden – blockiert durch: {', '.join(map(str, r.get('blocked_by') or [])) or '?'}"
             for r in rows]
    return ("=== VERPASSTE GUTE TRADES (von Lektionen/Filtern verhindert, laut Gegenprobe Gewinner) ===\n"
            + "\n".join(lines)
            + "\nPrüfe, ob die blockierende Lektion zu streng ist: abschwächen/entfernen, wenn sie "
              "wiederholt gute Trades verhindert und keinen belegten Nutzen hat.")
