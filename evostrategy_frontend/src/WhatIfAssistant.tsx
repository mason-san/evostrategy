import { useEffect, useRef, useState } from "react";
import { api, humanize, money, type AssistantModel, type ScenarioInput, type ScenarioResult, type WhatIfAnswer } from "./api";
import { RichText } from "./Home";

type Change = { label: string; from: string; to: string };
type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; changes?: Change[]; simulation?: ScenarioResult | null; error?: string };

const LEVERS: Array<{ key: keyof ScenarioInput; label: string; unit: string }> = [
  { key: "volume_change_pct", label: "Sales volume", unit: "%" },
  { key: "pricing_adjustment_pct", label: "Pricing", unit: "%" },
  { key: "price_elasticity", label: "Price elasticity", unit: "" },
  { key: "headcount_change", label: "Headcount", unit: " people" },
  { key: "vendor_consolidation_pct", label: "Vendor savings", unit: "%" },
  { key: "other_cost_change_pct", label: "Other costs", unit: "%" },
  { key: "horizon", label: "Horizon", unit: " months" },
];

type Tab = { id: string; title: string; messages: Message[] };
const STORE_KEY = "evostrategy.whatif.tabs";
const newTab = (): Tab => ({ id: Math.random().toString(36).slice(2, 10), title: "New chat", messages: [] });
const MAX_TABS = 6;

function loadTabs(): { tabs: Tab[]; active: string } {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORE_KEY) ?? "null") as { tabs: Tab[]; active: string } | null;
    if (saved?.tabs?.length) return { tabs: saved.tabs, active: saved.tabs.some((t) => t.id === saved.active) ? saved.active : saved.tabs[0].id };
  } catch { /* storage unavailable or corrupt: start fresh */ }
  const first = newTab();
  return { tabs: [first], active: first.id };
}

const show = (value: number, unit: string) => `${value > 0 && unit === "%" ? "+" : ""}${value}${unit}`;

function diff(before: ScenarioInput, after: ScenarioInput): Change[] {
  return LEVERS.filter(({ key }) => before[key] !== after[key])
    .map(({ key, label, unit }) => ({ label, from: show(before[key], unit), to: show(after[key], unit) }));
}

const SUGGESTIONS = [
  "What if we hire 3 people?",
  "Raise prices 8% and see the profit",
  "Cut vendor costs by 15%",
  "Reset everything",
];

/** Floating assistant for the What-if tab: talk to it and it moves the sliders and reads out the results. */
export function WhatIfAssistant({ input, onApply }: { input: ScenarioInput; onApply: (scenario: ScenarioInput) => void }) {
  const [open, setOpen] = useState(false);
  const [{ tabs, active }, setBoard] = useState(loadTabs);
  const [busyTabs, setBusyTabs] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [models, setModels] = useState<AssistantModel[]>([]);
  const [model, setModel] = useState("");
  const [configured, setConfigured] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);

  const current = tabs.find((t) => t.id === active) ?? tabs[0];
  const messages = current.messages;
  const busy = busyTabs.includes(current.id);

  useEffect(() => {
    api.assistantStatus().then((status) => {
      setModels(status.models.filter((m) => m.available));
      setModel(status.default_model);
      setConfigured(status.configured);
    }).catch(() => { /* the send itself will report the problem */ });
  }, []);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [messages, busy, open, active]);
  useEffect(() => { if (open) field.current?.focus(); }, [open]);

  useEffect(() => {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify({ tabs: tabs.map((t) => ({ ...t, messages: t.messages.slice(-30) })), active })); } catch { /* storage unavailable */ }
  }, [tabs, active]);

  const addMessage = (tabId: string, message: Message) =>
    setBoard((b) => ({ ...b, tabs: b.tabs.map((t) => t.id !== tabId ? t : {
      ...t, title: t.title === "New chat" && message.role === "user" ? message.text.slice(0, 28) : t.title, messages: [...t.messages, message] } ) }));
  const select = (id: string) => setBoard((b) => ({ ...b, active: id }));
  const add = () => setBoard((b) => {
    if (b.tabs.length >= MAX_TABS) return b;
    const tab = newTab();
    return { tabs: [...b.tabs, tab], active: tab.id };
  });
  const close = (id: string) => setBoard((b) => {
    const remaining = b.tabs.filter((t) => t.id !== id);
    if (!remaining.length) { const fresh = newTab(); return { tabs: [fresh], active: fresh.id }; }
    return { tabs: remaining, active: b.active === id ? remaining[Math.max(0, b.tabs.findIndex((t) => t.id === id) - 1)].id : b.active };
  });

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    const history = messages.filter((m) => !(m.role === "assistant" && m.error)).map((m) => ({ role: m.role, content: m.text }));
    const tabId = current.id;
    addMessage(tabId, { role: "user", text: question });
    setDraft("");
    setBusyTabs((ids) => [...ids, tabId]);
    try {
      const reply: WhatIfAnswer = await api.whatifAssistant(question, input, history, model || undefined);
      const changes = diff(input, reply.scenario);
      if (changes.length) onApply(reply.scenario);
      addMessage(tabId, { role: "assistant", text: reply.answer, changes, simulation: changes.length ? reply.simulation : null });
    } catch (e) {
      addMessage(tabId, { role: "assistant", text: "", error: (e as Error).message });
    } finally {
      setBusyTabs((ids) => ids.filter((id) => id !== tabId));
    }
  };

  return (
    <>
      {open && (
        <section className="wi-panel" role="dialog" aria-label="What-if assistant">
          <header>
            <span className="assistant-mark">E</span>
            <div><strong>What-if assistant</strong><small>Describe a decision and I'll set the levers</small></div>
            <button className="wi-close" aria-label="Close assistant" onClick={() => setOpen(false)}>×</button>
          </header>
          <div className="wi-tabs" role="tablist">
            {tabs.map((t) => (
              <span key={t.id} role="tab" aria-selected={t.id === active} className={`wi-tab ${t.id === active ? "active" : ""}`}>
                <button onClick={() => select(t.id)}>{busyTabs.includes(t.id) && <i className="tab-busy" />}{t.title}</button>
                <button className="wi-tab-close" aria-label={`Close ${t.title}`} onClick={() => close(t.id)}>×</button>
              </span>
            ))}
            <button className="wi-tab-add" aria-label="New chat" disabled={tabs.length >= MAX_TABS} onClick={add}>+</button>
          </div>
          <div className="wi-thread" ref={scroller}>
            {!messages.length && (
              <div className="wi-empty">
                <p>Tell me what you're considering and I'll move the sliders, run the numbers on your verified baseline and tell you what happens to profit.</p>
                <div className="wi-suggest">{SUGGESTIONS.map((s) => <button key={s} disabled={busy || !configured} onClick={() => void send(s)}>{s}</button>)}</div>
              </div>
            )}
            {messages.map((m, i) => m.role === "user"
              ? <div className="wi-user" key={i}><span>{m.text}</span></div>
              : (
                <div className="wi-bot" key={i}>
                  {m.error ? <p className="answer-error">{m.error}</p> : <div className="answer-body"><RichText text={m.text} /></div>}
                  {m.changes && m.changes.length > 0 && (
                    <ul className="wi-changes" aria-label="Sliders changed">
                      {m.changes.map((c) => <li key={c.label}><b>{c.label}</b><span>{c.from}</span>→<strong>{c.to}</strong></li>)}
                    </ul>
                  )}
                  {m.simulation && !m.simulation.error && (
                    <div className="wi-result">
                      {(["revenue", "expense", "profit"] as const).map((metric) => {
                        const delta = m.simulation!.totals.delta[metric];
                        const good = metric === "expense" ? delta <= 0 : delta >= 0;
                        return (
                          <div key={metric}>
                            <span>{humanize(metric)}</span>
                            <strong>{money(m.simulation!.totals.scenario[metric], true)}</strong>
                            <small className={delta === 0 ? "" : good ? "pos" : "neg"}>{delta >= 0 ? "+" : ""}{money(delta, true)}</small>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            {busy && <div className="thinking wi-thinking"><span /><span /><span />Working it out</div>}
          </div>
          {!configured && <p className="wi-note">The assistant isn't configured. Add an API key or start Ollama, then reload.</p>}
          <form className="wi-input" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
            <input ref={field} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="e.g. hire 2 people and raise prices 5%" disabled={busy || !configured} maxLength={2000} />
            <button type="submit" disabled={busy || !draft.trim() || !configured} aria-label="Send">↑</button>
          </form>
          {models.length > 1 && (
            <select className="wi-model" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          )}
        </section>
      )}
      <button className={`wi-fab ${open ? "open" : ""}`} aria-label={open ? "Close what-if assistant" : "Open what-if assistant"} onClick={() => setOpen((v) => !v)}>
        {open ? "×" : "E"}
      </button>
    </>
  );
}
