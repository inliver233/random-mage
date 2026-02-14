import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlaygroundPage } from "./PlaygroundPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("PlaygroundPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/random") && url.includes("format=json")) {
          return new Response(
            JSON.stringify({ ok: true, request_id: "req_play", data: { urls: { proxy: "/i/1.jpg" } } }),
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

  it("runs and shows request_id", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/random"]}>
          <Routes>
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("随机接口调试")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始请求" }));
    expect(await screen.findByText(/请求ID:\s*req_play/)).toBeInTheDocument();
  });
});
