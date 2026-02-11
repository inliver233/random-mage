import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ImportPage } from "./ImportPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ImportPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/admin/api/imports")) {
          return new Response(
            JSON.stringify({
              ok: true,
              import_id: "",
              job_id: "",
              accepted: 1,
              deduped: 0,
              errors: [],
              preview: [],
              request_id: "req_import",
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

  it("renders", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/import"]}>
          <Routes>
            <Route path="/admin/import" element={<ImportPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Import")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /导\s*入/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("One URL per line")).toBeInTheDocument();
  });

  it("submits import and shows request_id", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/import"]}>
          <Routes>
            <Route path="/admin/import" element={<ImportPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByPlaceholderText("One URL per line"), { target: { value: "https://example.com/1" } });
    fireEvent.click(screen.getByRole("button", { name: /导\s*入/ }));

    expect(await screen.findByText(/request_id:\s*req_import/)).toBeInTheDocument();
    expect(await screen.findByText(/accepted:\s*1/)).toBeInTheDocument();

    await waitFor(() => {
      const fetchMock = globalThis.fetch as unknown as { mock: { calls: unknown[][] } };
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/admin/api/imports"))).toBe(true);
    });
  });
});
