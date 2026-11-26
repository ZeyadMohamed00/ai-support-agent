export const API_BASE: string = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "/api" : "");

export function clientId(): string {
  let id = localStorage.getItem("sup_client_id");
  if (!id) {
    id = (crypto.randomUUID?.() ?? String(Date.now()) + Math.random().toString(16).slice(2)).replace(/[^a-zA-Z0-9-]/g, "");
    localStorage.setItem("sup_client_id", id);
  }
  return id;
}

async function req<T>(path: string, customer: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Client-Id": clientId(), "X-Customer": customer };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(API_BASE + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new Error(msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export type Order = { order_no: string; status: string; total: number; items: string; refunded: boolean };
export type Approval = { id: number; customer: string; order_no: string; amount: number; status: string };
export type Log = { tool: string; args: string; result: string; attempts: number; ok: boolean; latency_ms: number };
export type Usage = { llm_calls: number; tokens_in: number; tokens_out: number; cost_usd: number; note: string };
export type ChatOut = { conversation_id: number; reply: string; intent: string | null; pending_approval_id: number | null };

export const api = {
  chat: (c: string, message: string, conversation_id: number | null) => req<ChatOut>("/chat", c, "POST", { message, conversation_id }),
  conversation: (c: string, id: number) => req<{ role: string; content: string; intent: string }[]>(`/conversations/${id}`, c),
  orders: (c: string) => req<Order[]>("/orders", c),
  approvals: (c: string) => req<Approval[]>("/approvals", c),
  decide: (c: string, id: number, approve: boolean) => req<{ id: number; status: string; message: string }>(`/approvals/${id}/decision`, c, "POST", { approve }),
  logs: (c: string) => req<Log[]>("/logs", c),
  usage: (c: string) => req<Usage>("/usage", c),
  reset: (c: string) => req<void>("/demo/reset", c, "POST", {}),
};
