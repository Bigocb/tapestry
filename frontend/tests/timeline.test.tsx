import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Timeline } from "@/components/Timeline";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { getTimeline: vi.fn() },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

function memory(overrides: Record<string, unknown> = {}) {
  return {
    id: "m1",
    raw_input: "some text",
    title: "A memory",
    created_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

describe("Timeline rows", () => {
  beforeEach(() => {
    vi.mocked(api.getTimeline).mockResolvedValue([]);
  });

  it("shows who and where rather than a clock time", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        title: "Lunch",
        event_date: "1995-03-16T00:00:00",
        date_precision: "exact",
        people: ["Dawn"],
        location: "Raleigh",
      }),
    ]);

    render(<Timeline />);

    expect(await screen.findByText(/Dawn/)).toBeInTheDocument();
    expect(screen.getByText(/Raleigh/)).toBeInTheDocument();
    // 12:00 AM is the parse default, not a time anyone recorded.
    expect(screen.queryByText(/12:00/)).not.toBeInTheDocument();
  });

  it("does not call a year-precise memory approximate", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        title: "Born",
        event_date: "1976-01-01T00:00:00",
        date_precision: "year",
      }),
    ]);

    render(<Timeline />);
    await screen.findByText("Born");

    // 1976 is year-precise, not approximate — only decades and ranges are.
    expect(screen.queryByText(/approximate/i)).not.toBeInTheDocument();
  });

  it("does call a decade approximate", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        title: "The eighties",
        event_date: "1980-01-01T00:00:00",
        date_precision: "decade",
      }),
    ]);

    render(<Timeline />);
    await screen.findByText("The eighties");

    expect(screen.getByText(/approximate/i)).toBeInTheDocument();
  });

  it("offers a way to jump to a period", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        id: "m1",
        title: "One",
        event_date: "1976-01-01T00:00:00",
        date_precision: "year",
      }),
      memory({
        id: "m2",
        title: "Two",
        event_date: "2024-01-01T00:00:00",
        date_precision: "year",
      }),
    ]);

    render(<Timeline />);
    await screen.findByText("One");

    // Thirty-four thin years is a long scroll; finding 1976 should not mean
    // passing twenty of them.
    const jump = screen.getByRole("link", { name: "1976" });
    expect(jump).toHaveAttribute("href", "#period-1976");
  });

  it("puts qualified decades under one heading", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        id: "m1",
        title: "One",
        date_label: "1980s",
        event_date: "1980-01-01T00:00:00",
        date_precision: "decade",
      }),
      memory({
        id: "m2",
        title: "Two",
        date_label: "early 1980s",
        event_date: "1980-01-01T00:00:00",
        date_precision: "decade",
      }),
    ]);

    render(<Timeline />);

    // One section, not two — and the row keeps its own wording.
    expect(await screen.findAllByRole("heading", { level: 2 })).toHaveLength(1);
    expect(screen.getByText("early 1980s")).toBeInTheDocument();
  });
});
