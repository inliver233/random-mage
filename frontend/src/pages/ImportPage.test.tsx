import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import { ImportPage } from "./ImportPage";

describe("ImportPage", () => {
  it("renders", () => {
    render(<ImportPage />);
    expect(screen.getByText("Import")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /导\s*入/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("One URL per line")).toBeInTheDocument();
  });
});
