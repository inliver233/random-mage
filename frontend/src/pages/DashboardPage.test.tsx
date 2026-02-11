import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/settings")) {
          return new Response(
            JSON.stringify({
              ok: true,
              settings: {
                proxy: { enabled: false, fail_closed: true, route_mode: "pixiv_only", allowlist_domains: [] },
                random: {},
                security: { hide_origin_url_in_public_json: true },
                rate_limit: {},
              },
              request_id: "req_settings",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/admin/api/tokens")) {
          return new Response(JSON.stringify({ ok: true, items: [{}, {}], request_id: "req_tokens" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/admin/api/proxies/endpoints")) {
          return new Response(JSON.stringify({ ok: true, items: [{}], request_id: "req_proxies" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/admin/api/jobs?status=failed")) {
          return new Response(JSON.stringify({ ok: true, items: [{}, {}, {}], next_cursor: "", request_id: "req_jobs" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ ok: false, code: "NOT_FOUND", message: "not found", request_id: "req_x", details: {} }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  it("renders fetched counts", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("count: 2")).toBeInTheDocument();
    expect(await screen.findByText("count: 1")).toBeInTheDocument();
    expect(await screen.findByText("count: 3")).toBeInTheDocument();
  });
});

