"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface ReviewMemory {
  id: string;
  raw_input: string;
  title?: string;
  summary?: string;
  created_at: string;
  needs_review?: boolean;
  review_reason?: string;
}

const REASON_LABELS: Record<string, string> = {
  missing_date: "No date found",
};

export function ReviewQueue() {
  const [items, setItems] = useState<ReviewMemory[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api
      .getReviewQueue(100, 0)
      .then((data) => {
        if (!active) return;
        setItems(data.items || []);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load review queue");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-2">Review queue</h1>
      <p className="text-sm text-ink-muted mb-6">
        Memories that need your attention. Set a date so they appear on your
        timeline.
      </p>

      {error && <p className="text-coral mb-4">{error}</p>}
      {loading && <p>Loading...</p>}

      {!loading && items.length === 0 && !error && (
        <p className="text-ink-muted">Nothing to review. You&apos;re all caught up.</p>
      )}

      <ul className="space-y-3">
        {items.map((memory) => (
          <li key={memory.id} className="border rounded p-4 bg-surface">
            <div className="flex justify-between items-start gap-4">
              <div>
                <Link
                  href={`/memories/${memory.id}`}
                  className="font-semibold hover:text-flash"
                >
                  {memory.title || memory.raw_input}
                </Link>
                <p className="text-sm text-ink-muted mt-1 line-clamp-2">
                  {memory.summary || memory.raw_input}
                </p>
                <p className="text-xs text-ink-faint mt-2">
                  Captured {new Date(memory.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex flex-col items-end gap-2 shrink-0">
                {memory.review_reason && (
                  <span className="text-xs bg-flash/15 text-flash px-2 py-1 rounded">
                    {REASON_LABELS[memory.review_reason] || memory.review_reason}
                  </span>
                )}
                <Link
                  href={`/memories/${memory.id}`}
                  className="text-sm bg-flash text-flash-ink px-3 py-1 rounded hover:bg-flash-dark"
                >
                  Set date
                </Link>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
