"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";
import { timelineGroupHeading, timelineGroupKey } from "@/lib/dates";
import Link from "next/link";

// Group keys are normalised labels and dates, so they can hold spaces and
// commas; an id wants neither.
function slug(key: string): string {
  return key.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "");
}

export function Timeline() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getTimeline({ limit: 200, order: "desc" })
      .then((data) => {
        const items: Memory[] = data.items || data.memories || data || [];
        setMemories(items);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load memories")
      );
  }, []);

  // Group by period: two memories belong in the same section when they share a
  // fuzzy label ("Middle school" and "Middle school (1987-1990)" merge) or a
  // date. Exact-date memories still get one section per day.
  const byDate = memories.reduce(
    (acc: Record<string, Memory[]>, memory) => {
      const key = timelineGroupKey(memory);
      if (!acc[key]) acc[key] = [];
      acc[key].push(memory);
      return acc;
    },
    {}
  );

  // Show groups in the order the timeline returned them (chronological), so
  // labelled periods appear wherever their anchor dates place them.
  const groupOrder: string[] = [];
  const seen = new Set<string>();
  for (const memory of memories) {
    const key = timelineGroupKey(memory);
    if (!seen.has(key)) {
      seen.add(key);
      groupOrder.push(key);
    }
  }

  // A year is a precise answer, not an approximate one. Only a decade or a
  // range claims less than it sounds like it does.
  const isApproximate = (memory: Memory) =>
    memory.date_precision === "decade" || memory.date_precision === "range";

  const rowDetail = (memory: Memory, heading: string): string[] => {
    const bits: string[] = [];

    // A memory's own wording is worth a line when it says more than the
    // heading it sits under.
    const label = memory.date_label?.trim();
    if (label && label.toLowerCase() !== heading.trim().toLowerCase()) {
      bits.push(label);
    } else if (isApproximate(memory)) {
      bits.push("Approximate");
    }

    // Who and where, rather than a clock time. An exact date parsed from text
    // carries midnight as its default, which is not information about anything.
    if (memory.people?.length) bits.push(memory.people.join(", "));
    if (memory.location) bits.push(memory.location);

    return bits;
  };

  return (
    <div className="max-w-3xl">
      <h1 className="text-3xl font-bold mb-6">Timeline</h1>
      {error && <p className="text-coral">{error}</p>}

      {groupOrder.length > 1 && (
        <nav className="mb-8 flex flex-wrap gap-x-4 gap-y-1">
          {groupOrder.map((key) => (
            <a
              key={key}
              href={`#period-${slug(key)}`}
              className="stamp text-flash hover:text-flash-dark border-b border-dotted border-flash/40"
            >
              {timelineGroupHeading(byDate[key])}
            </a>
          ))}
        </nav>
      )}
      <div className="border-l-2 border-dotted border-line ml-3 space-y-8">
        {groupOrder.map((key, idx) => {
          const items = byDate[key];
          const heading = timelineGroupHeading(items);

          return (
            <div
              key={key}
              id={`period-${slug(key)}`}
              className="relative pl-7 scroll-mt-4"
            >
              <div
                className={`absolute -left-[7px] top-1.5 w-3 h-3 rounded-full ring-4 ring-bg ${
                  idx === 0 ? "bg-flash" : "bg-ink-faint"
                }`}
              ></div>
              <h2 className="text-lg mb-3">{heading}</h2>
              <ul className="space-y-2">
                {items.map((memory) => (
                  <li
                    key={memory.id}
                    className="bg-surface border border-line rounded-lg p-3 hover:border-flash transition"
                  >
                    <Link
                      href={`/memories/${memory.id}`}
                      className="font-medium text-ink hover:text-flash"
                    >
                      {memory.title || memory.summary || memory.raw_input}
                    </Link>
                    <p className="flex flex-wrap items-center gap-2 mt-1.5">
                      {rowDetail(memory, heading).map((bit) => (
                        <span
                          key={bit}
                          className="stamp text-ink-muted border border-dashed border-line rounded-sm px-1.5 py-0.5"
                        >
                          {bit}
                        </span>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {memories.length === 0 && !error && (
          <p className="text-ink-muted">No memories yet.</p>
        )}
      </div>
    </div>
  );
}