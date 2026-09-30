import { describe, expect, it } from "vitest";

import { timelineGroupKey } from "@/lib/dates";

function dated(overrides: Record<string, unknown> = {}) {
  return { created_at: "2026-01-01T00:00:00", ...overrides };
}

describe("timelineGroupKey", () => {
  it("groups a qualified decade with its base", () => {
    // "early 1980s" and "late 1980s" are the same decade seen more narrowly,
    // not different periods. Three headings for one decade was the bug.
    const base = timelineGroupKey(dated({ date_label: "1980s" }));

    expect(timelineGroupKey(dated({ date_label: "early 1980s" }))).toBe(base);
    expect(timelineGroupKey(dated({ date_label: "late 1980s" }))).toBe(base);
    expect(timelineGroupKey(dated({ date_label: "the 1980s" }))).toBe(base);
  });

  it("groups the parenthetical spelling with the plain one", () => {
    expect(
      timelineGroupKey(dated({ date_label: "Middle school (1987-1990)" }))
    ).toBe(timelineGroupKey(dated({ date_label: "Middle school" })));
  });

  it("leaves a label with no period in it alone", () => {
    expect(timelineGroupKey(dated({ date_label: "Middle school" }))).toBe(
      "middle school"
    );
  });

  it("does not collapse a bare year into a decade", () => {
    // 1994 is a year, not "the 1990s" — collapsing it would lose precision.
    expect(timelineGroupKey(dated({ date_label: "1994" }))).toBe("1994");
  });

  it("falls back to the decade for an unlabelled decade memory", () => {
    expect(
      timelineGroupKey(
        dated({ event_date: "1987-01-01T00:00:00", date_precision: "decade" })
      )
    ).toBe("1980s");
  });
});
