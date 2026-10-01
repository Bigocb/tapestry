import { describe, expect, it } from "vitest";

import { buildTimeline, periodOf } from "@/lib/dates";

function dated(overrides: Record<string, unknown> = {}) {
  return { created_at: "2026-01-01T00:00:00", ...overrides };
}

function exact(year: number, month: number, day: number) {
  const m = String(month).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return dated({
    event_date: `${year}-${m}-${d}T00:00:00`,
    date_precision: "exact",
  });
}

describe("periodOf", () => {
  it("places an exact date in its month", () => {
    const period = periodOf(exact(2024, 11, 28));

    expect(period.kind).toBe("month");
    expect(period.key).toBe("2024-11");
    expect(period.heading).toBe("November 2024");
    expect(period.group).toBe("2024");
  });

  it("places a month-precision memory in its month too", () => {
    const period = periodOf(
      dated({ event_date: "2024-11-01T00:00:00", date_precision: "month" })
    );

    expect(period.kind).toBe("month");
    expect(period.key).toBe("2024-11");
  });

  it("leaves a year-only memory on the year, with no month", () => {
    const period = periodOf(
      dated({ event_date: "1989-01-01T00:00:00", date_precision: "year" })
    );

    expect(period.kind).toBe("year");
    expect(period.key).toBe("1989");
  });

  it("groups a qualified decade with its base", () => {
    // "early 1980s", "late 1980s" and "the 1980s" are one decade, not three.
    const base = periodOf(dated({ date_label: "1980s" }));

    expect(periodOf(dated({ date_label: "early 1980s" })).key).toBe(base.key);
    expect(periodOf(dated({ date_label: "late 1980s" })).key).toBe(base.key);
    expect(periodOf(dated({ date_label: "the 1980s" })).key).toBe(base.key);
  });

  it("groups a named period written with or without its years", () => {
    expect(periodOf(dated({ date_label: "Middle school (1987-1990)" })).key).toBe(
      periodOf(dated({ date_label: "Middle school" })).key
    );
  });

  it("gives a named period with years a year to sort by", () => {
    const withYears = periodOf(dated({ date_label: "Middle school (1987-1990)" }));
    const without = periodOf(dated({ date_label: "Middle school" }));

    expect(withYears.sort).toBe("1987-01-01");
    // No year named: it belongs in Sometime, at the bottom.
    expect(without.sort).toBe("");
  });

  it("does not collapse a bare year into a decade", () => {
    expect(periodOf(dated({ date_label: "1994" })).key).not.toBe("1990s");
  });

  it("gives an open-ended range a decade rather than a second year", () => {
    const period = periodOf(
      dated({ event_date: "2021-07-01T00:00:00", date_precision: "range" })
    );

    expect(period.kind).toBe("decade");
    expect(period.key).toBe("2020s");
  });
});

describe("buildTimeline", () => {
  it("nests months under their year, newest first", () => {
    const sections = buildTimeline([
      exact(2024, 3, 5),
      exact(2024, 11, 28),
      exact(2024, 8, 3),
    ]);

    expect(sections).toHaveLength(1);
    expect(sections[0].heading).toBe("2024");
    expect(sections[0].months.map((m) => m.period.heading)).toEqual([
      "November 2024",
      "August 2024",
      "March 2024",
    ]);
  });

  it("keeps year-only memories before the months", () => {
    const sections = buildTimeline([
      exact(2024, 11, 28),
      dated({ event_date: "2024-01-01T00:00:00", date_precision: "year" }),
    ]);

    expect(sections[0].loose).toHaveLength(1);
    expect(sections[0].months).toHaveLength(1);
  });

  it("orders years newest first", () => {
    const sections = buildTimeline([
      exact(1976, 7, 29),
      exact(2024, 11, 28),
      exact(1994, 6, 1),
    ]);

    expect(sections.map((s) => s.heading)).toEqual(["2024", "1994", "1976"]);
  });

  it("puts undated labels in a Sometime section at the very end", () => {
    const sections = buildTimeline([
      exact(2024, 11, 28),
      dated({ date_label: "Middle school", event_date: null }),
    ]);

    const last = sections[sections.length - 1];
    expect(last.heading).toBe("Middle school");
    expect(last.sort).toBe("");
  });

  it("places a named period with years among the years, and undated last", () => {
    const sections = buildTimeline([
      exact(2024, 11, 28),
      dated({ date_label: "Middle school (1987-1990)" }),
      dated({ date_label: "The Disney trip", event_date: null }),
    ]);

    // 2024, then the 1987 period, then Sometime — not Sometime in the middle.
    expect(sections.map((s) => s.heading)).toEqual([
      "2024",
      "Middle school (1987-1990)",
      "The Disney trip",
    ]);
    expect(sections[2].sort).toBe("");
  });

  it("gives a decade its own marker between the years", () => {
    const sections = buildTimeline([
      exact(2024, 11, 28),
      dated({ event_date: "1980-01-01T00:00:00", date_precision: "decade" }),
      exact(1976, 7, 29),
    ]);

    expect(sections.map((s) => s.heading)).toEqual(["2024", "1980s", "1976"]);
  });

  it("shows the most common wording for a shared named period", () => {
    const sections = buildTimeline([
      dated({ date_label: "Middle school (1987-1990)" }),
      dated({ date_label: "Middle school (1987-1990)" }),
      dated({ date_label: "Middle school" }),
    ]);

    expect(sections).toHaveLength(1);
    expect(sections[0].heading).toBe("Middle school (1987-1990)");
  });
});
