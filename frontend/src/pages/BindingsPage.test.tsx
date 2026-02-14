import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";
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
                  token: { id: "1", label: "acc1" },
                  pool: { id: "1", name: "pixiv" },
                  primary_proxy: { id: "10", scheme: "http", host: "1.2.3.4", port: 8080, username: "u1" },
                  override_proxy: null,
                  override_expires_at: null,
                  effective_proxy_id: "10",
                  effective_mode: "primary",
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
      <MemoryRouter initialEntries={["/admin/bindings?pool_id=1"]}>
        <QueryClientProvider client={qc}>
          <BindingsPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("令牌与代理绑定")).toBeInTheDocument();
    expect(await screen.findByText("acc1（#1）")).toBeInTheDocument();
    expect(await screen.findByText("pixiv（#1）")).toBeInTheDocument();
    expect(await screen.findByText(/请求ID:\s*req_bindings/)).toBeInTheDocument();
  });
});
