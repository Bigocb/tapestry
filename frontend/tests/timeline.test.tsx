import { render, screen, within } from "@testing-library/react";
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

  it("shows the exact date, and who and where, rather than a clock time", async () => {
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

    // The exact date is the point of the row now.
    expect(await screen.findByText(/Mar 16, 1995/)).toBeInTheDocument();
    expect(screen.getByText(/Dawn/)).toBeInTheDocument();
    expect(screen.getByText(/Raleigh/)).toBeInTheDocument();
    // 12:00 AM is the parse default, not a time anyone recorded.
    expect(screen.queryByText(/12:00/)).not.toBeInTheDocument();
  });

  it("nests a month under its year", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        id: "m1",
        title: "One",
        event_date: "2024-11-28T00:00:00",
        date_precision: "exact",
      }),
      memory({
        id: "m2",
        title: "Two",
        event_date: "2024-08-03T00:00:00",
        date_precision: "exact",
      }),
    ]);

    render(<Timeline />);
    await screen.findByText("One");

    expect(screen.getByRole("heading", { level: 2, name: "2024" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "November 2024" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "August 2024" })
    ).toBeInTheDocument();
  });

  it("puts a year-only memory under the year, before the months", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        id: "m1",
        title: "Somewhere in the year",
        event_date: "2024-01-01T00:00:00",
        date_precision: "year",
      }),
      memory({
        id: "m2",
        title: "A day",
        event_date: "2024-11-28T00:00:00",
        date_precision: "exact",
      }),
    ]);

    render(<Timeline />);
    const year = (await screen.findByRole("heading", {
      level: 2,
      name: "2024",
    })).parentElement as HTMLElement;

    const headings = within(year).getAllByRole("heading");
    // The year heading, then the memory title link, is loose; the month is a
    // level-3 heading that must come after.
    expect(headings[0]).toHaveTextContent("2024");
    const month = within(year).getByRole("heading", {
      level: 3,
      name: "November 2024",
    });
    const loose = within(year).getByText("Somewhere in the year");
    expect(
      loose.compareDocumentPosition(month) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
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

  it("puts undated labels in a section after the dated years", async () => {
    vi.mocked(api.getTimeline).mockResolvedValue([
      memory({
        id: "m1",
        title: "A day",
        event_date: "2024-11-28T00:00:00",
        date_precision: "exact",
      }),
      memory({
        id: "m2",
        title: "No idea when",
        date_label: "Middle school",
        event_date: null,
      }),
    ]);

    render(<Timeline />);
    const year = await screen.findByRole("heading", { level: 2, name: "2024" });
    const sometime = screen.getByRole("heading", {
      level: 2,
      name: "Middle school",
    });

    expect(
      year.compareDocumentPosition(sometime) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
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
