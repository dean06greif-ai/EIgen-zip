import React, { useState } from 'react';
import { Path } from '@phosphor-icons/react';

const AUTO = '#00E5A0';
const MANUAL = '#FFB020';
const STEPS = [
  ['0', 'Regime-Assistent', 'du', 'Ein Klick je Anlageklasse. Festes Rezept (Makro × Haupt), keine Suche. Sagt dir per Ampel, ob Regime bei diesen Assets überhaupt etwas taugen. Rot = hier aufhören.'],
  ['1', 'Coins, Timeframe, Zeitraum', 'du', '3–8 ähnlich laufende Coins (Asset-Korrelation hilft), 1h oder 4h, ≥ 540 Tage, Training 75 %.'],
  ['D', 'Endlos-Suche (Autopilot)', 'du', 'Einmal starten, „Vollautomatik“ anlassen. Sucht die beste Erkennung; der Makro-Check aus Abschnitt 0 läuft am Ende von selbst mit.'],
  ['→', 'Regime suchen & speichern', 'auto', 'Analyse mit der besten Erkennung – wird automatisch eingereiht, wenn die Suche wirklich besser war.'],
  ['→', 'Ablation', 'auto', 'Pflicht-Nachweis für die Freigabe (welche Bausteine helfen wirklich). Gleiche Coins/Timeframe.'],
  ['→', 'Partial Pooling', 'auto', 'Nur wenn die Analyse als Gruppe taugt (≥ 3 Coins, Training < 100 %). Gruppen-Struktur + ein vorsichtiger Skalen-Faktor je Coin.'],
  ['→', 'Fairer Vergleich', 'auto', 'Gruppe vs. Pooling vs. Coin-Modell auf demselben ungesehenen Zeitraum – Grundlage für den Champion je Asset.'],
  ['✓', 'Champion & Freigabe', 'du', 'Champion-Modus wählen (Vorschlag/Automatisch), dann „Beobachten (Shadow)“. „Wirksam“ erst nach genug Shadow-Trades. Diese Entscheidung bleibt bewusst bei dir.'],
];

/** Roter Faden durchs Regime-Lab: was du klickst und was die Vollautomatik erledigt. */
export default function RegimeLabFlow() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rl-help" data-testid="regime-lab-flow">
      <button className="opt-chip" onClick={() => setOpen(!open)} data-testid="regime-lab-flow-toggle"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <Path size={12} weight="bold" /> {open ? 'Ablauf ausblenden' : 'Ablauf in 3 Klicks: was du tust – was automatisch läuft'}
      </button>
      {open && (
        <div className="rl-help-body" data-testid="regime-lab-flow-body">
          {STEPS.map(([no, title, who, txt], i) => (
            <div key={title} className="rl-help-row" data-testid={`regime-lab-flow-step-${i}`}>
              <b><span className="mono">{no}</span> {title}{' '}
                <span style={{ color: who === 'auto' ? AUTO : MANUAL, fontWeight: 400 }}>
                  {who === 'auto' ? '· automatisch' : '· dein Klick'}
                </span>
              </b>
              <span className="opt-small">{txt}</span>
            </div>
          ))}
          <div className="opt-small" style={{ marginTop: 6 }}>
            Automatische Schritte landen in der Job-Warteschlange (Nacht-Serie) und laufen auch bei geschlossenem Browser.
            Sie rechnen und speichern nur – am Handel ändert sich nichts, bis du einen Champion bzw. eine Freigabe setzt.
            Die Werkzeuge A–C (EMA-Vergleich, Auto-Kalibrierung, einzelne Ablation) brauchst du nur noch zum gezielten Nachjustieren.
          </div>
        </div>
      )}
    </div>
  );
}
