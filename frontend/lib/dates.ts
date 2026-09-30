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

/**
 * Section key for grouping memories on the timeline.
 *
 * Labels are compared case- and whitespace-insensitively, and a trailing
 * "(1987-1990)" range is dropped, so "Middle School", "Middle school" and
 * "Middle school (1987-1990)" all land in one section. Without this they
 * rendered as adjacent headings differing only in capitalisation.
 *
 * Unlabelled fuzzy memories get a key derived from their precision, so the
 * 1980s section collects every decade memory whether or not it was labelled,
 * and a range groups by its year span rather than by its raw start date.
 */
export function timelineGroupKey(memory: DatedMemory): string {
  if (memory.date_label) {
    const base = memory.date_label
      .replace(/\s*\([^)]*\)\s*$/, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
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

  // No date to key by, and a telling segment has no capture time at all.
  return memory.created_at
    ? new Date(memory.created_at).toLocaleDateString()
    : "";
}

/**
 * Pick the heading to show for a group.
 *
 * Prefers a user/agent label (the human wording) over a derived date key, and
 * when several label spellings are present chooses the most common one so the
 * heading is stable rather than depending on sort order.
 */
export function timelineGroupHeading(items: DatedMemory[]): string {
  const labels = items
    .map((m) => (m.date_label || "").trim())
    .filter((label) => label.length > 0);

  if (labels.length > 0) {
    const counts = new Map<string, number>();
    for (const label of labels) {
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    // Most frequent wins; ties resolve to the first seen (insertion order).
    let best = labels[0];
    for (const [label, count] of counts) {
      if (count > (counts.get(best) || 0)) best = label;
    }
    return best;
  }

  const first = items[0];
  if (first.event_date) {
    const start = new Date(first.event_date);
    switch (first.date_precision) {
      case "decade":
        return `${Math.floor(start.getFullYear() / 10) * 10}s`;
      case "year":
        return String(start.getFullYear());
      case "range":
        return first.event_date_end
          ? `${start.getFullYear()}–${new Date(first.event_date_end).getFullYear()}`
          : `${Math.floor(start.getFullYear() / 10) * 10}s`;
      default:
        return start.toLocaleDateString();
    }
  }
  // Memories always carry a capture time; a caller without one gets no
  // heading rather than a date built out of undefined.
  return first.created_at
    ? new Date(first.created_at).toLocaleDateString()
    : "";
}

/** Whether the memory has any time information beyond its capture time. */
export function hasEventTime(memory: DatedMemory): boolean {
  return Boolean(
    memory.event_date || memory.date_label || memory.date_precision === "range"
  );
}
