import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportDetailPage } from "./ImportDetailPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ImportDetailPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/admin/api/imports/123")) {
          return new Response(
            JSON.stringify({
              ok: true,
              item: {
                import: {
                  id: "123",
                  created_at: "2026-02-11T00:00:00Z",
                  created_by: "admin",
                  source: "manual",
                  total: 3,
                  accepted: 3,
                  success: 2,
                  failed: 1,
                },
                job: {
                  id: "9",
                  type: "import_images",
                  status: "completed",
                  attempt: 0,
                  max_attempts: 3,
                  last_error: null,
                },
                detail: { deduped: 1, errors: [] },
              },
              request_id: "req_import_123",
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

  it("renders import summary", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/import/123"]}>
          <Routes>
            <Route path="/admin/import/:id" element={<ImportDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Import #123")).toBeInTheDocument();
    expect(await screen.findByText("request_id: req_import_123")).toBeInTheDocument();
    expect(await screen.findByText("manual")).toBeInTheDocument();
    expect(await screen.findByText("import_images")).toBeInTheDocument();
  });
});

