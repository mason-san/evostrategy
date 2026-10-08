import { useEffect, useRef, useState } from "react";
import { Loading, useLoad } from "./hooks";
import { api, money, percent, type AssistantAnswer, type ChatTurn, type Summary } from "./api";
import { LineChart } from "./charts";

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string; result?: AssistantAnswer; error?: string };

const SUGGESTIONS = [
  "What was our revenue last quarter?",
  "Which customers are growing fastest?",
  "How long is our cash runway?",
  "What happens if we increase prices by 10%?",
];

const TOOL_LABELS: Record<string, string> = {
  get_data_overview: "Data overview", get_time_series: "Revenue & expense trend", get_breakdown: "Category breakdown",
  compare_growth: "Quarter-over-quarter growth", find_transactions: "Transaction search", get_forecast: "Forecast",
  get_cash_runway: "Cash runway", run_what_if: "What-if simulation", get_budget_status: "Budget status", get_review_queue: "Review queue",
};

function greeting(name: string) {
  const hour = new Date().getHours();
  const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  return `Good ${part}${name.trim() ? `, ${name.trim().split(" ")[0]}` : ""}.`;
}

/** Minimal inline renderer: paragraphs, "- " bullets and **bold** only. */
function RichText({ text }: { text: string }) {
  const inline = (line: string) => line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part);
  const blocks: Array<{ bullets: boolean; lines: string[] }> = [];
  for (const raw of text.split("\n")) {
    if (!raw.trim()) continue;
    const bullet = /^\s*[-•*]\s+/.test(raw);
    const last = blocks[blocks.length - 1];
    if (last && last.bullets === bullet && bullet) last.lines.push(raw.replace(/^\s*[-•*]\s+/, ""));
    else blocks.push({ bullets: bullet, lines: [bullet ? raw.replace(/^\s*[-•*]\s+/, "") : raw] });
  }
  return (
    <>
      {blocks.map((block, i) => block.bullets
        ? <ul key={i}>{block.lines.map((line, j) => <li key={j}>{inline(line)}</li>)}</ul>
        : <p key={i}>{inline(block.lines[0])}</p>)}
    </>
  );
}

function Trajectory({ visual }: { visual: NonNullable<AssistantAnswer["visual"]> }) {
  const labels = visual.labels.length > 12 ? visual.labels.slice(-12) : visual.labels;
  const values = visual.values.slice(-labels.length);
  const last = values.length - 1;
  const delta = last > 0 ? values[last] - values[last - 1] : null;
  return (
    <div className="answer-visual">
      <div className="answer-visual-head">
        <span className="mono-muted">{visual.title.toUpperCase()}</span>
        {delta !== null && <span className={`delta ${delta >= 0 ? "up" : "down"}`}>{delta >= 0 ? "▲" : "▼"} {money(Math.abs(delta), true)} vs previous</span>}
      </div>
      <LineChart labels={labels} height={180} series={[{ name: visual.title, values, color: "#4f46e5" }]} />
    </div>
  );
}

function AssistantMessage({ message, go }: { message: Extract<Message, { role: "assistant" }>; go: (view: "documents") => void }) {
  const [copied, setCopied] = useState(false);
  const r = message.result;
  const copy = () => {
    void navigator.clipboard?.writeText(message.text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <article className="answer-card">
      <header>
        <span className="assistant-mark">E</span>
        <strong>EvoAssistant</strong>
        <span className="mono-muted">· {r ? r.model : "Strategic intelligence query"}</span>
        {!message.error && <button className="ghost-button" onClick={copy}>{copied ? "Copied" : "Copy"}</button>}
      </header>
      {message.error ? <p className="answer-error">{message.error}</p> : <div className="answer-body"><RichText text={message.text} /></div>}
      {r?.visual && <Trajectory visual={r.visual} />}
      {r && (
        <footer>
          <span className="verified-line">
            <i />✓ Verified with {r.evidence.verified_records.toLocaleString()} transaction records · {percent(r.evidence.verified_rate)} reconciled
            {r.evidence.data_source?.is_demo && <em>demo data</em>}
          </span>
          <button className="link-button" onClick={() => go("documents")}>View supporting records →</button>
          {r.tools_used.length > 0 && (
            <span className="tools-line" title="Read-only queries the model ran on your verified data">
              Looked at: {[...new Set(r.tools_used.map((t) => TOOL_LABELS[t.name] ?? t.name))].join(" · ")}
            </span>
          )}
        </footer>
      )}
    </article>
  );
}

export function Home({ summary, reviewer, go }: { summary: Summary; reviewer: string; go: (view: "review" | "documents" | "forecast" | "whatif") => void }) {
  const { data: status } = useLoad(api.assistantStatus, []);
  const { data: overview, error } = useLoad(api.overview, [summary.last_run_at, summary.reviewed_cases]);
  const [model, setModel] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const chatting = messages.length > 0;
  const threadEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, [chatting]);
  useEffect(() => { if (status && !model) setModel(status.default_model); }, [status, model]);
  useEffect(() => { threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages, busy]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const history: ChatTurn[] = messages.filter((m) => !(m.role === "assistant" && m.error)).map((m) => ({ role: m.role, content: m.text }));
    setMessages((current) => [...current, { id: nextId.current++, role: "user", text: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const result = await api.ask(q, history, model || undefined);
      setMessages((current) => [...current, { id: nextId.current++, role: "assistant", text: result.answer, result }]);
    } catch (e) {
      setMessages((current) => [...current, { id: nextId.current++, role: "assistant", text: "", error: e instanceof Error ? e.message : "The assistant could not answer." }]);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };

  const askForm = (
    <form className="ask-box" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
        <input
          ref={input} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={2000}
          placeholder="Ask anything about your verified data…" aria-label="Ask EvoAssistant" disabled={status?.configured === false}
        />
        <div className="ask-row">
          <span className="source-chip">▤ Verified records only</span>
          <kbd>⌘K</kbd>
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model" disabled={!status}>
            {status?.models.map((m) => <option key={m.id} value={m.id}>{m.label} — {m.note}</option>)}
          </select>
          <button type="submit" className="send-button" disabled={busy || !question.trim() || status?.configured === false} aria-label="Ask">↑</button>
        </div>
      </form>
  );

  const quarters = overview?.quarterly;
  const done = quarters ? quarters.quarters.map((_, i) => i).filter((i) => quarters.complete[i]) : [];
  const latest = done[done.length - 1];
  const previous = done[done.length - 2];
  const growth = quarters && latest !== undefined && previous !== undefined && quarters.revenue[previous]
    ? (quarters.revenue[latest] - quarters.revenue[previous]) / quarters.revenue[previous] : null;
  const unverified = summary.transactions - summary.verified_transactions;

  const steps = [
    summary.open_cases > 0 && { label: `Review ${summary.open_cases} open ${summary.open_cases === 1 ? "case" : "cases"}`, hint: "They are excluded from every number until settled", view: "review" as const, tone: "warn" },
    { label: "Explore the revenue forecast", hint: "Linear regression + ARIMA with an accuracy check", view: "forecast" as const, tone: "info" },
    { label: "Test a pricing or hiring decision", hint: "Simulate it on the verified baseline", view: "whatif" as const, tone: "info" },
  ].filter(Boolean) as Array<{ label: string; hint: string; view: "review" | "forecast" | "whatif"; tone: string }>;

  if (chatting) {
    return (
      <div className="chat-view">
        <header className="chat-head">
          <div><strong>EvoAssistant</strong><span className="mono-muted">Answers come only from verified records</span></div>
          <button className="new-chat" onClick={() => { setMessages([]); setQuestion(""); }}>+ New chat</button>
        </header>
        <div className="chat-scroll" aria-live="polite">
          <div className="thread">
            {messages.map((m) => m.role === "user"
              ? <div className="user-bubble" key={m.id}><span>{m.text}</span><i>{(reviewer.trim()[0] ?? "Y").toUpperCase()}</i></div>
              : <AssistantMessage key={m.id} message={m} go={go} />)}
            {busy && <div className="thinking"><span /><span /><span />Reading your verified data…</div>}
            <div ref={threadEnd} />
          </div>
        </div>
        <div className="chat-input">{askForm}</div>
      </div>
    );
  }

  return (
    <div className="home">
      <h2 className="home-title">{greeting(reviewer)}</h2>
      <p className="home-sub">What would you like to understand about your business today?</p>

      {!chatting && askForm}

      {status && !status.configured && (
        <div className="notice setup-notice">The assistant needs an Anthropic API key. {status.setup_hint}</div>
      )}

      {(
        <div className="suggestions">
          <span className="mono-muted">Suggestions:</span>
          {SUGGESTIONS.map((s) => <button key={s} disabled={status?.configured === false} onClick={() => void ask(s)}>{s}</button>)}
        </div>
      )}

      <section className="glance">
        <header><h3>At a glance</h3><span className="mono-muted">verified data only</span></header>
        {!overview ? <Loading error={error} /> : (
          <div className="glance-grid">
            <div className="glance-card">
              <span>Revenue{latest !== undefined ? ` · ${quarters!.quarters[latest]}` : ""}</span>
              <strong>{money(latest !== undefined ? quarters!.revenue[latest] : overview.totals.revenue, true)}</strong>
              <small className={growth !== null && growth < 0 ? "bad" : "good"}>
                {growth !== null ? `${growth >= 0 ? "+" : ""}${(growth * 100).toFixed(1)}% vs ${quarters!.quarters[previous]}` : `${money(overview.totals.revenue, true)} total verified`}
              </small>
            </div>
            <button className="glance-card clickable" onClick={() => go("review")}>
              <span>Needs your review</span>
              <strong>{summary.open_cases}</strong>
              <small className={summary.open_cases ? "bad" : "good"}>{unverified} {unverified === 1 ? "record" : "records"} held back from analytics</small>
            </button>
            <div className="glance-card">
              <span>Verified transactions</span>
              <strong>{summary.verified_transactions.toLocaleString()}</strong>
              <small className="good">{percent(summary.verified_rate, 1)} reconciled across sources</small>
            </div>
          </div>
        )}
      </section>

      <section className="next-steps">
        <h4>Recommended next steps</h4>
        <div className="steps-grid">
          {steps.map((s) => (
            <button key={s.label} className={`step-card ${s.tone}`} onClick={() => go(s.view)}>
              <strong>{s.label}</strong><small>{s.hint}</small><i>→</i>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
