# Makro-Stufe im Regime-Autopilot (06/2026)

## Einschätzung
- Regime-Lab → Dynamische Strategien ist methodisch sauber: kausale Live-Labels, Holdout, Walk-Forward,
  Champion-Strafe, Shadow-Freigabe. Bisher fehlt kein Rechenbaustein, sondern belastbarer **Edge**.
- Schritt 0 (festes Rezept Makro 1d × Haupt 8h) ist ein Gesundheits-Check und kein Suchwerkzeug. Nicht optimieren.
  Er bleibt erhalten (Ampel für den KI-Trader), ist im Lab aber eingeklappt.
- Übergeordnete Zeitebenen sind **kein Wundermittel**. Sie filtern Gegen-Trend-Rauschen, kosten aber Phasen
  (weniger Trades, späterer Einstieg). Ob das hilft, hängt vom Asset ab. Deshalb wird es nur nach Messung übernommen.

## Umsetzung
- `services/regime_macro_filter.py`: Makro-Ebene als festes Jump-Modell auf langsamer Zeitskala in Tagen
  (Tages-Skala 7/45 d ≈ 1D, Wochen-Skala 14/60 d ≈ 1W). Weil die Features in Tagen und vola-normiert sind,
  gibt es keine Aggregation. Lab und Live rechnen also bit-gleich.
  Konfig: `macro_filter` = off | soft | strict, `macro_scale` = day | week. Standard ist `off`, dann ist das Verhalten unverändert.
  Der Filter greift in `regime_reactive.classify` direkt nach dem HTF-Filter. Damit gilt er überall gleich:
  in der Analyse, im KI-Trader und in den dynamischen Strategien.
- `services/regime_macro_stage.py`: Diese Stufe läuft nach jeder Autopilot-Suche und ist fest eingeschaltet.
  1. Es gibt 4 feste Kandidaten. Es findet keine Suche statt, also entsteht kein Such-Overfitting.
  2. Ausgewählt wird nur auf dem Training, nach dem höchsten Edge-t: Jede Live-Trendphase zählt als ein Trade
     nach Kosten, die Phasen aller Symbole werden zusammengelegt. Auswahl-Score und Note dürfen dabei nicht fallen.
  3. Danach wird einmal im Holdout bestätigt. Dafür muss gelten: t ≥ 1,0, t ≥ Haupt-t + 0,5 und
     mindestens 8 Holdout-Phasen. Sonst bleibt `macro_filter=off`.
- Bestehende Erkennungen bleiben gültig. Die Suche läuft immer auf der Haupt-Ebene, Makro-Schlüssel werden aus
  Start und Warmstart-Seeds entfernt. Jeder neue Lauf (mit Warmstart aus alten Läufen) prüft die Makro-Stufe neu.
- Autopilot-Bedienung: Warmstart, Note-Schutz und Makro-Stufe sind fest an. Limits, Grundgerüst-Suche,
  Vollautomatik und Timeframe-Kette liegen unter „Experte“.

## Tests
`backend/tests/test_macro_stage_0626.py` prüft Folgendes: Filter aus ist bit-gleich, soft/strict-Semantik,
Aufwärmphase ist fail-open, Seeds werden bereinigt, Entscheidungsregeln, End-to-End-Stufe.

## Nachtrag: Live = Lab, Schalter-Vergleich, Worker (06/2026)
- **Befund (gemessen, BTC/ETH/BNB 4h und 1h, 720 Tage):** Das Live-Regime (KI-Trader, dynamische Strategien) wich bei
  jump-Modellen und bei Modellen mit Makro-Filter in 10–45 % der Zeitpunkte vom Lab-Regime ab. Zwei Ursachen:
  1. Die Mindesthaltedauer merkt sich den letzten Wechsel. Ihr Ergebnis hängt deshalb vom Start der Historie ab.
  2. Makro-Filter und Jump-Glättung waren nach 3 Halbwertszeiten noch nicht eingeschwungen.
- **Fix:** `services/regime_hold.py` prüft exakt, ob das Live-Label vom Fenster-Start unabhängig ist.
  `services/regime_live_history.py` verlängert die Live-Historie schrittweise, bis das zutrifft (höchstens 400 Tage).
  Live-Warmup für Makro-Filter und Jump: 5 Halbwertszeiten (Tages-Skala 225 Tage, Wochen-Skala 300 Tage).
  Die Lab-Berechnung selbst ist unverändert, alte Erkennungen liefern im Lab dieselben Labels.
- **KI-Trader-Start:** `structural_regime.resolve` wartet höchstens 20 s auf eine frische Berechnung. Danach gilt der
  letzte Stand als `stale`, die Berechnung läuft im Hintergrund weiter.
- **Schalter-Vergleich:** Der Walk-Forward liefert zusätzlich `regime_split_macro`: dieselben Holdout-Trades, Regime
  einmal ohne und einmal mit Makro-Filter bestimmt. Anzeige nebeneinander im Lab und in der Werkbank
  (`RegimeSplitMacroCompare.js`). Kostet nur eine zweite Klassifikation, keinen zweiten Backtest.
- **Worker 1.27.0:** hält Windows wach, solange er läuft (`WORKER_KEEP_AWAKE=0` schaltet das ab).
- **Prüfskripte:** `scripts/majors_macro_run.py` (Autopilot je Coin ohne DB), `scripts/e2e_regime_chain.py`
  (Lab-Modell → Live-Fenster → Walk-Forward → Signal). Tests: `backend/tests/test_live_hold_sync_0626.py`.
- **Offen:** Der dynamische Ergebnis-Backtest (`dynamic_backtest.simulate_dynamic`) lädt weiter nur Testfenster + Warmup.
  Bei Modellen mit häufigen Wechseln kann sein Regime-Verlauf deshalb leicht vom Walk-Forward abweichen.
