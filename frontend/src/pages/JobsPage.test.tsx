import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobsPage } from "./JobsPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("JobsPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/jobs?status=failed&limit=20")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [
                {
                  id: "j1",
                  type: "proxy_probe",
                  status: "failed",
                  attempt: 1,
                  max_attempts: 3,
                  run_after: null,
                  last_error_code: "UPSTREAM_403",
                  last_error_message: "forbidden",
                  updated_at: "2026-02-11T00:00:00Z",
                },
              ],
              next_cursor: "",
              request_id: "req_jobs",
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
        <JobsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("任务队列")).toBeInTheDocument();
    expect(await screen.findByText("代理探测")).toBeInTheDocument();
    expect(await screen.findByText(/请求ID:\s*req_jobs/)).toBeInTheDocument();
  });
});
