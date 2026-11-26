import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";

let approvals: unknown[] = [];
beforeEach(() => {
  approvals = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url.endsWith("/chat")) { approvals = [{ id: 1, customer: "sara@example.com", order_no: "A1005", amount: 349, status: "pending" }];
      return ok({ conversation_id: 1, reply: "Refunds over $200 need a human to approve.", intent: "refund_needs_human", pending_approval_id: 1 }); }
    if (url.endsWith("/orders")) return ok([{ order_no: "A1005", status: "delivered", total: 349, items: "Standing Desk", refunded: false }]);
    if (url.endsWith("/approvals")) return ok(approvals);
    if (url.includes("/decision")) { approvals = [{ id: 1, customer: "sara@example.com", order_no: "A1005", amount: 349, status: "approved" }];
      return ok({ id: 1, status: "approved", message: "refunded $349.00" }); }
    if (url.endsWith("/logs")) return ok([]);
    if (url.endsWith("/usage")) return ok({ llm_calls: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, note: "" });
    return ok({});
  }));
});

test("large refund shows in approval queue and can be approved", async () => {
  render(<App />);
  await userEvent.click(await screen.findByText("I want a refund for A1005"));
  await screen.findByText(/need a human to approve/);
  await userEvent.click(await screen.findByText("Approve"));
  await waitFor(() => expect(screen.getByText(/\[team decision\] refunded \$349.00/)).toBeInTheDocument());
});

test("typing a message sends it", async () => {
  render(<App />);
  await userEvent.type(await screen.findByLabelText("Message"), "hello{enter}");
  await screen.findByText("hello");
});
