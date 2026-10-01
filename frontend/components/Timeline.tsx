"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";
import { buildTimeline, TimelineSection } from "@/lib/dates";
import Link from "next/link";

// A year is a precise answer, not an approximate one. Only a decade or a range
// claims less than it sounds like it does.
function isApproximate(memory: Memory): boolean {
  return (
    memory.date_precision === "decade" || memory.date_precision === "range"
  );
}

// The memory's own time, for the row. An exact date is the point of the row now;
// a coarser memory shows its own wording when it says more than the heading.
function rowDate(memory: Memory, heading: string): string | null {
  if (memory.event_date && memory.date_precision === "exact") {
    return new Date(memory.event_date).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  const label = memory.date_label?.trim();
  if (label && label.toLowerCase() !== heading.trim().toLowerCase()) {
    return label;
  }
  if (isApproximate(memory)) return "Approximate";
  return null;
}

function MemoryRows({
  items,
  heading,
}: {
  items: Memory[];
  heading: string;
}) {
  return (
    <ul className="space-y-2">
      {items.map((memory) => {
        const date = rowDate(memory, heading);
        return (
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
              {date && (
                <span className="stamp text-flash">{date}</span>
              )}
              {memory.people?.length ? (
                <span className="stamp text-ink-muted border border-dashed border-line rounded-sm px-1.5 py-0.5">
                  {memory.people.join(", ")}
                </span>
              ) : null}
              {memory.location ? (
                <span className="stamp text-ink-muted border border-dashed border-line rounded-sm px-1.5 py-0.5">
                  {memory.location}
                </span>
              ) : null}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Section<T extends Memory>({
  section,
  first,
}: {
  section: TimelineSection<T>;
  first: boolean;
}) {
  return (
    <section className="relative pl-7 scroll-mt-4">
      <div
        className={`absolute -left-[7px] top-1.5 w-3 h-3 rounded-full ring-4 ring-bg ${
          first ? "bg-flash" : "bg-ink-faint"
        }`}
      />
      <h2 className="text-lg mb-3">{section.heading}</h2>

      {section.loose.length > 0 && (
        <MemoryRows items={section.loose} heading={section.heading} />
      )}

      {section.months.map((month) => (
        <div key={month.period.key} className="mt-4">
          <h3 className="stamp text-ink-muted mb-2">{month.period.heading}</h3>
          <MemoryRows items={month.memories} heading={month.period.heading} />
        </div>
      ))}
    </section>
  );
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

  const sections = buildTimeline(memories);

  return (
    <div className="max-w-3xl">
      <h1 className="text-3xl font-bold mb-6">Timeline</h1>
      {error && <p className="text-coral">{error}</p>}

      <div className="border-l-2 border-dotted border-line ml-3 space-y-10">
        {sections.map((section, index) => (
          <Section
            key={`${section.kind}-${section.heading}`}
            section={section}
            first={index === 0}
          />
        ))}
        {memories.length === 0 && !error && (
          <p className="text-ink-muted pl-7">No memories yet.</p>
        )}
      </div>
    </div>
  );
}
