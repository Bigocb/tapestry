"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";
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

  const groupDate = (memory: Memory) =>
    new Date(memory.event_date || memory.created_at).toLocaleDateString();

  const byDate = memories.reduce(
    (acc: Record<string, Memory[]>, memory) => {
      const date = groupDate(memory);
      if (!acc[date]) acc[date] = [];
      acc[date].push(memory);
      return acc;
    },
    {}
  );

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Timeline</h1>
      {error && <p className="text-red-600">{error}</p>}
      <div className="border-l-2 border-indigo-200 ml-3 space-y-6">
        {Object.entries(byDate).map(([date, items]) => (
          <div key={date} className="relative pl-6">
            <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-indigo-600 border-2 border-white"></div>
            <h2 className="font-semibold text-lg mb-2">{date}</h2>
            <ul className="space-y-2">
              {items.map((memory) => (
                <li key={memory.id} className="bg-white border rounded p-3">
                  <Link
                    href={`/memories/${memory.id}`}
                    className="font-medium hover:text-indigo-600"
                  >
                    {memory.title || memory.refined_text || memory.raw_input}
                  </Link>
                  <p className="text-sm text-gray-500">
                    {new Date(memory.event_date || memory.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {memories.length === 0 && !error && <p>No memories yet.</p>}
      </div>
    </div>
  );
}
