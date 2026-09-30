import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasEventTime } from "@/lib/dates";

describe("frontend test harness", () => {
  it("renders a component and supports jest-dom matchers", () => {
    render(<p>Hello Tapestry</p>);
    expect(screen.getByText("Hello Tapestry")).toBeInTheDocument();
  });

  it("resolves the @/ path alias", () => {
    expect(typeof hasEventTime).toBe("function");
  });
});
