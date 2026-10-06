import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, humanize, money, monthLabel, percent,
  type CaseDetail, type CaseRow, type DocumentDetail, type DocumentRow, type Forecast,
  type Overview as OverviewData, type ReviewAction, type ScenarioInput, type ScenarioResult, type Summary,
} from "./api";
import { BarList, LineChart, Meter } from "./charts";

type View = "overview" | "review" | "documents" | "analytics" | "forecast" | "whatif" | "audit";

const NAV: Array<{ key: View; label: string; group: string }> = [
  { key: "overview", label: "Overview", group: "Workspace" },
  { key: "review", label: "Review queue", group: "Verification" },
  { key: "documents", label: "Documents", group: "Verification" },
  { key: "audit", label: "Audit log", group: "Verification" },
  { key: "analytics", label: "Analytics", group: "Intelligence" },
  { key: "forecast", label: "Forecast", group: "Intelligence" },
  { key: "whatif", label: "What-if", group: "Intelligence" },
];

const STATUS_TONE: Record<string, string> = {
  ESCALATED: "danger", MISSING: "warn", AMBIGUOUS: "warn", AUTO_RESOLVED: "info", MATCHED: "ok",
  ACCEPTED: "ok", CORRECTED: "info", REJECTED: "muted", RECONCILED: "ok", SINGLE_SOURCE: "neutral",
  PENDING_REVIEW: "warn", QUARANTINED: "muted",
};

function StatusPill({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="pill neutral">—</span>;
  return <span className={`pill ${STATUS_TONE[status] ?? "neutral"}`}>{humanize(status)}</span>;
}

function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    loader().then((value) => { setData(value); setError(""); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load data."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

function Loading({ error }: { error?: string }) {
  return error ? <div className="notice error">{error}</div> : <div className="loading">Loading…</div>;
}

function Traceability({ overview }: { overview: OverviewData }) {
  const t = overview.traceability;
  const pending = (t.status_counts.PENDING_REVIEW ?? 0) + (t.status_counts.QUARANTINED ?? 0);
  return (
    <p className="trace">
      <span className="trace-dot" />
      Built from {t.verified_records} verified records ({t.source_documents} source documents)
      {t.date_from && <> · {t.date_from} → {t.date_to}</>}
      {pending > 0 && <> · {pending} record{pending === 1 ? "" : "s"} excluded until reviewed</>}
    </p>
  );
}

// --------------------------------------------------------------------------- overview

function OverviewView({ summary, go }: { summary: Summary; go: (view: View) => void }) {
  const { data, error } = useLoad(api.overview, [summary.last_run_at, summary.reviewed_cases]);
  if (!data) return <Loading error={error} />;
  const m = data.monthly;
  return (
    <>
      <div className="kpi-grid">
        <div className="kpi"><span>Verified revenue</span><strong>{money(data.totals.revenue, true)}</strong><small>{m.months.length} months</small></div>
        <div className="kpi"><span>Verified expenses</span><strong>{money(data.totals.expense, true)}</strong><small>{data.expense_by_category.length} categories</small></div>
        <div className="kpi"><span>Profit</span><strong>{money(data.totals.profit, true)}</strong><small>{percent(data.totals.margin, 1)} margin</small></div>
        <button className="kpi attention" onClick={() => go("review")}>
          <span>Needs your review</span><strong>{summary.open_cases}</strong><small>Open review queue →</small>
        </button>
      </div>
      <div className="grid-2-1">
        <section className="card">
          <header className="card-head"><h3>Revenue vs expenses</h3><span className="mono-muted">verified only</span></header>
          <LineChart labels={m.months} series={[
            { name: "Revenue", values: m.revenue, color: "#4f46e5" },
            { name: "Expenses", values: m.expense, color: "#c2410c" },
          ]} />
        </section>
        <section className="card">
          <header className="card-head"><h3>Data integrity</h3></header>
          <div className="integrity">
            <div><strong>{percent(summary.verified_rate, 1)}</strong><span>of transactions passed the reconciliation gate</span></div>
            <ul className="status-list">
              {Object.entries(data.traceability.status_counts).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
                <li key={status}><StatusPill status={status} /><b>{count}</b></li>
              ))}
            </ul>
            {Object.keys(summary.discrepancy_types).length > 0 && (
              <>
                <h4>Open discrepancies</h4>
                <ul className="status-list">
                  {Object.entries(summary.discrepancy_types).map(([type, count]) => <li key={type}><span>{humanize(type)}</span><b>{count}</b></li>)}
                </ul>
              </>
            )}
          </div>
        </section>
      </div>
      <div className="grid-2">
        <section className="card"><header className="card-head"><h3>Revenue by category</h3></header><BarList rows={data.revenue_by_category} /></section>
        <section className="card"><header className="card-head"><h3>Expenses by category</h3></header><BarList rows={data.expense_by_category} color="#c2410c" /></section>
      </div>
      <Traceability overview={data} />
    </>
  );
}

// --------------------------------------------------------------------------- review queue

function SourcePanel({ doc, highlight }: { doc: CaseDetail["documents"][number]; highlight: string[] }) {
  const [showPage, setShowPage] = useState(true);
  const source = doc.source;
  return (
    <div className="source-panel">
      <header>
        <div>
          <span className="doc-type">{humanize(doc.facts.document_type)}</span>
          <strong>{doc.facts.source_name}{source?.source_row ? ` · row ${source.source_row}` : ""}</strong>
        </div>
        {source?.extraction_confidence !== null && source?.extraction_confidence !== undefined && (
          <span className={`conf ${source.low_confidence ? "low" : ""}`}>{percent(source.extraction_confidence, 1)} conf.</span>
        )}
      </header>
      <dl className="facts">
        <div><dt>Amount</dt><dd>{money(doc.facts.amount)}</dd></div>
        <div><dt>Date</dt><dd>{doc.facts.date ?? "—"}</dd></div>
        <div><dt>Identifiers</dt><dd className="mono">{doc.facts.identifiers.join(", ") || "—"}</dd></div>
      </dl>
      {source && source.page_count > 0 && (
        <>
          <button className="link-button" onClick={() => setShowPage((v) => !v)}>{showPage ? "Hide" : "Show"} original page</button>
          {showPage && <img className="page-image" src={api.pageUrl(source.document_id, 1)} alt={`Page 1 of ${source.source_name}`} loading="lazy" />}
        </>
      )}
      {source && (
        <table className="field-table">
          <thead><tr><th>Label (as printed)</th><th>Value</th></tr></thead>
          <tbody>
            {source.fields.map((field) => (
              <tr key={field.field_id} className={highlight.includes(field.field_id) ? "used" : ""}>
                <td>{field.label}</td><td>{field.value === null ? <em>empty</em> : String(field.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ReviewForm({ detail, reviewer, onDone }: { detail: CaseDetail; reviewer: string; onDone: (d: CaseDetail) => void }) {
  const [action, setAction] = useState<"ACCEPT" | "REJECT" | "CORRECT">("ACCEPT");
  const [reason, setReason] = useState("");
  const [field, setField] = useState("amount");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setAction("ACCEPT"); setReason(""); setValue(""); setError(""); }, [detail.case_id]);

  const submit = async () => {
    if (!reviewer.trim()) { setError("Enter your reviewer name in the sidebar first."); return; }
    setBusy(true);
    setError("");
    try {
      onDone(await api.review(detail.case_id, {
        action, reviewer, reason: reason || undefined,
        field: action === "CORRECT" ? field : undefined,
        corrected_value: action === "CORRECT" ? value : undefined,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="review-form">
      <div className="segmented">
        {(["ACCEPT", "REJECT", "CORRECT"] as const).map((a) => (
          <button key={a} className={action === a ? "active" : ""} onClick={() => setAction(a)}>{humanize(a)}</button>
        ))}
      </div>
      <p className="hint">
        {action === "ACCEPT" && "Accept the records as they are. The transaction enters analytics."}
        {action === "REJECT" && "Reject the records. The transaction is quarantined and excluded from analytics."}
        {action === "CORRECT" && "Record the correct value. Originals stay untouched; analytics uses your correction."}
      </p>
      {action === "CORRECT" && (
        <div className="form-row">
          <label>Field<select value={field} onChange={(e) => setField(e.target.value)}>
            <option value="amount">Amount</option><option value="date">Date (YYYY-MM-DD)</option>
            <option value="category">Category</option><option value="counterparty">Counterparty</option>
          </select></label>
          <label>Correct value<input value={value} onChange={(e) => setValue(e.target.value)} placeholder={field === "date" ? "2012-12-08" : field === "amount" ? "2724.57" : ""} /></label>
        </div>
      )}
      <label><span>Reason <small className="muted">{action === "ACCEPT" ? "(optional)" : "(required)"}</small></span>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="What did you check?" />
      </label>
      {error && <p className="form-error">{error}</p>}
      <button className="next-button" disabled={busy} onClick={submit}>{busy ? "Saving…" : `Save · ${humanize(action)}`}</button>
    </section>
  );
}

function ReviewView({ reviewer, onChanged }: { reviewer: string; onChanged: () => void }) {
  const [filter, setFilter] = useState("open");
  const { data: cases, error, reload } = useLoad(() => api.cases(filter === "all" ? undefined : filter), [filter]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    if (cases && cases.length && (!selected || !cases.some((c) => c.case_id === selected))) setSelected(cases[0].case_id);
    if (cases && !cases.length) setSelected(null);
  }, [cases, selected]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    setDetail(null);
    api.caseDetail(selected).then(setDetail).catch((e: Error) => setDetailError(e.message));
  }, [selected]);

  const highlight = useMemo(() => detail?.documents.flatMap((d) => [d.facts.amount_field?.field_id, d.facts.date_field?.field_id].filter(Boolean) as string[]) ?? [], [detail]);

  return (
    <div className="review-layout">
      <aside className="case-list">
        <div className="segmented small">
          {[["open", "Open"], ["reviewed", "Reviewed"], ["all", "All"]].map(([key, label]) => (
            <button key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>
          ))}
        </div>
        {!cases && <Loading error={error} />}
        {cases && !cases.length && <p className="muted empty">{filter === "open" ? "Nothing to review — every record is reconciled." : "No cases."}</p>}
        {cases?.map((c: CaseRow) => (
          <button key={c.case_id} className={`case-item ${selected === c.case_id ? "selected" : ""}`} onClick={() => setSelected(c.case_id)}>
            <div className="case-top"><StatusPill status={c.status} /><span className="mono-muted">{humanize(c.case_type)}</span></div>
            <strong>{c.documents.map((d) => d.source_name).join(" ↔ ")}</strong>
            <span className="case-explain">{c.explanation}</span>
          </button>
        ))}
      </aside>
      <section className="case-detail">
        {!detail && selected && <Loading error={detailError} />}
        {!selected && <p className="muted empty">Select a case.</p>}
        {detail && (
          <>
            <header className="case-header">
              <div>
                <div className="case-top"><StatusPill status={detail.status} />{detail.status !== detail.computed_status && <span className="mono-muted">engine: {humanize(detail.computed_status)}</span>}</div>
                <h2>{humanize(detail.case_type)}{detail.relationship ? ` · ${humanize(detail.relationship)}` : ""}</h2>
                <p>{detail.explanation}</p>
              </div>
              <div className="tags">{detail.discrepancy_types.map((t) => <span className="tag" key={t}>{humanize(t)}</span>)}</div>
            </header>
            {detail.results.length > 0 && (
              <table className="compare-table">
                <thead><tr><th>Field</th><th>{detail.documents[0]?.facts.source_name}</th><th>{detail.documents[1]?.facts.source_name}</th><th>Difference</th><th>Result</th></tr></thead>
                <tbody>
                  {detail.results.map((r) => (
                    <tr key={r.field}>
                      <td>{humanize(r.field)}</td>
                      <td className="mono">{r.field === "amount" ? money(r.left_value as number) : String(r.left_value ?? "—")}</td>
                      <td className="mono">{r.field === "amount" ? money(r.right_value as number) : String(r.right_value ?? "—")}</td>
                      <td className="mono">{r.difference_percent !== null ? `${r.difference_percent}%` : r.difference !== null ? `${r.difference} days` : r.note ?? "—"}</td>
                      <td><StatusPill status={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className={`source-grid ${detail.documents.length === 1 ? "single" : ""}`}>
              {detail.documents.map((doc) => <SourcePanel key={doc.facts.document_id} doc={doc} highlight={highlight} />)}
            </div>
            <ReviewForm detail={detail} reviewer={reviewer} onDone={(updated) => { setDetail(updated); reload(); onChanged(); }} />
            {detail.history.length > 0 && (
              <section className="history">
                <h4>Decision history</h4>
                {detail.history.map((h) => (
                  <div key={h.id} className="history-row">
                    <StatusPill status={{ ACCEPT: "ACCEPTED", REJECT: "REJECTED", CORRECT: "CORRECTED" }[h.action]} />
                    <span><b>{h.reviewer}</b> · {h.created_at} UTC{h.field && <> · {h.field} → <code>{h.corrected_value}</code></>}{h.reason && <> — {h.reason}</>}</span>
                  </div>
                ))}
              </section>
            )}
          </>
        )}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------- documents

function DocumentsView() {
  const { data, error } = useLoad(api.documents, []);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<DocumentDetail | null>(null);
  const rows = useMemo(() => (data ?? []).filter((row) =>
    (!status || row.verification_status === status) &&
    (!query || `${row.source_name} ${row.category ?? ""} ${row.document_id}`.toLowerCase().includes(query.toLowerCase()))
  ), [data, query, status]);
  if (!data) return <Loading error={error} />;
  const statuses = Array.from(new Set(data.map((d) => d.verification_status).filter(Boolean))) as string[];
  return (
    <>
      <div className="toolbar">
        <input className="search" placeholder="Search file, category or id" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </select>
        <span className="mono-muted">{rows.length} of {data.length}</span>
      </div>
      <div className="table-wrap card flush">
        <table className="data-table">
          <thead><tr><th>Source</th><th>Type</th><th>Category</th><th>Date</th><th className="num">Amount</th><th>Extraction</th><th>Status</th></tr></thead>
          <tbody>
            {rows.slice(0, 400).map((row: DocumentRow) => (
              <tr key={row.document_id} onClick={() => api.document(row.document_id).then(setOpen)} className="clickable">
                <td><strong>{row.source_name}</strong>{row.source_row ? <span className="mono-muted"> · row {row.source_row}</span> : null}</td>
                <td>{row.document_types?.map(humanize).join(" + ") ?? "—"}</td>
                <td>{row.category ?? "—"}</td>
                <td className="mono">{row.date ?? "—"}</td>
                <td className="num mono">{money(row.amount)}</td>
                <td><span className={`conf ${row.low_confidence ? "low" : ""}`}>{row.extraction_method} · {percent(row.extraction_confidence, 0)}</span></td>
                <td><StatusPill status={row.verification_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && (
        <div className="drawer-backdrop" onClick={() => setOpen(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <header><h3>{open.source_name}{open.source_row ? ` · row ${open.source_row}` : ""}</h3><button className="link-button" onClick={() => setOpen(null)}>Close</button></header>
            <p className="mono-muted">{open.extraction_method} · OCR {percent(open.ocr_confidence, 1)} · fields {percent(open.extraction_confidence, 1)}</p>
            {open.cases.map((c) => <div key={c.case_id} className="history-row"><StatusPill status={c.status} /><span>{c.explanation}</span></div>)}
            {open.page_count > 0 && <img className="page-image" src={api.pageUrl(open.document_id, 1)} alt="Original page" />}
            <table className="field-table">
              <thead><tr><th>Label (as printed)</th><th>Value</th><th>Conf.</th></tr></thead>
              <tbody>{open.fields.map((f) => <tr key={f.field_id}><td>{f.label}</td><td>{String(f.value ?? "—")}</td><td className="mono">{percent(f.confidence, 0)}</td></tr>)}</tbody>
            </table>
            {open.ocr_text && <details><summary>Raw OCR text</summary><pre>{open.ocr_text}</pre></details>}
          </aside>
        </div>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- analytics

function AnalyticsView({ version }: { version: string }) {
  const { data, error } = useLoad(api.overview, [version]);
  if (!data) return <Loading error={error} />;
  const m = data.monthly;
  return (
    <>
      <section className="card">
        <header className="card-head"><h3>Monthly profit & loss</h3><span className="mono-muted">verified records only</span></header>
        <LineChart labels={m.months} series={[
          { name: "Revenue", values: m.revenue, color: "#4f46e5" },
          { name: "Expenses", values: m.expense, color: "#c2410c" },
          { name: "Profit", values: m.profit, color: "#15803d" },
        ]} />
      </section>
      <div className="grid-2">
        <section className="card">
          <header className="card-head"><h3>Budget consumption {data.budget.year}</h3><span className="mono-muted">Jan–{data.budget.through_month ? monthLabel(`${data.budget.year}-${String(data.budget.through_month).padStart(2, "0")}`).split(" ")[0] : ""} vs budget</span></header>
          <div className="budget-list">
            {data.budget.categories.map((row) => (
              <div key={row.category} className="budget-row">
                <div className="bar-copy"><span>{row.category}</span><strong>{percent(row.consumption, 0)}</strong></div>
                <Meter value={row.consumption} />
                <small className="mono-muted">{money(row.spent, true)} of {money(row.budget, true)} · {row.budget_source}</small>
              </div>
            ))}
          </div>
        </section>
        <section className="card">
          <header className="card-head"><h3>Largest suppliers</h3></header>
          <BarList rows={data.top_counterparties} color="#c2410c" />
          <header className="card-head spaced"><h3>Revenue mix</h3></header>
          <BarList rows={data.revenue_by_category} />
        </section>
      </div>
      <Traceability overview={data} />
    </>
  );
}

// --------------------------------------------------------------------------- forecast

function ForecastView({ version }: { version: string }) {
  const [metric, setMetric] = useState("revenue");
  const [horizon, setHorizon] = useState(6);
  const { data, error, loading } = useLoad<Forecast>(() => api.forecast(metric, horizon), [metric, horizon, version]);
  return (
    <>
      <div className="toolbar">
        <div className="segmented">
          {["revenue", "expense", "profit"].map((m) => <button key={m} className={metric === m ? "active" : ""} onClick={() => setMetric(m)}>{humanize(m)}</button>)}
        </div>
        <label className="inline">Horizon
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>{[3, 6, 9, 12].map((h) => <option key={h} value={h}>{h} months</option>)}</select>
        </label>
        {loading && <span className="mono-muted">fitting models…</span>}
      </div>
      {!data && <Loading error={error} />}
      {data?.error && <div className="notice">{data.error}</div>}
      {data && !data.error && (() => {
        const labels = [...data.history.months, ...data.forecast_months];
        const h = data.history.values.length;
        const pad = (values: number[]) => [...Array(h - 1).fill(null), data.history.values[h - 1], ...values];
        const e = data.models.ensemble;
        return (
          <>
            <section className="card">
              <header className="card-head"><h3>{humanize(metric)} forecast · next {horizon} months</h3><span className="mono-muted">{Math.round(data.confidence_level * 100)}% interval</span></header>
              <LineChart labels={labels} divider={h - 1}
                series={[
                  { name: "Verified actuals", values: [...data.history.values, ...Array(horizon).fill(null)], color: "#141b2b" },
                  { name: "Ensemble forecast", values: pad(e.point), color: "#4f46e5", dashed: true },
                ]}
                band={{ lower: pad(e.lower), upper: pad(e.upper), color: "#4f46e5", label: `${Math.round(data.confidence_level * 100)}% interval` }}
              />
            </section>
            <div className="grid-2">
              <section className="card">
                <header className="card-head"><h3>Model accuracy</h3>
                  {data.backtest && <span className={`pill ${data.meets_target ? "ok" : "warn"}`}>{data.meets_target ? "Meets" : "Misses"} ≤{data.backtest.target_mape}% MAPE target</span>}
                </header>
                {data.backtest ? (
                  <>
                    <table className="data-table compact">
                      <thead><tr><th>Model</th><th className="num">Backtest MAPE</th><th>Notes</th></tr></thead>
                      <tbody>
                        <tr><td>Linear regression</td><td className="num mono">{data.backtest.mape.linear_regression}%</td><td className="mono-muted">trend {money(Number(data.models.linear_regression.params?.slope_per_month), true)}/mo</td></tr>
                        <tr><td>ARIMA</td><td className="num mono">{data.backtest.mape.arima}%</td><td className="mono-muted">{data.models.arima.params ? `order ${(data.models.arima.params.order as number[]).join(",")}${(data.models.arima.params.seasonal_order as number[])[3] ? " · seasonal 12" : ""}` : data.models.arima.model}</td></tr>
                        <tr className="strong"><td>Ensemble (used)</td><td className="num mono">{data.backtest.mape.ensemble}%</td><td className="mono-muted">mean of both</td></tr>
                      </tbody>
                    </table>
                    <p className="muted small">Tested by hiding the last {data.backtest.holdout_months} verified months and forecasting them. The {Math.round(data.confidence_level * 100)}% interval contained {percent(data.backtest.interval_coverage)} of those months.</p>
                  </>
                ) : <p className="muted">Not enough history for a backtest yet (needs 14+ months).</p>}
              </section>
              <section className="card">
                <header className="card-head"><h3>Projected months</h3></header>
                <table className="data-table compact">
                  <thead><tr><th>Month</th><th className="num">Forecast</th><th className="num">Low</th><th className="num">High</th></tr></thead>
                  <tbody>{data.forecast_months.map((month, i) => (
                    <tr key={month}><td>{monthLabel(month)}</td><td className="num mono">{money(e.point[i], true)}</td><td className="num mono">{money(e.lower[i], true)}</td><td className="num mono">{money(e.upper[i], true)}</td></tr>
                  ))}</tbody>
                </table>
              </section>
            </div>
          </>
        );
      })()}
    </>
  );
}

// --------------------------------------------------------------------------- what-if

const DEFAULT_SCENARIO: ScenarioInput = {
  horizon: 6, volume_change_pct: 0, pricing_adjustment_pct: 0, price_elasticity: 0.5,
  headcount_change: 0, baseline_headcount: 15, vendor_consolidation_pct: 0, other_cost_change_pct: 0,
};

function Slider({ label, value, min, max, step = 1, unit = "%", onChange }: { label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span><b>{label}</b><output>{value > 0 && unit === "%" ? "+" : ""}{value}{unit}</output></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function WhatIfView({ version }: { version: string }) {
  const [input, setInput] = useState<ScenarioInput>(DEFAULT_SCENARIO);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.whatif(input).then((r) => { setResult(r); setError(""); }).catch((e: Error) => setError(e.message));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [input, version]);
  const set = (key: keyof ScenarioInput) => (value: number) => setInput((current) => ({ ...current, [key]: value }));
  return (
    <div className="whatif-layout">
      <section className="card levers">
        <header className="card-head"><h3>Scenario levers</h3><button className="link-button" onClick={() => setInput(DEFAULT_SCENARIO)}>Reset</button></header>
        <Slider label="Sales volume" value={input.volume_change_pct} min={-30} max={30} onChange={set("volume_change_pct")} />
        <Slider label="Pricing adjustment" value={input.pricing_adjustment_pct} min={-20} max={20} onChange={set("pricing_adjustment_pct")} />
        <Slider label="Price elasticity" value={input.price_elasticity} min={0} max={2} step={0.1} unit="" onChange={set("price_elasticity")} />
        <Slider label="Headcount change" value={input.headcount_change} min={-10} max={10} unit=" people" onChange={set("headcount_change")} />
        <Slider label="Vendor consolidation savings" value={input.vendor_consolidation_pct} min={0} max={30} onChange={set("vendor_consolidation_pct")} />
        <Slider label="Other cost change" value={input.other_cost_change_pct} min={-20} max={20} onChange={set("other_cost_change_pct")} />
        <div className="form-row">
          <label>Current headcount<input type="number" min={1} value={input.baseline_headcount} onChange={(e) => set("baseline_headcount")(Math.max(1, Number(e.target.value)))} /></label>
          <label>Horizon<select value={input.horizon} onChange={(e) => set("horizon")(Number(e.target.value))}>{[3, 6, 12].map((h) => <option key={h} value={h}>{h} months</option>)}</select></label>
        </div>
        <p className="muted small">Scenarios never change stored records — they reshape the verified baseline forecast.</p>
      </section>
      <section className="whatif-results">
        {error && <div className="notice error">{error}</div>}
        {result?.error && <div className="notice">{result.error}</div>}
        {result && !result.error && (
          <>
            <div className="kpi-grid three">
              {(["revenue", "expense", "profit"] as const).map((metric) => {
                const delta = result.totals.delta[metric];
                const good = metric === "expense" ? delta <= 0 : delta >= 0;
                return (
                  <div className="kpi" key={metric}>
                    <span>{humanize(metric)} · {input.horizon} mo</span>
                    <strong>{money(result.totals.scenario[metric], true)}</strong>
                    <small className={delta === 0 ? "" : good ? "pos" : "neg"}>{delta >= 0 ? "+" : ""}{money(delta, true)} vs baseline</small>
                  </div>
                );
              })}
            </div>
            <section className="card">
              <header className="card-head"><h3>Profit: baseline vs scenario</h3></header>
              <LineChart labels={result.months.map((r) => r.month)} height={220} series={[
                { name: "Baseline", values: result.months.map((r) => r.baseline.profit), color: "#777587", dashed: true },
                { name: "Scenario", values: result.months.map((r) => r.scenario.profit), color: "#4f46e5" },
              ]} />
            </section>
            <section className="card">
              <header className="card-head"><h3>Assumptions</h3></header>
              <ul className="assumptions">
                <li>Payroll is {percent(Number(result.assumptions.payroll_share_of_expense), 0)} of expenses; one person costs about {money(Number(result.assumptions.monthly_cost_per_head), true)}/month (payroll ÷ headcount).</li>
                <li>Revenue multiplier {result.assumptions.revenue_factor}: volume × price × (1 − elasticity × price change).</li>
                <li>Non-payroll costs multiplied by {result.assumptions.non_payroll_cost_factor}.</li>
                <li>Baseline: {result.assumptions.baseline_model}.</li>
              </ul>
            </section>
          </>
        )}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------- audit

function AuditView({ version }: { version: string }) {
  const { data, error } = useLoad<ReviewAction[]>(api.audit, [version]);
  if (!data) return <Loading error={error} />;
  if (!data.length) return <p className="muted empty">No reviewer decisions yet. Every ACCEPT, REJECT and CORRECT will be recorded here.</p>;
  return (
    <div className="card flush table-wrap">
      <table className="data-table">
        <thead><tr><th>When (UTC)</th><th>Reviewer</th><th>Decision</th><th>Case</th><th>Correction</th><th>Reason</th></tr></thead>
        <tbody>{data.map((a) => (
          <tr key={a.id}>
            <td className="mono">{a.created_at}</td><td>{a.reviewer}</td>
            <td><StatusPill status={{ ACCEPT: "ACCEPTED", REJECT: "REJECTED", CORRECT: "CORRECTED" }[a.action]} /></td>
            <td className="mono small">{a.case_id}</td>
            <td className="mono">{a.field ? `${a.field} → ${a.corrected_value}` : "—"}</td>
            <td>{a.reason ?? "—"}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------- shell

const TITLES: Record<View, [string, string]> = {
  overview: ["Overview", "Your verified business at a glance."],
  review: ["Review queue", "Discrepancies the engine could not settle on its own. Your decision is final and audited."],
  documents: ["Documents", "Every extracted record, traceable to its source file."],
  audit: ["Audit log", "Append-only record of every reviewer decision."],
  analytics: ["Analytics", "Trends and budgets built only from reconciled records."],
  forecast: ["Forecast", "Linear regression and ARIMA, combined, with an honest accuracy check."],
  whatif: ["What-if", "Test decisions against the verified baseline before you make them."],
};

function readReviewer() {
  try { return window.localStorage.getItem("evostrategy.reviewer") ?? ""; } catch { return ""; }
}

export function Workspace({ onAddDocuments, onLoadDemo }: { onAddDocuments: () => void; onLoadDemo: () => void }) {
  const [view, setView] = useState<View>("overview");
  const [reviewer, setReviewer] = useState(readReviewer);
  const { data: summary, error, reload } = useLoad(api.summary, []);
  useEffect(() => { try { window.localStorage.setItem("evostrategy.reviewer", reviewer); } catch { /* storage unavailable */ } }, [reviewer]);
  const version = `${summary?.last_run_at}-${summary?.reviewed_cases}`;
  const [title, subtitle] = TITLES[view];
  let lastGroup = "";

  return (
    <div className="workspace">
      <nav className="sidebar">
        <div className="brand"><div className="brand-mark small">◆</div><span className="brand-name">EvoStrategy</span></div>
        <div className="nav-groups">
          {NAV.map((item) => {
            const header = item.group !== lastGroup ? <div className="nav-group" key={`${item.group}-h`}>{item.group}</div> : null;
            lastGroup = item.group;
            return (
              <div key={item.key}>
                {header}
                <button className={`nav-item ${view === item.key ? "active" : ""}`} onClick={() => setView(item.key)}>
                  {item.label}
                  {item.key === "review" && summary && summary.open_cases > 0 && <span className="nav-count">{summary.open_cases}</span>}
                </button>
              </div>
            );
          })}
        </div>
        <div className="sidebar-foot">
          <label>Reviewer<input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" /></label>
          <button className="add-documents" onClick={onAddDocuments}>+ Add documents</button>
          <span className="kernel-status">● Local · no cloud storage</span>
        </div>
      </nav>
      <main className="workspace-main">
        <header className="workspace-head">
          <div><h1>{title}</h1><p>{subtitle}</p></div>
          {summary && <div className="head-meta mono-muted">{summary.documents} documents · {summary.transactions} transactions</div>}
        </header>
        {!summary && <Loading error={error} />}
        {summary && !summary.has_data && (
          <section className="card empty-state">
            <h2>No documents yet</h2>
            <p>Upload invoices, payments and ledgers — or explore with a sample company's data.</p>
            <div className="ready-actions">
              <button className="report-button" onClick={onLoadDemo}>Load sample data</button>
              <button className="workspace-button" onClick={onAddDocuments}>Upload documents</button>
            </div>
          </section>
        )}
        {summary?.has_data && view === "overview" && <OverviewView summary={summary} go={setView} />}
        {summary?.has_data && view === "review" && <ReviewView reviewer={reviewer} onChanged={reload} />}
        {summary?.has_data && view === "documents" && <DocumentsView />}
        {summary?.has_data && view === "analytics" && <AnalyticsView version={version} />}
        {summary?.has_data && view === "forecast" && <ForecastView version={version} />}
        {summary?.has_data && view === "whatif" && <WhatIfView version={version} />}
        {summary?.has_data && view === "audit" && <AuditView version={version} />}
      </main>
    </div>
  );
}
