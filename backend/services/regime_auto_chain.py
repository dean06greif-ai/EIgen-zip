"""Vollautomatik nach der Endlos-Suche (Regime-Autopilot).

Die Folge-Analyse des Autopiloten trägt `auto_next` im Request-Body. Sobald ihr
Eintrag in der Job-Warteschlange fertig ist (Cloud oder lokaler Worker), hängt
dieses Modul die Schritte an, die man danach ohnehin immer braucht:

  ablation – Pflicht-Nachweis für die Freigabe (gleiche Coins/Timeframe)
  pooling  – nur wenn die Eignungs-Prüfung der Analyse grün ist (>= 3 Coins …)
  fair     – fairer Gleich-Zeitraum-Vergleich für den Champion je Asset

Übernommen/freigegeben wird dadurch nichts – das entscheidet weiter der
Champion-Modus bzw. die Freigabe. Alles fail-open.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STEPS = ("ablation", "pooling", "fair")
MAX_FAIR_KEYS = 8
DOC_PROJECTION = {"_id": 0, "chart": 0, "chart_emas": 0, "combined.per_symbol": 0, "per_coin": 0}


def steps_of(body: Optional[Dict]) -> List[str]:
    raw = (body or {}).get("auto_next") or []
    return [s for s in STEPS if s in raw] if isinstance(raw, (list, tuple)) else []


def ablation_body(doc: Dict, src: Dict) -> Dict:
    st = doc.get("settings") or {}
    out = {"symbols": list(doc.get("symbols") or []), "timeframe": doc.get("timeframe"),
           "days": doc.get("days"), "train_pct": st.get("train_pct"),
           "engine_config": st.get("engine_config") or {},
           "execution": src.get("execution") or "cloud"}
    if src.get("worker_id"):
        out["worker_id"] = src["worker_id"]
    return out


def pooling_body(doc: Dict) -> Dict:
    from services import regime_pooling
    return {"analysis_id": doc.get("id"), "symbols": list(doc.get("symbols") or []),
            "timeframe": doc.get("timeframe"), "days": doc.get("days"),
            "prior_phases": regime_pooling.PRIOR_PHASES, "auto_next": ["fair"]}


def plan(doc: Optional[Dict], src: Dict) -> Dict:
    """Welche Folge-Einträge entstehen aus einer fertigen Analyse? (rein)
    -> {items: [{kind, body, label}], fair_now: bool, pooling_skipped: [Gründe]}"""
    from services import regime_pooling
    steps = steps_of(src)
    out: Dict = {"items": [], "fair_now": False, "pooling_skipped": []}
    if not doc or not steps:
        return out
    name = doc.get("name") or doc.get("id")
    if "ablation" in steps and (doc.get("settings") or {}).get("engine") == "v2":
        out["items"].append({"kind": "regime_ablation", "body": ablation_body(doc, src),
                             "label": f"Auto · Ablation · {name}"})
    pooled = False
    if "pooling" in steps:
        chk = regime_pooling.source_check(doc)
        if chk["ok"]:
            pooled = True
            out["items"].append({"kind": "regime_pooling", "body": pooling_body(doc),
                                 "label": f"Auto · Pooling · {name}"})
        else:
            out["pooling_skipped"] = chk["reasons"]
    out["fair_now"] = "fair" in steps and not pooled
    return out


async def start_fair(db, symbols: List[str], timeframe: Optional[str]) -> List[str]:
    from services import regime_fair_compare as fair
    from services import regime_release, regime_selection
    res = await regime_selection.compute(db, list(symbols or []))
    band = regime_release.band_of_timeframe(timeframe) if timeframe else None
    keys = [k for k in res["results"] if not band or k.endswith(f"|{band}")][:MAX_FAIR_KEYS]
    return keys if fair.start_job(db, keys) else []


async def after_item(db, item: Dict) -> Dict:
    """Nach einem fertigen Serien-Eintrag die Folge-Schritte anstoßen."""
    body = item.get("body") or {}
    steps = steps_of(body)
    if item.get("status") != "done" or not steps or db is None:
        return {}
    if item.get("kind") == "regime_pooling":
        return {"fair": await start_fair(db, body.get("symbols"), body.get("timeframe"))} \
            if "fair" in steps else {}
    if item.get("kind") != "regime_analysis":
        return {}
    aid = (item.get("summary") or {}).get("analysis_id")
    doc = await db.regime_analyses.find_one({"id": aid}, DOC_PROJECTION) if aid else None
    p = plan(doc, body)
    from services import job_series
    queued = []
    for it in p["items"]:
        try:
            queued.append((await job_series.add_item(db, it["kind"], it["body"], label=it["label"]))["id"])
        except Exception as e:  # noqa: BLE001 – ein Schritt darf die anderen nicht verhindern
            logger.warning(f"Vollautomatik: {it['kind']} nicht eingereiht: {e}")
    out = {"queued": queued, "pooling_skipped": p["pooling_skipped"]}
    if p["fair_now"]:
        out["fair"] = await start_fair(db, doc.get("symbols"), doc.get("timeframe"))
    logger.info(f"Vollautomatik nach Analyse {aid}: {out}")
    return out
