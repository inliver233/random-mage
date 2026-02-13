import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";
import { ImportPage } from "./ImportPage";
import { PlaygroundPage } from "./PlaygroundPage";
import { TokensPage } from "./TokensPage";
import { ProxiesPage } from "./ProxiesPage";
import { JobsPage } from "./JobsPage";
import { ImagesPage } from "./ImagesPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("DashboardPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
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
        if (url.endsWith("/admin/api/summary")) {
          return new Response(
            JSON.stringify({
              ok: true,
              counts: {
                images: { total: 14, enabled: 14 },
                tokens: { total: 2, enabled: 1 },
                proxies: { endpoints_total: 1, endpoints_enabled: 1 },
                proxy_pools: { total: 0, enabled: 0 },
                bindings: { total: 0 },
                jobs: { counts: { pending: 2, running: 0, failed: 3 } },
                worker: { last_seen_at: "2026-02-13T00:00:00Z" },
              },
              request_id: "req_summary",
            }),
            {
            status: 200,
            headers: { "Content-Type": "application/json" },
            },
          );
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
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("worker.last_seen_at: 2026-02-13T00:00:00Z")).toBeInTheDocument();
    expect(await screen.findByText("total: 14")).toBeInTheDocument();
    expect(await screen.findByText("total: 2")).toBeInTheDocument();
    expect(await screen.findByText("endpoints: 1/1 enabled")).toBeInTheDocument();
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
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Worker / Queue")).toBeInTheDocument();
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
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Worker / Queue")).toBeInTheDocument();
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
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Worker / Queue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /去\s*添\s*加\s*Token/ }));
    expect(await screen.findByRole("button", { name: /新\s*增\s*Token/ })).toBeInTheDocument();
  });

  it("navigates to proxies", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Worker / Queue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /去\s*添\s*加\s*代\s*理/ }));
    expect(await screen.findByText("Proxies")).toBeInTheDocument();
  });

  it("navigates to playground", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin"]}>
          <Routes>
            <Route path="/admin" element={<DashboardPage />} />
            <Route path="/admin/import" element={<ImportPage />} />
            <Route path="/admin/tokens" element={<TokensPage />} />
            <Route path="/admin/proxies" element={<ProxiesPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/images" element={<ImagesPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Worker / Queue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /打\s*开\s*Playground/ }));
    expect(await screen.findByText("Random Playground")).toBeInTheDocument();
  });
});
