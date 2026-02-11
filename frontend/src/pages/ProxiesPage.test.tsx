import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProxiesPage } from "./ProxiesPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ProxiesPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/proxies/endpoints")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [
                {
                  id: "1",
                  uri_masked: "http://***:***@1.2.3.4:8080",
                  enabled: true,
                  latency_ms: 123,
                  status: "ok",
                  blacklisted_until: null,
                  last_error: null,
                },
              ],
              request_id: "req_proxies",
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
        <ProxiesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Proxies")).toBeInTheDocument();
    expect(await screen.findByText("http://***:***@1.2.3.4:8080")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_proxies/)).toBeInTheDocument();
  });
});

