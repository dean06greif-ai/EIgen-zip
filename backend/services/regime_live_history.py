"""Live-Historie für die Regime-Erkennung: so viel laden, bis das Live-Label eingerastet ist.

Start = Detektor-Warmup (`regime_engine.required_history_days`). Hängt das Label wegen der
Mindesthaltedauer noch vom Fenster-Start ab (services/regime_hold), wird die Historie
schrittweise verlängert (bis MAX_DAYS). Die gefundene Länge wird je Modell × Symbol gemerkt,
damit der nächste Refresh sofort passend lädt.
"""
from typing import Awaitable, Callable, Dict, Optional, Tuple

MAX_DAYS = 400
_DAYS: Dict[Tuple[str, str], int] = {}


def next_days(days: int) -> int:
    return min(int(days * 1.5) + 15, MAX_DAYS)


def _key(model: Dict, symbol: str) -> Tuple[str, str]:
    from services import market_context as mc
    return (str(mc.model_fingerprint(model)), symbol)


async def load_synced(model: Dict, symbol: str, base_days: int,
                      load: Callable[[int], Awaitable[list]],
                      min_hold_days: Optional[float] = None) -> Tuple[list, int, Optional[bool]]:
    """(Kerzen, geladene Tage, eingerastet?) – eingerastet None = nicht prüfbar (Alt-Modell)."""
    from services import regime as rg
    key = _key(model, symbol)
    days = max(int(base_days), _DAYS.get(key, 0))
    while True:
        candles = await load(days)
        try:
            ok = (rg.hold_synced(model, candles) if min_hold_days is None
                  else rg.hold_synced(model, candles, min_hold_days)) if len(candles) else None
        except Exception:  # noqa: BLE001 – reine Zusatzprüfung, fail-open
            ok = None
        if ok is not False or days >= MAX_DAYS:
            if ok:
                _DAYS[key] = days
            return candles, days, ok
        days = next_days(days)
