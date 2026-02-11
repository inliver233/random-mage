import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlaygroundPage } from "./PlaygroundPage";
import { TagsPage } from "./TagsPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("TagsPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/tags?limit=50")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [{ name: "tag1", translated_name: "t1", count_images: 5 }],
              next_cursor: "",
              request_id: "req_tags",
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
        <MemoryRouter initialEntries={["/admin/tags"]}>
          <Routes>
            <Route path="/admin/tags" element={<TagsPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tags")).toBeInTheDocument();
    expect(await screen.findByText("tag1")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_tags/)).toBeInTheDocument();
  });

  it("navigates to playground with included_tags prefill", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/tags"]}>
          <Routes>
            <Route path="/admin/tags" element={<TagsPage />} />
            <Route path="/admin/random" element={<PlaygroundPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("tag1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /从\s*该\s*标\s*签\s*随\s*机\s*一\s*张/ }));
    expect(await screen.findByText("Random Playground")).toBeInTheDocument();

    await waitFor(() => {
      const input = screen.getByLabelText(/Included tags/i) as HTMLInputElement;
      expect(input.value).toBe("tag1");
    });
  });
});
