import React from 'react';

const fmt = (v, d = 3) => (v === null || v === undefined ? '–' : Number(v).toFixed(d));
const cell = { padding: '2px 10px 2px 0', textAlign: 'left', whiteSpace: 'nowrap' };

function Side({ s }) {
  if (!s) return <td style={cell}>–</td>;
  const good = s.verdict === 'Regime trägt';
  return (
    <td style={cell}>
      Ø {fmt(s.avg_in)} ({s.trades_in}) / Ø {fmt(s.avg_out)} ({s.trades_out}) · t {s.t ?? '–'} ·{' '}
      <b style={{ color: good ? '#00E5A0' : undefined }}>{s.verdict}</b>
    </td>
  );
}

// „Regime als Schalter“ ohne / mit Makro-Filter nebeneinander (gleiche Holdout-Trades).
export default function RegimeSplitMacroCompare({ base, alt, testPrefix = 'split-macro' }) {
  if (!base || !alt) return null;
  const [off, on] = alt.alt_has_macro ? [base, alt] : [alt, base];
  const onLabel = alt.alt_has_macro ? alt.macro_label : alt.active_label;
  const byId = Object.fromEntries((on.strategies || []).map(s => [String(s.regime), s]));
  const carried = x => (x.strategies || []).filter(s => s.verdict === 'Regime trägt').length;
  const diff = carried(on) - carried(off);
  return (
    <div className="opt-small" style={{ margin: '6px 0' }} data-testid={testPrefix}
      title="Dieselben Holdout-Trades, nur das Regime bei Einstieg wird einmal ohne und einmal mit Makro-Filter bestimmt. Je Zelle: im Regime Ø PnL (Trades) / außerhalb Ø PnL (Trades) · t-Wert. t ≥ 2 = belastbar. Reine Auswertung – die aktive Erkennung wird nicht verändert.">
      Schalter-Vergleich Makro-Filter:{' '}
      <b data-testid={`${testPrefix}-summary`} style={{ color: diff > 0 ? '#00E5A0' : diff < 0 ? '#FFB74D' : undefined }}>
        {diff > 0 ? `mit Makro-Filter tragen ${diff} Regime mehr` : diff < 0 ? `mit Makro-Filter tragen ${-diff} Regime weniger` : 'kein Unterschied in der Tragfähigkeit'}
      </b>
      {' '}({alt.alt_has_macro ? 'aktiv: ohne Makro-Filter' : `aktiv: ${alt.active_label}`})
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', marginTop: 4 }}>
          <thead>
            <tr>
              <th style={cell}>Regime-Strategie</th>
              <th style={cell} data-testid={`${testPrefix}-head-off`}>ohne Makro-Filter</th>
              <th style={cell} data-testid={`${testPrefix}-head-on`}>mit Makro-Filter ({onLabel})</th>
            </tr>
          </thead>
          <tbody>
            {(off.strategies || []).map(s => (
              <tr key={String(s.regime)} data-testid={`${testPrefix}-row-${s.regime}`}>
                <td style={cell}>{s.label}</td>
                <Side s={s} />
                <Side s={byId[String(s.regime)]} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
