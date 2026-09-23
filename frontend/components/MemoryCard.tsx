"use client";

import Link from "next/link";

export interface Memory {
  id: string;
  raw_input: string;
  title?: string;
  summary?: string;
  state?: string;
  processing_state?: string;
  created_at: string;
  event_date?: string;
  mood?: string;
  tags?: string[];
  people?: string[];
  location?: string;
  importance_level?: number;
  needs_review?: boolean;
  review_reason?: string;
}

export function MemoryCard({
  memory,
  onDelete,
}: {
  memory: Memory;
  onDelete?: (id: string) => void;
}) {
  return (
    <div className="border rounded p-4 bg-white shadow-sm hover:shadow transition">
      <div className="flex justify-between items-start">
        <Link href={`/memories/${memory.id}`} className="font-semibold text-lg">
          {memory.title || memory.raw_input}
        </Link>
        {onDelete && (
          <button
            onClick={() => onDelete(memory.id)}
            className="text-red-600 text-sm hover:underline"
          >
            Delete
          </button>
        )}
      </div>
      <p className="text-sm text-gray-500 mt-1">
        {memory.event_date
          ? new Date(memory.event_date).toLocaleDateString()
          : new Date(memory.created_at).toLocaleDateString()}
        {" "}
        · {memory.processing_state}
      </p>
      <p className="text-gray-700 mt-2 line-clamp-3">
        {memory.summary || memory.raw_input}
      </p>
      <div className="flex flex-wrap gap-2 mt-3">
        {memory.mood && (
          <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
            {memory.mood}
          </span>
        )}
        {memory.location && (
          <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
            {memory.location}
          </span>
        )}
        {memory.tags?.map((tag) => (
          <span
            key={tag}
            className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded"
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}
