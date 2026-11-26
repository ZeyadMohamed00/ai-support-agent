import { useEffect, useState, type FormEvent } from "react";
import { api, type Approval, type Log, type Order, type Usage } from "./api";

type Line = { role: "user" | "assistant"; content: string; intent?: string };
const SUGGESTIONS = ["Where is order A1002?", "How long does shipping take?", "I want a refund for A1001", "I want a refund for A1005", "Let me talk to a manager"];

export function App() {
  const [customer, setCustomer] = useState("sara@example.com");
  const [conv, setConv] = useState<number | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);

  const side = async (c = customer) => {
    const [o, a, l, u] = await Promise.all([api.orders(c), api.approvals(c), api.logs(c), api.usage(c)]);
    setOrders(o); setApprovals(a); setLogs(l); setUsage(u);
  };
  const run = async (fn: () => Promise<void>) => {
    setError(""); setBusy(true);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  useEffect(() => { run(() => side()); }, [customer]);

  const send = (text: string) => run(async () => {
    setLines((l) => [...l, { role: "user", content: text }]); setQ("");
    const r = await api.chat(customer, text, conv);
    setConv(r.conversation_id);
    setLines((l) => [...l, { role: "assistant", content: r.reply, intent: r.intent ?? undefined }]);
    await side();
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) send(q.trim()); };

  const decide = (a: Approval, ok: boolean) => run(async () => {
    const r = await api.decide(customer, a.id, ok);
    setLines((l) => [...l, { role: "assistant", content: `[team decision] ${r.message}`, intent: "approval_" + r.status }]);
    await side();
  });

  return (
    <div className="wrap">
      <header>
        <h1>AI Customer Support Agent</h1>
        <label>Demo customer{" "}
          <select aria-label="Customer" value={customer} onChange={(e) => { setCustomer(e.target.value); setConv(null); setLines([]); }}>
            <option>sara@example.com</option><option>omar@example.com</option>
          </select>
        </label>
        <button onClick={() => run(async () => { await api.reset(customer); setConv(null); setLines([]); await side(); })}>Reset demo data</button>
        <p className="muted">Synthetic shop data, private to your browser. The agent here is rule-based (no LLM key configured).</p>
      </header>
      {error && <p role="alert" className="err">{error}</p>}
      <div className="grid">
        <section>
          <h3>Chat</h3>
          <div className="chips">{SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>)}</div>
          <div className="thread">
            {lines.length === 0 && <p className="muted">Pick a suggestion or type a message.</p>}
            {lines.map((m, i) => (
              <div key={i} className={"msg " + m.role}>{m.content}{m.intent && <span className="muted"> intent: {m.intent}</span>}</div>
            ))}
          </div>
          <form onSubmit={submit} className="bar">
            <input aria-label="Message" value={q} placeholder="Type a message" onChange={(e) => setQ(e.target.value)} />
            <button type="submit" disabled={busy}>Send</button>
          </form>
        </section>
        <section>
          <h3>Orders ({customer.split("@")[0]})</h3>
          <ul>{orders.map((o) => <li key={o.order_no}>{o.order_no}: {o.items}, ${o.total.toFixed(2)}, {o.status}{o.refunded ? " (refunded)" : ""}</li>)}</ul>
          <h3>Human approval queue</h3>
          {approvals.length === 0 && <p className="muted">No requests. Try "I want a refund for A1005" (over $200).</p>}
          <ul>{approvals.map((a) => (
            <li key={a.id}>#{a.id} {a.order_no} ${a.amount.toFixed(2)} <strong>{a.status}</strong>
              {a.status === "pending" && <> <button onClick={() => decide(a, true)}>Approve</button> <button onClick={() => decide(a, false)}>Reject</button></>}
            </li>))}
          </ul>
          <h3>Tool log</h3>
          <ul className="logs">{logs.slice(0, 8).map((l, i) => <li key={i}>{l.ok ? "ok" : "FAIL"} {l.tool} {l.args} ({l.attempts} try, {l.latency_ms}ms)</li>)}</ul>
          {usage && <p className="muted">LLM usage: {usage.llm_calls} calls, ${usage.cost_usd.toFixed(4)}. {usage.note}</p>}
        </section>
      </div>
    </div>
  );
}
