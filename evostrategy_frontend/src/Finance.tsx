import { useEffect, useState } from "react";
import { api, money, monthLabel, percent, type DataSource, type Metrics, type Settings } from "./api";
import { LineChart } from "./charts";
import { Loading, useLoad } from "./hooks";

export function DataSourceNote({ source }: { source: DataSource }) {
  return source.demo_documents > 0
    ? <span className="demo-badge" title={source.note}> · Demo data: {source.note}</span>
    : <span> · {source.note}</span>;
}

// --------------------------------------------------------------------------- runway

export function RunwayView({ version, go }: { version: string; go: () => void }) {
  const { data, error } = useLoad(api.runway, [version]);
  if (!data) return <Loading error={error} />;
  if (!data.configured) {
    return (
      <section className="card empty-state">
        <h2>Cash balance needed</h2>
        <p>Documents tell us revenue and costs, not how much cash is in the bank. Enter your current balance once and the runway is projected from verified cash flow.</p>
        <div className="ready-actions"><button className="workspace-button" onClick={go}>Open settings</button></div>
      </section>
    );
  }
  if (data.error) return <div className="notice">{data.error}</div>;
  const history = data.history!;
  const projection = data.projection!;
  const horizon = Math.min(projection.months.length, Math.max(12, (data.runway_months ?? 0) + 3, (data.runway_months_range?.optimistic ?? 0) + 2));
  const labels = [...history.months, ...projection.months.slice(0, horizon)];
  const h = history.balance.length;
  const pad = (values: number[]) => [...Array(h - 1).fill(null), history.balance[h - 1], ...values.slice(0, horizon)];
  const level = Math.round((data.confidence_level ?? 0.85) * 100);
  const range = data.runway_months_range;
  return (
    <>
      <p className="trace">
        <span className="trace-dot" />
        Cash {money(data.cash_balance, true)} at end of {monthLabel(data.cash_as_of!)} ({data.cash_source})
        {data.traceability && <> · cash flow from {data.traceability.verified_records} verified records<DataSourceNote source={data.traceability.data_source} /></>}
      </p>
      <div className="kpi-grid three">
        <div className="kpi"><span>Runway</span><strong>{data.runway_months ? `${data.runway_months} mo` : "—"}</strong><small>{data.cash_out_month ? `cash out ≈ ${monthLabel(data.cash_out_month)}` : data.burning_cash ? "beyond 36 months" : "not burning cash"}</small></div>
        <div className="kpi"><span>Net cash flow / month</span><strong className={data.burning_cash ? "neg" : "pos"}>{money(-(data.monthly_net_burn ?? 0), true)}</strong><small>trend of the last {h} months</small></div>
        <div className="kpi"><span>{level}% range</span><strong>{range?.pessimistic ? `${range.pessimistic} mo` : "> 36 mo"}</strong><small>pessimistic · optimistic {range?.optimistic ? `${range.optimistic} mo` : "> 36 mo"}</small></div>
      </div>
      <section className="card">
        <header className="card-head"><h3>Cash balance projection</h3><span className="mono-muted">{level}% interval</span></header>
        <LineChart labels={labels} divider={h - 1}
          series={[
            { name: "Cash (from verified cash flow)", values: [...history.balance, ...Array(horizon).fill(null)], color: "#141b2b" },
            { name: "Projection", values: pad(projection.point), color: "#4f46e5", dashed: true },
            { name: "Zero", values: labels.map(() => 0), color: "#c2410c", dashed: true },
          ]}
          band={{ lower: pad(projection.lower), upper: pad(projection.upper), color: "#4f46e5", label: `${level}% interval` }}
        />
        <p className="muted small">{data.summary} Method: {data.method}.</p>
      </section>
    </>
  );
}

// --------------------------------------------------------------------------- settings

export function SettingsView({ onSaved }: { onSaved: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [budgets, setBudgets] = useState<Record<string, string>>({});
  const [cash, setCash] = useState("");
  const [asOf, setAsOf] = useState("");
  const [headcount, setHeadcount] = useState("");

  useEffect(() => {
    api.settings().then((s) => {
      setSettings(s);
      setBudgets(Object.fromEntries(Object.entries(s.budgets).map(([k, v]) => [k, String(v)])));
      setCash(s.finance.cash_balance != null ? String(s.finance.cash_balance) : "");
      setAsOf(s.finance.cash_as_of ?? "");
      setHeadcount(s.finance.headcount != null ? String(s.finance.headcount) : "");
    }).catch((e: Error) => setError(e.message));
    // budgets are for costs: offer the verified expense categories
    api.overview().then((o) => setCategories(o.budget.categories.map((c) => c.category)))
      .catch(() => { /* no data yet: only configured budgets are listed */ });
  }, []);

  const save = async () => {
    setError(""); setSaved("");
    const parsed: Record<string, number> = {};
    for (const [category, value] of Object.entries(budgets)) {
      if (value.trim() === "") continue;
      const number = Number(value.replace(/[,$\s]/g, ""));
      if (!Number.isFinite(number) || number <= 0) { setError(`Budget for ${category} must be a positive number.`); return; }
      parsed[category] = number;
    }
    const cashNumber = cash.trim() === "" ? null : Number(cash.replace(/[,$\s]/g, ""));
    if (cashNumber !== null && !Number.isFinite(cashNumber)) { setError("Cash balance must be a number."); return; }
    if (asOf && !/^\d{4}-\d{2}$/.test(asOf)) { setError("'Cash as of' must be a month like 2013-09."); return; }
    try {
      const result = await api.saveSettings({
        budgets: parsed,
        finance: { cash_balance: cashNumber, cash_as_of: asOf || null, headcount: headcount ? Number(headcount) : null },
      });
      setSettings(result);
      setSaved("Saved. Analytics, runway and what-if now use these values.");
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save settings."); }
  };

  if (!settings) return <Loading error={error} />;
  const rows = Array.from(new Set([...categories, ...Object.keys(budgets)])).sort();
  return (
    <div className="grid-2">
      <section className="card">
        <header className="card-head"><h3>Cash & people</h3></header>
        <div className="form-stack">
          <label>Cash balance (USD)<input inputMode="decimal" value={cash} onChange={(e) => setCash(e.target.value)} placeholder="e.g. 250000" /></label>
          <label>Cash as of (month)<input value={asOf} onChange={(e) => setAsOf(e.target.value)} placeholder="YYYY-MM — blank = latest verified month" /></label>
          <label>Current headcount<input type="number" min={1} value={headcount} onChange={(e) => setHeadcount(e.target.value)} placeholder="used by what-if" /></label>
        </div>
        {settings.finance.source && <p className="muted small">Current values: {settings.finance.source}.</p>}
      </section>
      <section className="card">
        <header className="card-head"><h3>Annual expense budgets</h3><span className="mono-muted">blank = prior year +5%</span></header>
        <div className="form-stack">
          {rows.length === 0 && <p className="muted">Categories appear here once documents are loaded.</p>}
          {rows.map((category) => (
            <label key={category}>{category}
              <input inputMode="decimal" value={budgets[category] ?? ""} onChange={(e) => setBudgets((b) => ({ ...b, [category]: e.target.value }))} placeholder="default" />
            </label>
          ))}
        </div>
      </section>
      <div className="settings-actions">
        <button className="workspace-button" onClick={save}>Save settings</button>
        {saved && <span className="pos">{saved}</span>}
        {error && <span className="form-error">{error}</span>}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- evaluation

const pass = (ok: boolean) => <span className={`pill ${ok ? "ok" : "warn"}`}>{ok ? "Meets target" : "Below target"}</span>;

export function EvaluationView({ version }: { version: string }) {
  const { data, error } = useLoad<Metrics>(api.metrics, [version]);
  if (!data) return <Loading error={error} />;
  const e = data.evaluation;
  const live = data.live_review_efficiency;
  return (
    <>
      <div className="grid-2">
        <section className="card">
          <header className="card-head"><h3>Review effort — this workspace</h3>{live.reduction !== null && pass(live.meets_target)}</header>
          <p className="big-number">{percent(live.reduction, 1)} <small>less manual checking</small></p>
          <p className="muted small">{live.documents_cleared_automatically} of {live.documents_needing_reconciliation} reconcilable documents were cleared automatically; {live.documents_needing_a_human} need a person. {live.caveat}</p>
        </section>
        <section className="card">
          <header className="card-head"><h3>System checks</h3></header>
          <ul className="assumptions">
            <li>Audit log: {data.audit_chain.intact ? `intact (${data.audit_chain.chained} chained entries)` : "TAMPERING DETECTED"}</li>
            <li>Second OCR engine (PaddleOCR): {data.second_ocr_engine}</li>
          </ul>
        </section>
      </div>
      {!e && <div className="notice">No evaluation report yet. Run <code>{data.how_to_refresh}</code> on the server.</div>}
      {e && (
        <>
          <p className="trace"><span className="trace-dot" />Last full evaluation {e.generated_at} · refresh with <code>{data.how_to_refresh}</code></p>
          <section className="card flush table-wrap">
            <table className="data-table">
              <thead><tr><th>Hypothesis</th><th>Data</th><th>Result</th><th>Target</th><th></th></tr></thead>
              <tbody>
                {e.h1_extraction.results.map((r) => (
                  <tr key={r.dataset}><td>H1 OCR &amp; extraction</td><td>{r.dataset}</td><td className="mono">{r.correct}/{r.fields} = {percent(r.accuracy, 1)}</td><td>≥ 92%</td><td>{pass(r.meets_target)}</td></tr>
                ))}
                {e.h2_reconciliation.results.map((r) => (
                  <tr key={r.dataset}><td>H2 Reconciliation</td><td>{r.dataset}</td><td className="mono">P {r.precision.toFixed(3)} · R {r.recall.toFixed(3)}</td><td>P ≥ 0.90 · R ≥ 0.88</td><td>{pass(r.meets_target)}</td></tr>
                ))}
                {Object.entries(e.h3_forecasting.metrics ?? {}).map(([metric, m]) => (
                  <tr key={metric}><td>H3 Forecast</td><td>{metric} · {e.h3_forecasting.history_months} months (demo ledger)</td>
                    <td className="mono">holdout {m.holdout_6m_mape.ensemble}% · rolling {m.rolling_3m_mape.ensemble}%</td><td>MAPE ≤ 15%</td>
                    <td>{pass(m.meets_target_holdout && m.meets_target_rolling)}</td></tr>
                ))}
                <tr><td>H4 Review effort</td><td>demo dataset</td><td className="mono">{percent(e.h4_review_efficiency.demo.reduction, 1)}</td><td>≥ 60% less</td><td>{pass(e.h4_review_efficiency.demo.meets_target)}</td></tr>
                {e.h4_review_efficiency.by_problem_rate.map((p) => (
                  <tr key={p.problem_share}><td>H4 Review effort</td><td>benchmark, ~{percent(p.problem_share)} of orders with a problem</td><td className="mono">{percent(p.reduction, 1)}</td><td>≥ 60% less</td><td>{pass(p.meets_target)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <p className="muted small">The full method and limits for each number are in docs/EVALUATION.md.</p>
        </>
      )}
    </>
  );
}
