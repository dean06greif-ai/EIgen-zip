"""Mindesthaltedauer (Hold-Sperre) der Live-Labels: ist ein Live-Fenster eingerastet?

Die Sperre in `regime_reactive.classify` merkt sich den letzten akzeptierten Wechsel. Ihr
Ergebnis hängt deshalb vom Startpunkt der Historie ab: ein kürzeres Live-Fenster kann bei
identischen Roh-Labels ein anderes Regime liefern als das Lab (gemessen 06/2026: bis 40 %
der Zeitpunkte bei jump-Modellen). Hier wird das exakt geprüft: die Sperre wird von JEDEM
möglichen Startzustand aus gerechnet. Liefern alle denselben Zustand, ist das Fenster
„eingerastet“ – das Live-Label ist dann unabhängig von älterer Historie (= Lab-Label).
Rein, ohne Seiteneffekte.
"""
from typing import Optional

import numpy as np

FOREIGN = -99   # steht für jedes Regime, das im Fenster nicht vorkommt


def sync_index(ids, warm: int, hold: int) -> Optional[int]:
    """Erster Index, ab dem die Hold-Sperre für alle Startzustände identisch ist (None = nie).
    ids = Roh-Labels ohne Sperre, gültig ab `warm`."""
    ids = np.asarray(ids, dtype=int)
    n, warm, hold = len(ids), max(int(warm), 0), int(hold or 0)
    if warm >= n:
        return None
    if hold <= 1:
        return warm
    labels = np.append(np.unique(ids[warm:]), FOREIGN)
    cur = np.repeat(labels, hold + 1)
    age = np.tile(np.arange(hold + 1), len(labels))
    for i in range(warm, n):
        r = ids[i]
        change = (cur != r) & (age >= hold)
        cur[change] = r
        age[change] = 0
        if cur.min() == cur.max():
            a = np.minimum(age, hold)
            if a.min() == a.max():
                return i
        age += 1
    return None


def synced(ids, warm: int, hold: int) -> bool:
    return sync_index(ids, warm, hold) is not None
