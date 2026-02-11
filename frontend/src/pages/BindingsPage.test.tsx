import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BindingsPage } from "./BindingsPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("BindingsPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/bindings?pool_id=1")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [
                {
                  id: "1",
                  token_id: "t1",
                  proxy_id: "p1",
                  is_primary: true,
                  override_proxy_id: null,
                  override_expires_at: null,
                  reason: null,
                },
              ],
              request_id: "req_bindings",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({ ok: false, code: "NOT_FOUND", message: "not found", request_id: "req_x", details: {} }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  it("renders list", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <BindingsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Bindings")).toBeInTheDocument();
    expect(await screen.findByText("t1")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_bindings/)).toBeInTheDocument();
  });
});

