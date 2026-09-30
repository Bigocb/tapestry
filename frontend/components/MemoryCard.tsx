"use client";

import Link from "next/link";
import { usePrivacy } from "@/lib/privacy";
import { formatMemoryDate } from "@/lib/dates";

export interface Memory {
  id: string;
  raw_input: string;
  title?: string;
  summary?: string;
  state?: string;
  processing_state?: string;
  created_at: string;
  event_date?: string;
  date_precision?: string;
  event_date_end?: string;
  date_label?: string;
  mood?: string;
  tags?: string[];
  people?: string[];
  location?: string;
  importance_level?: number;
  needs_review?: boolean;
  review_reason?: string;
  is_private?: boolean;
  is_locked?: boolean;
}

export function MemoryCard({
  memory,
  onDelete,
}: {
  memory: Memory;
  onDelete?: (id: string) => void;
}) {
  const { isUnlocked, unlock, relock } = usePrivacy();

  // Server redaction is authoritative: honour is_locked, which stays true even
  // if the client thinks it unlocked something the server withheld.
  const locked = memory.is_locked === true;
  // A memory that was unlocked for this session but has since been relocked
  // client-side will come back redacted after a refetch.
  const privateUnlocked =
    memory.is_private === true && !locked && isUnlocked(memory.id);

  // Unlocking/re-locking changes which memories the server will redact, so
  // reload to refetch everything with the updated session unlock list.
  const handleUnlock = () => {
    unlock(memory.id);
    window.location.reload();
  };

  const handleRelock = () => {
    relock(memory.id);
    window.location.reload();
  };

  return (
    <div
      className={`border rounded-lg p-4 transition ${
        locked
          ? "bg-bg border-line"
          : "bg-surface border-line hover:border-flash"
      }`}
    >
      <div className="flex justify-between items-start gap-3">
        {locked ? (
          <span className="font-medium text-lg text-ink-muted">
            🔒 {memory.title || "Private memory"}
          </span>
        ) : (
          <Link href={`/memories/${memory.id}`} className="font-medium text-lg text-ink hover:text-flash">
            {memory.title || memory.raw_input}
          </Link>
        )}
        <div className="flex items-center gap-3 shrink-0">
          {locked && (
            <button
              onClick={handleUnlock}
              className="text-sm bg-flash text-flash-ink px-3 py-1 rounded hover:bg-flash-dark"
            >
              Unlock
            </button>
          )}
          {privateUnlocked && (
            <button
              onClick={handleRelock}
              className="text-sm border border-line text-ink-muted px-3 py-1 rounded hover:bg-surface-2"
              title="Hide this memory again"
            >
              Re-lock
            </button>
          )}
          {onDelete && (
            <button
              onClick={() => onDelete(memory.id)}
              className="text-coral/70 text-sm hover:text-coral"
            >
              Delete
            </button>
          )}
        </div>
      </div>
      <p className="stamp text-ink-muted mt-1.5">
        {formatMemoryDate(memory)}
        {" · "}
        {memory.processing_state}
        {memory.is_private && (
          <span className="ml-2">
            {locked ? "Private" : "Private · unlocked"}
          </span>
        )}
      </p>
      {locked ? (
        <p className="text-ink-muted mt-2 italic">
          Locked. Unlock to view this memory.
        </p>
      ) : (
        <>
          <p className="text-ink/90 mt-2 line-clamp-3">
            {memory.summary || memory.raw_input}
          </p>
          <div className="flex flex-wrap gap-2 mt-3">
            {memory.mood && (
              <span className="text-xs bg-flash/15 text-flash px-2 py-1 rounded">
                {memory.mood}
              </span>
            )}
            {memory.location && (
              <span className="text-xs bg-mint/15 text-mint px-2 py-1 rounded">
                {memory.location}
              </span>
            )}
            {memory.tags?.map((tag) => (
              <span
                key={tag}
                className="text-xs bg-bg border border-line text-ink-muted px-2 py-1 rounded"
              >
                {tag}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
