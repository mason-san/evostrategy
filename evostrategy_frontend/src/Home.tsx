import { useEffect, useRef, useState } from "react";
import { Loading, useLoad } from "./hooks";
import { api, money, percent, type AssistantAnswer, type ChatSummary, type Summary } from "./api";
import { LineChart } from "./charts";

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string; result?: AssistantAnswer; error?: string };

const TABS_KEY = "evostrategy.chat.tabs";
const ACTIVE_KEY = "evostrategy.chat.active";
const readStored = <T,>(key: string, fallback: T): T => {
  try { const raw = window.localStorage.getItem(key); return raw ? (JSON.parse(raw) as T) : fallback; } catch { return fallback; }
};
const writeStored = (key: string, value: unknown) => { try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } };

function when(value: string) {
  const date = new Date(value);
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days < 1) return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return days < 7 ? `${days}d ago` : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function HistoryList({ chats, activeId, onOpen, onDelete, limit }: {
  chats: ChatSummary[]; activeId: string | null; onOpen: (id: string) => void; onDelete: (chat: ChatSummary) => void; limit?: number;
}) {
  const rows = chats.filter((c) => c.message_count > 0).slice(0, limit);
  if (!rows.length) return <p className="history-empty">No saved chats yet. Ask a question and it will be kept here.</p>;
  return (
    <ul className="history-list">
      {rows.map((c) => (
        <li key={c.id} className={c.id === activeId ? "current" : ""}>
          <button className="history-open" onClick={() => onOpen(c.id)}><strong>{c.title}</strong><span>{when(c.updated_at)} · {Math.ceil(c.message_count / 2)} {c.message_count <= 2 ? "question" : "questions"}</span></button>
          <button className="history-delete" aria-label={`Delete chat ${c.title}`} onClick={() => onDelete(c)}>🗑</button>
        </li>
      ))}
    </ul>
  );
}

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
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [tabs, setTabs] = useState<string[]>(() => readStored<string[]>(TABS_KEY, []));
  const [activeId, setActiveId] = useState<string | null>(() => readStored<string | null>(ACTIVE_KEY, null));
  const [threads, setThreads] = useState<Record<string, Message[]>>({});
  const [busy, setBusy] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [notice, setNotice] = useState("");
  const tempId = useRef(-1);
  const threadEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const messages = activeId ? threads[activeId] ?? [] : [];
  const chatting = activeId !== null;
  const isBusy = activeId !== null && busy.includes(activeId);
  const modelReady = !status || !!status.models.find((m) => m.id === model)?.available;
  const titleOf = (id: string) => chats.find((c) => c.id === id)?.title ?? "Chat";

  const refreshChats = () => api.chats().then(setChats).catch(() => undefined);
  const toMessages = (stored: Awaited<ReturnType<typeof api.chat>>["messages"]): Message[] =>
    stored.map((m) => m.role === "user"
      ? { id: m.id, role: "user", text: m.text }
      : { id: m.id, role: "assistant", text: m.text, result: m.result ?? undefined, error: m.error ?? undefined });

  // load the saved list once, and drop tabs whose chat no longer exists
  useEffect(() => {
    api.chats().then((list) => {
      setChats(list);
      const ids = new Set(list.map((c) => c.id));
      setTabs((current) => current.filter((id) => ids.has(id)));
      setActiveId((current) => (current && ids.has(current) ? current : null));
    }).catch(() => undefined);
  }, []);
  useEffect(() => { writeStored(TABS_KEY, tabs); }, [tabs]);
  useEffect(() => { writeStored(ACTIVE_KEY, activeId); }, [activeId]);
  // fetch a chat's saved messages the first time its tab is shown
  useEffect(() => {
    if (!activeId || threads[activeId]) return;
    api.chat(activeId).then((chat) => setThreads((current) => ({ ...current, [activeId]: current[activeId] ?? toMessages(chat.messages) })))
      .catch(() => { setNotice("That chat could not be loaded."); closeTab(activeId); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);
  useEffect(() => { input.current?.focus(); }, [activeId]);
  useEffect(() => { if (status && !model) setModel(status.default_model); }, [status, model]);
  useEffect(() => { threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages.length, isBusy, activeId]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openChat = (id: string) => {
    setTabs((current) => (current.includes(id) ? current : [...current, id]));
    setActiveId(id);
    setShowHistory(false);
  };
  const closeTab = (id: string) => {
    setTabs((current) => current.filter((t) => t !== id));
    setActiveId((current) => (current === id ? null : current));
  };
  const removeChat = (chat: ChatSummary) => {
    if (!window.confirm(`Delete the chat "${chat.title}"? This cannot be undone.`)) return;
    api.deleteChat(chat.id).then(() => {
      closeTab(chat.id);
      setThreads((current) => { const { [chat.id]: _gone, ...rest } = current; return rest; });
      void refreshChats();
    }).catch((e: Error) => setNotice(e.message));
  };

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || (activeId && busy.includes(activeId))) return;
    setNotice("");
    let id = activeId;
    try {
      if (!id) {
        id = (await api.createChat()).id;
        setThreads((current) => ({ ...current, [id!]: [] }));
        openChat(id);
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not start a chat.");
      return;
    }
    const chatId = id;
    const add = (message: Message) => setThreads((current) => ({ ...current, [chatId]: [...(current[chatId] ?? []), message] }));
    add({ id: tempId.current--, role: "user", text: q });
    setQuestion("");
    setBusy((current) => [...current, chatId]);
    try {
      const result = await api.ask(q, model || undefined, chatId);
      add({ id: tempId.current--, role: "assistant", text: result.answer, result });
    } catch (e) {
      add({ id: tempId.current--, role: "assistant", text: "", error: e instanceof Error ? e.message : "The assistant could not answer." });
    } finally {
      setBusy((current) => current.filter((b) => b !== chatId));
      void refreshChats();
      input.current?.focus();
    }
  };

  const askForm = (
    <form className="ask-box" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
      <input
        ref={input} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={2000}
        placeholder="Ask anything about your verified data…" aria-label="Ask EvoAssistant" disabled={!modelReady}
      />
      <div className="ask-row">
        <span className="source-chip">▤ Verified records only</span>
        <kbd>⌘K</kbd>
        <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model" disabled={!status}>
          {status?.models.map((m) => <option key={m.id} value={m.id} disabled={!m.available}>{m.label} — {m.available ? m.note : "needs API key"}</option>)}
        </select>
        <button type="submit" className="send-button" disabled={isBusy || !question.trim() || !modelReady} aria-label="Ask">↑</button>
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

  const tabBar = (tabs.length > 0 || chatting) && (
    <div className="chat-tabs" role="tablist">
      <button role="tab" aria-selected={!chatting} className={`chat-tab home-tab${!chatting ? " active" : ""}`} onClick={() => setActiveId(null)}>⌂ Home</button>
      {tabs.map((id) => (
        <span key={id} role="tab" aria-selected={id === activeId} className={`chat-tab${id === activeId ? " active" : ""}`}>
          <button className="tab-title" onClick={() => setActiveId(id)} title={titleOf(id)}>{busy.includes(id) && <i className="tab-busy" />}{titleOf(id)}</button>
          <button className="tab-close" aria-label={`Close tab ${titleOf(id)}`} onClick={() => closeTab(id)}>×</button>
        </span>
      ))}
      <button className="chat-tab new-tab" aria-label="New chat" onClick={() => setActiveId(null)}>+</button>
      <span className="tabs-spacer" />
      <div className="history-menu">
        <button className="new-chat" aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}>History</button>
        {showHistory && (
          <div className="history-pop">
            <HistoryList chats={chats} activeId={activeId} onOpen={openChat} onDelete={removeChat} />
          </div>
        )}
      </div>
    </div>
  );

  if (chatting) {
    return (
      <div className="chat-view">
        {tabBar}
        <div className="chat-scroll" aria-live="polite">
          <div className="thread">
            {notice && <div className="notice error">{notice}</div>}
            {!threads[activeId!] && <div className="loading">Loading chat…</div>}
            {messages.map((m) => m.role === "user"
              ? <div className="user-bubble" key={m.id}><span>{m.text}</span><i>{(reviewer.trim()[0] ?? "Y").toUpperCase()}</i></div>
              : <AssistantMessage key={m.id} message={m} go={go} />)}
            {isBusy && <div className="thinking"><span /><span /><span />Reading your verified data…</div>}
            <div ref={threadEnd} />
          </div>
        </div>
        <div className="chat-input">{askForm}</div>
      </div>
    );
  }

  return (
    <div className="home">
      {tabBar}
      <h2 className="home-title">{greeting(reviewer)}</h2>
      <p className="home-sub">What would you like to understand about your business today?</p>

      {askForm}
      {notice && <div className="notice error setup-notice">{notice}</div>}

      {status && !modelReady && model && (
        <div className="notice setup-notice">This model is not available. {status.setup_hint}</div>
      )}

      <div className="suggestions">
        <span className="mono-muted">Suggestions:</span>
        {SUGGESTIONS.map((s) => <button key={s} disabled={!modelReady} onClick={() => void ask(s)}>{s}</button>)}
      </div>

      {chats.some((c) => c.message_count > 0) && (
        <section className="recent-chats">
          <h4>Recent chats</h4>
          <HistoryList chats={chats} activeId={null} onOpen={openChat} onDelete={removeChat} limit={5} />
        </section>
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
