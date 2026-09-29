"use client";

export interface DatedMemory {
  created_at: string;
  event_date?: string;
  date_precision?: string;
  event_date_end?: string;
  date_label?: string;
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

  // No event date: fall back to when it was captured.
  return new Date(memory.created_at).toLocaleDateString();
}

/**
 * Section key for grouping memories on the timeline.
 *
 * Two memories describe the same period when their labels match after dropping
 * a trailing "(1987-1990)" range, so "Middle school" and
 * "Middle school (1987-1990)" land in one section rather than splitting.
 *
 * Unlabeled fuzzy memories get a key derived from their precision, so the
 * 1980s section collects every decade memory whether or not it was labelled,
 * and a range groups by its year span rather than by its raw start date.
 */
export function timelineGroupKey(memory: DatedMemory): string {
  if (memory.date_label) {
    // Strip a trailing parenthetical so labelled variants merge.
    const base = memory.date_label.replace(/\s*\([^)]*\)\s*$/, "").trim();
    if (base) return base;
  }

  if (memory.event_date) {
    const start = new Date(memory.event_date);
    switch (memory.date_precision) {
      case "decade": {
        // "1980s" collects labelled and unlabelled decade memories alike.
        const decade = Math.floor(start.getFullYear() / 10) * 10;
        return `${decade}s`;
      }
      case "year":
        return String(start.getFullYear());
      case "range": {
        const end = memory.event_date_end
          ? new Date(memory.event_date_end)
          : null;
        // An open-ended range groups by its decade so it still clusters.
        return end
          ? `${start.getFullYear()}-${end.getFullYear()}`
          : `${Math.floor(start.getFullYear() / 10) * 10}s`;
      }
      default:
        return start.toLocaleDateString();
    }
  }

  return new Date(memory.created_at).toLocaleDateString();
}

/** Whether the memory has any time information beyond its capture time. */
export function hasEventTime(memory: DatedMemory): boolean {
  return Boolean(
    memory.event_date || memory.date_label || memory.date_precision === "range"
  );
}
