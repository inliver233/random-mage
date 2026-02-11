import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TagsPage } from "./TagsPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("TagsPage", () => {
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
        <TagsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Tags")).toBeInTheDocument();
    expect(await screen.findByText("tag1")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_tags/)).toBeInTheDocument();
  });
});

