import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Approval, type Log, type Order, type Usage } from "./api";
import { Badge, BarChart, Empty, Shell, Stat, ToastProvider, useToast } from "./ui";
import results from "./data/results.json";

type Line = { role: "user" | "assistant"; content: string; intent?: string };
type Page = "chat" | "orders" | "approvals" | "logs" | "eval" | "about";
const SUGGESTIONS = ["Where is order A1002?", "How long does shipping take?", "I want a refund for A1001", "I want a refund for A1005", "Let me talk to a manager"];
const intentKind = (i?: string) => (!i ? "" : i.includes("human") || i.includes("needs") ? "warn" : i.includes("reject") || i.includes("fail") ? "bad" : i.includes("approved") || i.includes("refund") ? "ok" : "info");

export function App() { return <ToastProvider><Main /></ToastProvider>; }

function Main() {
  const toast = useToast();
  const [page, setPage] = useState<Page>("chat");
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
  const end = useRef<HTMLDivElement>(null);

  const side = useCallback(async (c = customer) => {
    const [o, a, l, u] = await Promise.all([api.orders(c), api.approvals(c), api.logs(c), api.usage(c)]);
    setOrders(o); setApprovals(a); setLogs(l); setUsage(u);
  }, [customer]);
  const run = useCallback(async (fn: () => Promise<void>) => {
    setError(""); setBusy(true);
    try { await fn(); } catch (e) { setError((e as Error).message); toast((e as Error).message, "bad"); } finally { setBusy(false); }
  }, [toast]);
  useEffect(() => { run(() => side()); }, [run, side]);
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: "smooth" }); }, [lines]);

  const send = (text: string) => run(async () => {
    setLines((l) => [...l, { role: "user", content: text }]); setQ("");
    const r = await api.chat(customer, text, conv);
    setConv(r.conversation_id);
    setLines((l) => [...l, { role: "assistant", content: r.reply, intent: r.intent ?? undefined }]);
    if (r.pending_approval_id) toast("Sent to the human approval queue");
    await side();
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) send(q.trim()); };
  const decide = (a: Approval, ok: boolean) => run(async () => {
    const r = await api.decide(customer, a.id, ok);
    setLines((l) => [...l, { role: "assistant", content: `[team decision] ${r.message}`, intent: "approval_" + r.status }]);
    toast(ok ? "Refund approved" : "Refund rejected", ok ? "ok" : undefined);
    await side();
  });
  const pending = approvals.filter((a) => a.status === "pending");

  return (
    <Shell brand="Support Agent" tagline="Tool-using AI agent" page={page} onNav={(p) => setPage(p as Page)}
      nav={[{ id: "chat", label: "Customer chat", icon: "✎" }, { id: "orders", label: "Orders", icon: "▤", badge: orders.length }, { id: "approvals", label: "Approval queue", icon: "✓", badge: pending.length }, { id: "logs", label: "Tool log & cost", icon: "≡" }, { id: "eval", label: "Classifier accuracy", icon: "◎" }, { id: "about", label: "How it works", icon: "?" }]}
      actions={<>
        <select aria-label="Customer" value={customer} onChange={(e) => { setCustomer(e.target.value); setConv(null); setLines([]); }}><option>sara@example.com</option><option>omar@example.com</option></select>
        <button className="btn sm" onClick={() => run(async () => { await api.reset(customer); setConv(null); setLines([]); await side(); toast("Demo data reset", "ok"); })}>Reset demo data</button>
      </>}>
      {error && <p role="alert" className="err">{error}</p>}

      {page === "chat" && (
        <div className="grid g-main">
          <div className="col">
            <div className="page-h"><div><h1>Customer chat</h1><p>The agent classifies the message, calls tools, and escalates what it should not decide alone.</p></div></div>
            <div className="row">{SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>)}</div>
            <div className="thread" aria-live="polite">
              {lines.length === 0 && <div className="card"><Empty icon="✎" title="Start a conversation" hint="Pick a suggestion above or type a message. Try the $349 refund to see human approval." /></div>}
              {lines.map((m, i) => <div key={i} className={`msg ${m.role}`}>{m.content}{m.intent && <div className="it"><Badge kind={intentKind(m.intent)}>intent: {m.intent}</Badge></div>}</div>)}
              {busy && lines.length > 0 && <div className="msg"><span className="spin" /> working...</div>}
              <div ref={end} />
            </div>
            <form onSubmit={submit} className="bar-in"><input aria-label="Message" value={q} placeholder="Type a message as the customer" onChange={(e) => setQ(e.target.value)} /><button className="btn primary" type="submit" disabled={busy}>Send</button></form>
          </div>
          <div className="col">
            <div className="card"><h3>Human approval {pending.length > 0 && <Badge kind="warn">{pending.length} pending</Badge>}</h3>
              {pending.length === 0 ? <p className="muted small">No pending requests. Refunds over $200 land here.</p> : pending.map((a) => (
                <div key={a.id} className="row" style={{ marginBottom: 8 }}><span>#{a.id} {a.order_no} <b>${a.amount.toFixed(2)}</b></span><span className="sp row"><button className="btn sm primary" onClick={() => decide(a, true)}>Approve</button><button className="btn sm" onClick={() => decide(a, false)}>Reject</button></span></div>))}
            </div>
            <div className="card"><h3>Orders</h3><div className="list">{orders.map((o) => <div key={o.order_no} className="row"><b>{o.order_no}</b><span className="muted small">{o.items}</span><span className="sp"><Badge kind={o.refunded ? "info" : o.status === "delivered" ? "ok" : "warn"}>{o.refunded ? "refunded" : o.status}</Badge></span></div>)}</div></div>
          </div>
        </div>
      )}

      {page === "orders" && (<>
        <div className="page-h"><div><h1>Orders</h1><p>Synthetic data for {customer}. The agent reads this through its Order Lookup tool.</p></div></div>
        <div className="card tw"><table className="t"><thead><tr><th>Order</th><th>Items</th><th>Total</th><th>Status</th></tr></thead><tbody>{orders.map((o) => <tr key={o.order_no}><td><b>{o.order_no}</b></td><td>{o.items}</td><td>${o.total.toFixed(2)}</td><td><Badge kind={o.refunded ? "info" : o.status === "delivered" ? "ok" : "warn"}>{o.refunded ? "refunded" : o.status}</Badge></td></tr>)}</tbody></table></div></>)}

      {page === "approvals" && (<>
        <div className="page-h"><div><h1>Approval queue</h1><p>Refunds above $200 stop here until a person decides. The refund tool re-checks every rule when it executes.</p></div></div>
        <div className="grid g3"><Stat label="Pending" value={pending.length} /><Stat label="Approved" value={approvals.filter((a) => a.status === "approved").length} /><Stat label="Rejected" value={approvals.filter((a) => a.status === "rejected").length} /></div>
        <div className="card tw">{approvals.length === 0 ? <Empty icon="✓" title="Nothing to review" hint='In Customer chat, send "I want a refund for A1005".' /> : <table className="t"><thead><tr><th>#</th><th>Order</th><th>Amount</th><th>Status</th><th /></tr></thead><tbody>{approvals.map((a) => <tr key={a.id}><td>{a.id}</td><td>{a.order_no}</td><td>${a.amount.toFixed(2)}</td><td><Badge kind={a.status === "pending" ? "warn" : a.status === "approved" ? "ok" : "bad"}>{a.status}</Badge></td><td>{a.status === "pending" && <span className="row"><button className="btn sm primary" onClick={() => decide(a, true)}>Approve</button><button className="btn sm" onClick={() => decide(a, false)}>Reject</button></span>}</td></tr>)}</tbody></table>}</div></>)}

      {page === "logs" && (<>
        <div className="page-h"><div><h1>Tool log and cost</h1><p>Every tool call is logged with arguments, retries and latency.</p></div></div>
        {usage && <div className="grid g4"><Stat label="LLM calls" value={usage.llm_calls} /><Stat label="Tokens in / out" value={`${usage.tokens_in} / ${usage.tokens_out}`} /><Stat label="Cost" value={`$${usage.cost_usd.toFixed(4)}`} /><Stat label="Tool calls" value={logs.length} hint={`${logs.filter((l) => !l.ok).length} failed`} /></div>}
        {usage?.note && <p className="muted small">{usage.note}</p>}
        <div className="card tw">{logs.length === 0 ? <Empty icon="≡" title="No tool calls yet" hint="Chat with the agent first." /> : <table className="t"><thead><tr><th>Tool</th><th>Arguments</th><th>Result</th><th>Tries</th><th>Latency</th></tr></thead><tbody>{logs.map((l, i) => <tr key={i}><td><Badge kind={l.ok ? "ok" : "bad"}>{l.ok ? "ok" : "fail"}</Badge> <span className="mono">{l.tool}</span></td><td className="mono">{l.args}</td><td className="small muted">{l.result.slice(0, 80)}</td><td>{l.attempts}</td><td>{l.latency_ms} ms</td></tr>)}</tbody></table>}</div></>)}

      {page === "eval" && <EvalPage />}
      {page === "about" && (<>
        <div className="page-h"><div><h1>How it works</h1><p>A LangGraph state machine over FastAPI and PostgreSQL.</p></div></div>
        <div className="card"><div className="flow"><span className="n">classify</span><span className="a">→</span><span className="n">order_status → reply</span><span className="a">|</span><span className="n">faq → reply</span><span className="a">|</span><span className="n">refund → check rules</span><span className="a">→</span><span className="n">≤ $200 execute</span><span className="a">/</span><span className="n">&gt; $200 human approval</span><span className="a">|</span><span className="n">human → escalate</span></div></div>
        <div className="grid g3"><div className="card"><h3>The brain proposes, tools decide</h3><p className="muted">Business rules (30-day window, delivered only, $200 approval limit) live in code, so a manipulated classifier cannot break them.</p></div><div className="card"><h3>Retries and logging</h3><p className="muted">Flaky tool calls are retried; every attempt is logged with latency.</p></div><div className="card"><h3>No LLM key here</h3><p className="muted">The live demo uses a rule-based classifier. With an API key the LLM path adds usage and cost tracking.</p></div></div></>)}
    </Shell>
  );
}

function EvalPage() {
  const r = results as { n: number; accuracy: number; classifier: string; per_intent: Record<string, { precision: number; recall: number; n: number }>; errors: { text: string; label: string; predicted: string }[] };
  const intents = Object.entries(r.per_intent);
  return (<>
    <div className="page-h"><div><h1>Classifier accuracy</h1><p>{r.n} labelled messages, {r.classifier} classifier. Measured offline by the repo's eval script.</p></div></div>
    <div className="grid g3"><Stat label="Accuracy" value={`${(r.accuracy * 100).toFixed(1)}%`} /><Stat label="Messages" value={r.n} /><Stat label="Errors" value={r.errors.length} /></div>
    <div className="grid g2">
      <div className="card"><h3>Precision by intent</h3><BarChart max={1} data={intents.map(([k, v]) => ({ label: k, value: v.precision }))} /><div className="row small muted" style={{ justifyContent: "space-around" }}>{intents.map(([k]) => <span key={k}>{k}</span>)}</div></div>
      <div className="card"><h3>Recall by intent</h3><BarChart max={1} data={intents.map(([k, v]) => ({ label: k, value: v.recall }))} color="var(--accent-2)" /><div className="row small muted" style={{ justifyContent: "space-around" }}>{intents.map(([k]) => <span key={k}>{k}</span>)}</div></div>
    </div>
    <div className="card"><h3>Misclassified</h3>{r.errors.map((e) => <p key={e.text}>"{e.text}" labelled <Badge>{e.label}</Badge> predicted <Badge kind="bad">{e.predicted}</Badge></p>)}<p className="muted small" style={{ marginTop: 8 }}>The rules were tuned after seeing an earlier version of this set, so accuracy is optimistic. It is not an independent test.</p></div>
  </>);
}
