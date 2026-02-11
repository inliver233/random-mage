import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";
import { ImportPage } from "./ImportPage";
import { TokensPage } from "./TokensPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("DashboardPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    let proxiesCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
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
                {
                  id: "2",
                  label: "acc2",
                  enabled: false,
                  refresh_token_masked: "***",
                  weight: 1.0,
                  error_count: 3,
                  backoff_until: null,
                  last_ok_at: null,
                  last_fail_at: null,
                },
              ],
              request_id: "req_tokens",
            }),
            {
            status: 200,
            headers: { "Content-Type": "application/json" },
            },
          );
        }
        if (url.endsWith("/admin/api/proxies/endpoints")) {
          proxiesCalls += 1;
          return new Response(JSON.stringify({ ok: true, items: [{}], request_id: `req_proxies_${proxiesCalls}` }), {
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
        if (url.endsWith("/admin/api/hydration-runs")) {
          return new Response(JSON.stringify({ ok: true, hydration_run_id: "10", job_id: "99", request_id: "req_hyd" }), {
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
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("count: 2")).toBeInTheDocument();
    expect(await screen.findByText("count: 1")).toBeInTheDocument();
    expect(await screen.findByText("count: 3")).toBeInTheDocument();
  });

  it("navigates to import", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Settings")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /去\s*导\s*入/ }));
    expect(await screen.findByText("Import")).toBeInTheDocument();
  });

  it("creates hydration run", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Settings")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /创\s*建\s*补\s*全\s*任\s*务/ }));
    expect(await screen.findByText("Hydration run created")).toBeInTheDocument();
    expect(await screen.findByText(/hydration_run_id:\s*10/)).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_hyd/)).toBeInTheDocument();
  });

  it("navigates to tokens", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Settings")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /去\s*添\s*加\s*Token/ }));
    expect(await screen.findByRole("button", { name: /新\s*增\s*Token/ })).toBeInTheDocument();
  });

  it("refreshes proxies", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("request_id: req_proxies_1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /刷\s*新\s*代\s*理/ }));
    expect(await screen.findByText("request_id: req_proxies_2")).toBeInTheDocument();
  });
});
