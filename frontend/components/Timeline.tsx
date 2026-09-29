"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";
import { timelineGroupHeading, timelineGroupKey } from "@/lib/dates";
import Link from "next/link";

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

  const isFuzzy = (memory: Memory) =>
    Boolean(memory.date_label) ||
    memory.date_precision === "decade" ||
    memory.date_precision === "range" ||
    memory.date_precision === "year";

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Timeline</h1>
      {error && <p className="text-red-600">{error}</p>}
      <div className="border-l-2 border-indigo-200 ml-3 space-y-6">
        {groupOrder.map((key) => {
          const items = byDate[key];
          const heading = timelineGroupHeading(items);

          return (
            <div key={key} className="relative pl-6">
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
                    <p className="text-sm text-gray-500">
                      {isFuzzy(memory)
                        ? memory.date_label &&
                          memory.date_label.trim().toLowerCase() !==
                            heading.trim().toLowerCase()
                          ? memory.date_label
                          : "Approximate"
                        : memory.event_date
                          ? new Date(memory.event_date).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : new Date(memory.created_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
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