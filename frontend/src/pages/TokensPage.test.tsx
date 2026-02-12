import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TokensPage } from "./TokensPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("TokensPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    let listCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/api/tokens") && init?.method === "POST") {
          const body = init?.body ? JSON.parse(String(init.body)) : {};
          expect(body.refresh_token).toBe("rt_test");
          return new Response(JSON.stringify({ ok: true, token_id: "2", request_id: "req_create" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/admin/api/tokens")) {
          listCalls += 1;
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
                  last_error_code: null,
                  last_error_msg: null,
                },
              ],
              request_id: `req_tokens_${listCalls}`,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/admin/api/tokens/1/test-refresh")) {
          expect(init?.method).toBe("POST");
          return new Response(JSON.stringify({ ok: true, expires_in: 123, user_id: "u1", request_id: "req_test_refresh" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/admin/api/tokens/1/reset-failures")) {
          expect(init?.method).toBe("POST");
          return new Response(JSON.stringify({ ok: true, token_id: "1", request_id: "req_reset" }), {
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
        <TokensPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tokens")).toBeInTheDocument();
    expect(await screen.findByText("acc1")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_tokens_1/)).toBeInTheDocument();
  });

  it("creates token", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <TokensPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tokens")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /新增\s*Token/ }));
    const dialog = await screen.findByRole("dialog", { name: /新增\s*Token/ });
    fireEvent.change(within(dialog).getByPlaceholderText("required"), { target: { value: "rt_test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /创\s*建/ }));

    expect(await screen.findByText(/Token created:\s*2/)).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_create/)).toBeInTheDocument();
  });

  it("tests refresh and resets failures", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <TokensPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tokens")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /测试刷新/ }));
    expect(await screen.findByText(/Token refresh OK/)).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_test_refresh/)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /重置失败退避/ }));
    expect(await screen.findByText(/Token failures reset:\s*1/)).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_reset/)).toBeInTheDocument();
  });
});
