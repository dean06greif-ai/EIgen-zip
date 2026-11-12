# Fortschritt Regime-Erkennung

> Wenn der Chat abbricht: hier steht der genaue Stand. Nächster Schritt = erster offener Punkt unten.
> Plan: `REGIME_UMSETZUNGSPLAN.md`

## Erledigt
- [x] 24.09. Referenz v2, Skill, balanciert, Richtungs-Phase (regime_reference, regime_truth, regime_quality)
- [x] 24.09. Macro-F1 + Cohens κ (Note, Autopilot-Score, Ablation, Freigabe-Delta)
- [x] 24.09. Crash-Wick-Endlosschleife Pivot-Scan (regime_kombi, regime_reactive) – DOT 70 d → 0,6 d
- [x] 24.09. Hinweis „alte Referenz v1“ auf der Qualitätskarte

## In Arbeit / offen (Reihenfolge)
- [x] 12/2026 Mehrere Timeframes schlüssig verbunden (Abschnitt 0 ↔ Endlos-Suche):
  - Drei Ebenen: **Makro** = festes Rezept je Klasse aus Abschnitt 0 (Filter, nie gesucht) ·
    **Haupt** = Erkennung der Endlos-Suche (gewählter bzw. per Timeframe-Kette bester TF) ·
    **Handel** = 5m–1h Timing. `htf_confirm` bleibt Rauschfilter innerhalb der Haupt-Erkennung.
  - Timeframe-Kette bleibt UNTER dem Makro-TF der Anlageklasse (`regime_tf_chain.build_chain(tf, max_minutes)`,
    z.B. Krypto 4h → 2h·4h·8h statt …·1d). Ohne Kette unverändert.
  - Makro-Check nach jedem Autopilot-Lauf (`services/regime_macro_check.py`, rein auswertend, ändert
    Suche/Score nicht): Nutzen-Note „nur Haupt“ vs. „Makro × Haupt“ + Konflikt-Anteil → `result.macro_check`,
    Anzeige unter dem Autopilot-Ergebnis (`autopilot-macro-check`).
  - Copilot kennt Ziel, Ebenen, Weg und die letzten Autopilot-Läufe inkl. „Nächster Schritt“
    (`regime_copilot_knowledge.search_path_lines/search_lines/next_steps`).
  - Abschnitt 0 (Regime-Assistent) läuft als normaler Regime-Lab-Job `assistant`: Haupt-Balken mit
    Pausieren/Abbrechen/Notfall-Reset, Cloud oder lokaler Worker (ab 1.25.0, `fn="assistant"`),
    Ergebnis speichert der Server (`persist_worker_result`).
  - Fix Makro-Ebene (Abschnitt 0): festes Jump-Zentrum 0.5 bei 7d/45d lag über dem 97. Perzentil der
    Features -> Makro fast immer „seitwärts“ (BTC 720 T: 100 %), Note Makro „–“, Kombination = Haupt.
    Jetzt `regime_hierarchy.noise_center()` (gleiches Rausch-Verhältnis wie Lab-Standard 1d/14d/0.6):
    Makro 0.25, langsames Makro (1w) 0.19. Krypto 8 Coins: Makro seitwärts 96 % -> ~60 %.
  - Befund Krypto rot: kein Rechenfehler – bei XRP/ADA/DOGE/AVAX ist die Trennschärfe negativ (nach „auf“
    fiel der Kurs in 1–3 Tagen), BTC/ETH/BNB Haupt-Note 71–88. Die Klassen-Ampel ist der Median.
  - Tests: `tests/test_worker_regime_bridge_1206.py`.
- [x] 1.4 Regime-Nutzen (services/regime_utility.py → Referenz-Dict, Qualitätskarte „Regime-Nutzen / Richtung bestätigt / Seitwärts-Ruhe“, Autopilot-Kennzahlen)
- [x] 1.5 Autopilot: Duplikat-Cache, Plateau-Stopp (UI-Feld, Standard 300), erweiterter Suchraum (kombi_ema ab 3, dominance ab 0.5, ema ab 2), Top-10-Neustart alle 120 stagnierende Runden
- [x] 1.6 Tests + Testing-Agent (iteration_25: 66/66 Backend, Frontend Plateau-Feld ok)
- [x] 2.1 Höherer-TF-Filter: regime_reactive.htf_filter/htf_slope (in classify, nur Live-Sicht), Konfig-Schlüssel in regime_engine (Standard AUS = rückwärtskompatibel, UI-Gruppe „Höherer-TF-Filter“), Autopilot-Suchraum. **Ergebnis: Ziel erreicht** (siehe Messwerte)
- [x] 2.2 Richtungs-Modus: bereits gegeben – Shadow-Statistik gruppiert nach „strukturell bär/bulle/seitwärts“ (ai_rewards.structural_regime_of) → 3×30 = 90 Trades. Meine frühere Aussage „270“ war falsch; keine Änderung nötig
- [x] 2.5 Autopilot-Score: Regime-Nutzen (NUR Trainingsteil: utility_train_sign_hit_pct, ±0,5 Punkte je %-Punkt über/unter 50 %, gedeckelt ±5)
- [x] 2.3 Crash-Wick-Robustheit: durch Fix 1.3 (Pivot-Scan) abgedeckt; Warnhinweis je Coin optional später
- [x] 2.4 Analysen neu bewerten: POST /api/regime-lab/{aid}/reevaluate (Cloud oder lokal, Worker 1.15.0), lab.run_reevaluate/apply_reevaluation, Knopf „Neu bewerten (aktuelle Bewertung)“ unter der Qualitätskarte; Modell/Regime bleiben, nur Kennzahlen je Symbol neu
- [ ] 3.x Funding/OI, Markt-Breite
- [ ] 4.x Kette Autopilot→Analyse→Ablation, Kombi-Kalibrierung v2

## Messwerte (BTC/ETH/SOL 1h, 1080 d, Holdout) – Stand 24.09.
| Variante | Roh-Treffer | Macro-F1 | κ | Richtungs-Phase | Regime-Nutzen 3 d | Richtung bestätigt |
|---|---|---|---|---|---|---|
| gespeichert (Krypto 1h) | ~66 % | 44,0 | 12,6 | 22,9 d | +1,2 % | 52,6 % |
| kombi ema 8 / dominance 5 | – | 47,6 | 20,0 | 7,5 d | +1,6 % | 53,2 % |
| **+ HTF 4 d, thr 0,2 (EMPFOHLEN)** | – | **52,9** | **26,8** | **5,6 d** | **+1,8 %** | 52,4 % |
| + HTF 2 d, thr 0,2 | – | 55,4 | 29,6 | 3,4 d (< 4 = flackert) | +1,5 % | 48,9 % (< Münzwurf) |
| + HTF 4 d + Hochstufen 2,0 | – | 52,5 | 28,2 | 3,6 d | +1,2 % | 51,0 % |
Hochstufen (htf_promote_thr) erhöht den balancierten Treffer, verschlechtert aber den Regime-Nutzen → aus lassen.
Empfohlene Start-Konfiguration für den Autopilot: detector kombi, kombi_ema_days 8, kombi_dominance_days 5,
htf_confirm an, htf_days 4, htf_thr 0.2 (Rest wie „Regime Krypto 1h“).

## Was DU danach tun musst
1. Deploy auf Render (Branch pushen) + Worker-Paket ≥ 1.14.0 neu herunterladen
2. Autopilot neu starten (1h, Krypto-Kern, Ziel 4–14 d) – alte Scores nicht mit neuen vergleichen
3. Analyse ausführen → Qualitätskarte: Macro-F1, κ, Regime-Nutzen prüfen

## Log
- 24.09. 2.4 + 2.5 fertig, Unit-Tests 42 grün, Build ok. Nächster Schritt: Testing-Agent Phase 2, danach 4.1 (Ablation-Kette) / 4.2 (Kombi-Kalibrierung v2), 3.x Funding/OI
- 24.09. 2.1 fertig + gemessen (Macro-F1 44→53, κ 13→27, Richtungs-Phase 23→5,6 d, Nutzen 1,2→1,8 %). Nächster Schritt: 2.5 Regime-Nutzen in Autopilot-Score, dann 2.4
- 24.09. Start Phase 2: 2.1 Code fertig, 2.2 geprüft (schon vorhanden)
- 24.09. 1.6 erledigt (Testing-Agent grün). Nächster Schritt: 2.1
- 24.09. 1.4 + 1.5 umgesetzt, Unit-Tests grün (tests/test_pruefung_2409.py 28), Build ok – nächster Schritt 1.6 Testing-Agent
- 24.09. Plan erstellt, Start Phase 1.4
