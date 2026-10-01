"use client";

export interface DatedMemory {
  // Optional because a telling segment has no capture time of its own, and
  // nullable because a segment's dates are explicitly cleared, not just absent.
  created_at?: string;
  event_date?: string | null;
  date_precision?: string | null;
  event_date_end?: string | null;
  date_label?: string | null;
}

/**
 * Human label for a memory's time.
 *
 * Fuzzy periods are shown using the user's own wording ("Middle school",
 * "the 80s") instead of a fake exact date, so "sometime in the 80s" never
 * masquerades as 1 Jan 1980.
 */
export function formatMemoryDate(memory: DatedMemory): string {
  if (memory.date_label) {
    return memory.date_label;
  }

  if (memory.event_date) {
    const start = new Date(memory.event_date);

    switch (memory.date_precision) {
      case "decade":
      case "year":
        return String(start.getFullYear());
      case "month":
        return start.toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
        });
      case "range": {
        if (!memory.event_date_end) {
          return String(start.getFullYear());
        }
        const end = new Date(memory.event_date_end);
        return `${start.getFullYear()}–${end.getFullYear()}`;
      }
      default:
        return start.toLocaleDateString();
    }
  }

  // No event date: fall back to when it was captured, if that is even known.
  // Callers pass "" on rather than inventing a date for an undated draft.
  return memory.created_at
    ? new Date(memory.created_at).toLocaleDateString()
    : "";
}

/** Where a period sits on the timeline, and what kind of thing it is. */
export interface TimelinePeriod {
  kind: "year" | "month" | "decade" | "range" | "label";
  key: string;
  heading: string;
  /** Descending sort puts the newest first and Sometime (empty) last. */
  sort: string;
  /** For a month period, the year it belongs to; null otherwise. */
  group: string | null;
}

export interface TimelineMonth<T extends DatedMemory = DatedMemory> {
  period: TimelinePeriod;
  memories: T[];
}

export interface TimelineSection<T extends DatedMemory = DatedMemory> {
  kind: TimelinePeriod["kind"];
  heading: string;
  sort: string;
  /** Rows shown directly under the heading — a year's year-only memories, or
   *  the members of a decade, range or named period. */
  loose: T[];
  /** Month sub-sections, newest first. Empty unless this is a year. */
  months: TimelineMonth<T>[];
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function decadeStart(year: number): number {
  return Math.floor(year / 10) * 10;
}

/**
 * The decade a label names, if it names one.
 *
 * "early 1980s", "late 1980s" and "the 1980s" are one period seen from
 * different angles, so they collapse to the same decade. A bare year is not a
 * decade, so "1994" is left alone.
 */
function decadeOfLabel(label: string): number | null {
  const match = label.match(/\b((?:1[89]|20)?\d0)'?s\b/);
  if (!match) return null;
  const digits = match[1];
  if (digits.length === 4) return decadeStart(Number(digits));
  const value = Number(digits);
  return decadeStart((value < 30 ? 2000 : 1900) + value);
}

function yearPeriod(year: number): TimelinePeriod {
  const key = String(year);
  return { kind: "year", key, heading: key, sort: `${key}-01-01`, group: null };
}

function monthPeriod(year: number, month: number): TimelinePeriod {
  const key = `${year}-${String(month).padStart(2, "0")}`;
  return {
    kind: "month",
    key,
    heading: `${MONTHS[month - 1]} ${year}`,
    sort: key,
    group: String(year),
  };
}

function decadePeriod(startYear: number): TimelinePeriod {
  return {
    kind: "decade",
    key: `${startYear}s`,
    heading: `${startYear}s`,
    sort: `${startYear}-01-01`,
    group: null,
  };
}

function rangePeriod(startYear: number, endYear: number): TimelinePeriod {
  return {
    kind: "range",
    key: `${startYear}-${endYear}`,
    heading: `${startYear}–${endYear}`,
    sort: `${startYear}-01-01`,
    group: null,
  };
}

/**
 * A period named in words ("Middle school", "the Disney trip"), optionally with
 * years attached.
 *
 * Keyed on the words, not the years, so "Middle school" and "Middle school
 * (1987-1990)" are one period written two ways rather than a heading each. The
 * heading shown is the most common wording, chosen in buildTimeline.
 */
function namedPeriod(base: string, startYear: number | null): TimelinePeriod {
  const key = base.replace(/\s+/g, " ").trim().toLowerCase() || "sometime";
  return {
    kind: "label",
    key,
    heading: base || "Sometime",
    sort: startYear !== null ? `${startYear}-01-01` : "",
    group: null,
  };
}

/** Does the label hold a name, as opposed to only years and punctuation? */
function hasNameWord(label: string): boolean {
  return /[A-Za-z]/.test(
    label.replace(/\b(?:18|19|20)\d{2}\b/g, "").replace(/\([^)]*\)/g, "")
  );
}

function firstYearIn(label: string): number | null {
  const match = label.match(/\b(?:18|19|20)\d{2}\b/);
  return match ? Number(match[0]) : null;
}

const MONTH_INDEX: Record<string, number> = {
  january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
  july: 7, august: 8, september: 9, october: 10, november: 11, december: 12,
};

/**
 * A period a label names outright: "September 2000", "1988", "the 1980s",
 * "1987-1990".
 *
 * The label is the most reliable thing a memory carries about its own date. The
 * precision column is the model's guess and is routinely wrong — "September
 * 2000" stored as a range, "1988" as unknown — so the wording is read first and
 * the precision is only a fallback.
 */
function parseLabelPeriod(label: string): TimelinePeriod | null {
  const text = label.trim();
  if (!text) return null;

  const range = text.match(
    /^((?:18|19|20)\d{2})\s*[-–—]\s*((?:18|19|20)\d{2})$/
  );
  if (range) return rangePeriod(Number(range[1]), Number(range[2]));

  // A whole date written out, however it was stored. The month is what the
  // timeline groups by; the day is shown on the row.
  const written = text.match(
    /^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:18|19|20)\d{2})$/
  );
  if (written) {
    const index = MONTH_INDEX[written[1].toLowerCase()];
    if (index) return monthPeriod(Number(written[3]), index);
  }
  const numeric = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (numeric) {
    return monthPeriod(Number(numeric[3]), Number(numeric[1]));
  }
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) {
    return monthPeriod(Number(iso[1]), Number(iso[2]));
  }

  const month = text.match(/^([A-Za-z]+)\s+((?:18|19|20)\d{2})$/);
  if (month) {
    const index = MONTH_INDEX[month[1].toLowerCase()];
    if (index) return monthPeriod(Number(month[2]), index);
  }

  const decade = decadeOfLabel(text);
  if (decade !== null) return decadePeriod(decade);

  const year = text.match(/^((?:18|19|20)\d{2})$/);
  if (year) return yearPeriod(Number(year[1]));

  return null;
}

export function periodOf(memory: DatedMemory): TimelinePeriod {
  const label = (memory.date_label ?? "").trim();
  const base = label.replace(/\s*\([^)]*\)\s*$/, "").trim();
  const precision = memory.date_precision ?? null;
  const date = memory.event_date ? new Date(memory.event_date) : null;

  // 1. The wording, when it names a period.
  const fromLabel = parseLabelPeriod(label);
  if (fromLabel) return fromLabel;

  // 2. A name that is not a period ("Middle school", "The Disney trip"). Its
  //    years, if any, place it among the years rather than in Sometime.
  if (label && hasNameWord(label)) return namedPeriod(base, firstYearIn(label));

  // 3. The date itself. A day other than the 1st is a real day, so the memory
  //    belongs in that month whatever the precision says — a decade stored as
  //    "1988-09-17" is a day, not a decade.
  if (date) {
    const year = date.getFullYear();
    if (date.getDate() !== 1) return monthPeriod(year, date.getMonth() + 1);

    // A 1st is a placeholder: month, year, decade and range all store one.
    if (precision === "range") {
      const end = memory.event_date_end ? new Date(memory.event_date_end) : null;
      if (end && end.getFullYear() > year) {
        return rangePeriod(year, end.getFullYear());
      }
      return decadePeriod(decadeStart(year));
    }
    if (precision === "decade") return decadePeriod(decadeStart(year));
    if (precision === "month" || precision === "exact") {
      return monthPeriod(year, date.getMonth() + 1);
    }
    return yearPeriod(year);
  }

  // 4. A label with no period and no date: a real answer, just not a dated one.
  if (label) return namedPeriod(base, null);

  // 5. Nothing but a capture time. The timeline normally hides these; a caller
  //    who passes one through gets a year rather than an empty heading.
  if (memory.created_at) {
    return yearPeriod(new Date(memory.created_at).getFullYear());
  }
  return yearPeriod(0);
}

function mostCommonLabel(items: DatedMemory[]): string {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = (item.date_label ?? "").trim();
    if (!label) continue;
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  let best = "";
  for (const [label, count] of counts) {
    if (count > (counts.get(best) || 0)) best = label;
  }
  return best;
}

/**
 * Build the timeline tree.
 *
 * Year sections (newest first), each holding its year-only memories first and
 * then its months (newest first). Decades, ranges and named periods are their
 * own markers, ordered among the years by the year they start; a named period
 * with no year falls to the Sometime section at the very end.
 */
export function buildTimeline<T extends DatedMemory>(
  memories: T[]
): TimelineSection<T>[] {
  const years = new Map<string, TimelineSection<T>>();
  const others = new Map<string, TimelineSection<T>>();

  const yearSection = (year: number): TimelineSection<T> => {
    const key = String(year);
    let section = years.get(key);
    if (!section) {
      section = {
        kind: "year",
        heading: key,
        sort: `${key}-01-01`,
        loose: [],
        months: [],
      };
      years.set(key, section);
    }
    return section;
  };

  for (const memory of memories) {
    const period = periodOf(memory);

    if (period.kind === "year") {
      yearSection(Number(period.key)).loose.push(memory);
      continue;
    }
    if (period.kind === "month") {
      const section = yearSection(Number(period.group));
      let month = section.months.find((m) => m.period.key === period.key);
      if (!month) {
        month = { period, memories: [] };
        section.months.push(month);
      }
      month.memories.push(memory);
      continue;
    }

    let section = others.get(period.key);
    if (!section) {
      section = {
        kind: period.kind,
        heading: period.heading,
        sort: period.sort,
        loose: [],
        months: [],
      };
      others.set(period.key, section);
    } else if (!section.sort && period.sort) {
      // A named period met first without years, then with them, takes the year
      // so it is placed by it rather than left in Sometime.
      section.sort = period.sort;
    }
    section.loose.push(memory);
  }

  for (const section of years.values()) {
    section.months.sort((a, b) => b.period.key.localeCompare(a.period.key));
  }
  for (const [key, section] of others) {
    if (section.kind === "label") {
      section.heading = mostCommonLabel(section.loose) || key;
    }
  }

  const sections = [...years.values(), ...others.values()];
  sections.sort((a, b) => b.sort.localeCompare(a.sort));
  return sections;
}

/** Whether the memory has any time information beyond its capture time. */
export function hasEventTime(memory: DatedMemory): boolean {
  return Boolean(
    memory.event_date || memory.date_label || memory.date_precision === "range"
  );
}
