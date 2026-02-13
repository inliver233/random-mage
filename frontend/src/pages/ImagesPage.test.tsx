import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImagesPage } from "./ImagesPage";

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ImagesPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/images?limit=50&r18=2")) {
          return new Response(
            JSON.stringify({
              ok: true,
              items: [
                {
                  id: "1",
                  illust_id: "111",
                  page_index: 0,
                  ext: "jpg",
                  width: 100,
                  height: 200,
                  x_restrict: 0,
                  ai_type: 1,
                  user: { id: "9", name: "u" },
                  title: "t",
                  created_at_pixiv: "2020-01-01T00:00:00Z",
                },
              ],
              next_cursor: "",
              request_id: "req_images",
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
        <ImagesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Images")).toBeInTheDocument();
    expect(await screen.findByText("111")).toBeInTheDocument();
    expect(await screen.findByText(/request_id:\s*req_images/)).toBeInTheDocument();
  });
});
