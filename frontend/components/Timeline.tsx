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
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Timeline</h1>
      {error && <p className="text-red-600">{error}</p>}

      {groupOrder.length > 1 && (
        <nav className="mb-6 flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {groupOrder.map((key) => (
            <a
              key={key}
              href={`#period-${slug(key)}`}
              className="text-indigo-700 underline"
            >
              {timelineGroupHeading(byDate[key])}
            </a>
          ))}
        </nav>
      )}
      <div className="border-l-2 border-indigo-200 ml-3 space-y-6">
        {groupOrder.map((key) => {
          const items = byDate[key];
          const heading = timelineGroupHeading(items);

          return (
            <div
              key={key}
              id={`period-${slug(key)}`}
              className="relative pl-6 scroll-mt-4"
            >
              <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-indigo-600 border-2 border-white"></div>
              <h2 className="font-semibold text-lg mb-2">{heading}</h2>
              <ul className="space-y-2">
                {items.map((memory) => (
                  <li key={memory.id} className="bg-white border rounded p-3">
                    <Link
                      href={`/memories/${memory.id}`}
                      className="font-medium hover:text-indigo-600"
                    >
                      {memory.title || memory.summary || memory.raw_input}
                    </Link>
                    <p className="text-sm text-gray-500 flex flex-wrap items-center gap-x-2">
                      {rowDetail(memory, heading).map((bit) => (
                        <span key={bit}>{bit}</span>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {memories.length === 0 && !error && <p>No memories yet.</p>}
      </div>
    </div>
  );
}