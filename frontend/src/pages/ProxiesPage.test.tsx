import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProxiesPage } from "./ProxiesPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ProxiesPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    let endpointsCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/api/proxies/endpoints")) {
          endpointsCalls += 1;
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
              request_id: `req_proxies_${endpointsCalls}`,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/admin/api/proxies/endpoints/import")) {
          expect(init?.method).toBe("POST");
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          expect(body.source).toBe("manual");
          expect(body.conflict_policy).toBe("overwrite");
          expect(String(body.text || "")).toContain("http://u:pa@ss@1.2.3.4:8080");
          expect(String(body.text || "")).toContain("socks5://5.6.7.8:1080");
          return new Response(JSON.stringify({ ok: true, created: 2, updated: 0, skipped: 0, errors: [], request_id: "req_manual" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/admin/api/proxies/easy-proxies/import")) {
          expect(init?.method).toBe("POST");
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          expect(body.base_url).toBe("http://easy.test");
          expect(body.password).toBe("pw_test");
          expect(body.conflict_policy).toBe("skip_non_easy_proxies");
          return new Response(
            JSON.stringify({ ok: true, created: 1, updated: 0, skipped: 0, errors: [], request_id: "req_easy" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/admin/api/proxies/probe")) {
          expect(init?.method).toBe("POST");
          return new Response(JSON.stringify({ ok: true, job_id: "job_1", request_id: "req_probe" }), {
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

  it("renders list", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ProxiesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Proxies")).toBeInTheDocument();
    expect(await screen.findByText("http://***:***@1.2.3.4:8080")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_proxies_1/)).toBeInTheDocument();
  });

  it("imports from easy_proxies", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ProxiesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Proxies")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("http://easy-proxies:9090"), { target: { value: "http://easy.test" } });
    fireEvent.change(screen.getByPlaceholderText("required"), { target: { value: "pw_test" } });
    fireEvent.click(screen.getByRole("button", { name: /从\s*easy_proxies\s*导入/ }));

    expect(await screen.findByText("easy_proxies imported")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_easy/)).toBeInTheDocument();
  });

  it("imports manual endpoints", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ProxiesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Proxies")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("http://user:pass@1.2.3.4:8080"), {
      target: { value: "http://u:pa@ss@1.2.3.4:8080\nsocks5://5.6.7.8:1080\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^导\s*入$/ }));

    expect(await screen.findByText("Imported")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_manual/)).toBeInTheDocument();
  });

  it("enqueues proxy probe job", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ProxiesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Proxies")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /探测健康/ }));

    expect(await screen.findByText("probe enqueued")).toBeInTheDocument();
    expect(await screen.findByText(/job_id:\s*job_1/)).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_probe/)).toBeInTheDocument();
  });
});
