import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TokensPage } from "./TokensPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("TokensPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/tokens")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [
                {
                  id: "1",
                  label: "acc1",
                  enabled: true,
                  refresh_token_masked: "***",
                  weight: 1.0,
                  error_count: 0,
                  backoff_until: null,
                  last_ok_at: null,
                  last_fail_at: null,
                },
              ],
              request_id: "req_tokens",
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
        <TokensPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tokens")).toBeInTheDocument();
    expect(await screen.findByText("acc1")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_tokens/)).toBeInTheDocument();
  });
});

