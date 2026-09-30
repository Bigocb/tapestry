"use client";

import { useEffect, useRef, useState } from "react";

import {
  api,
  type Telling,
  type TellingSegment,
  type TellingSegmentUpdate,
} from "@/lib/api";
import { formatMemoryDate } from "@/lib/dates";

// A fuzzy period is a real answer, so precision is the user's to choose.
const PRECISIONS = ["exact", "month", "year", "decade"];

export function TellingReview({ tellingId }: { tellingId: string }) {
  const [telling, setTelling] = useState<Telling | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [resplit, setResplit] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getTelling(tellingId)
      .then((loaded) => {
        if (cancelled) return;
        setTelling(loaded);
        setTranscript(loaded.raw_transcript);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this telling.");
      });
    return () => {
      cancelled = true;
    };
  }, [tellingId]);

  async function resplitTranscript() {
    if (!telling) return;

    // The whole split is thrown away, so say so before doing it.
    const proceed = window.confirm(
      "Re-splitting replaces the current proposed memories. Continue?"
    );
    if (!proceed) return;

    const value = transcript ?? telling.raw_transcript;
    const before = new Set(telling.segments.map((segment) => segment.text));

    setBusy(true);
    try {
      const updated = await api.updateTellingTranscript(telling.id, value);
      const after = new Set(updated.segments.map((segment) => segment.text));
      const added = [...after].filter((text) => !before.has(text)).length;
      const gone = [...before].filter((text) => !after.has(text)).length;

      setTelling(updated);
      setTranscript(updated.raw_transcript);
      setResplit(`${added} new, ${gone} gone`);
    } finally {
      setBusy(false);
    }
  }

  // Every structural edit returns the whole telling, so the screen is rebuilt
  // from one source of truth rather than patched piecemeal.
  async function reshape(action: () => Promise<Telling>) {
    setBusy(true);
    try {
      setTelling(await action());
    } finally {
      setBusy(false);
    }
  }

  function replaceSegment(updated: TellingSegment) {
    setTelling((current) =>
      current
        ? {
            ...current,
            segments: current.segments.map((segment) =>
              segment.id === updated.id ? updated : segment
            ),
          }
        : current
    );
  }

  async function commit() {
    setBusy(true);
    try {
      const committed = await api.commitTelling(tellingId);
      setTelling(committed);
      const created = committed.segments.filter(
        (segment) => segment.memory_id
      ).length;
      setResult(`${created} ${created === 1 ? "memory" : "memories"} created.`);
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    setBusy(true);
    try {
      setTelling(await api.deleteTellingMemories(tellingId));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!telling) return <p className="text-gray-500">Loading…</p>;

  const segments = telling.segments;

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <section>
        <h1 className="text-2xl font-bold mb-4">Tell a story</h1>
        <div className="border rounded p-4 bg-gray-50 space-y-3">
          <label className="block">
            <span className="block text-xs uppercase tracking-wide text-gray-500 mb-2">
              What you said
            </span>
            <textarea
              data-testid="telling-transcript"
              className="w-full border rounded p-3 h-40 text-gray-700"
              value={transcript ?? ""}
              onChange={(event) => setTranscript(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={resplitTranscript}
            disabled={busy}
            className="border px-4 py-2 rounded hover:bg-white disabled:opacity-50"
          >
            Re-split
          </button>
          {resplit ? (
            <p className="text-sm text-gray-600">Re-split: {resplit}.</p>
          ) : null}
        </div>
      </section>

      <section>
        <h2 className="text-xl font-bold mb-4">Proposed memories</h2>
        {telling.frame_label ? (
          <p className="mb-3 text-gray-600">
            This telling is about:{" "}
            <span className="font-medium">{telling.frame_label}</span>
          </p>
        ) : null}
        <div className="space-y-4">
          {segments.map((segment, index) => (
            <SegmentCard
              key={segment.id}
              tellingId={telling.id}
              segment={segment}
              busy={busy}
              canMergeWithNext={index < segments.length - 1}
              canMoveUp={index > 0}
              canMoveDown={index < segments.length - 1}
              onSaved={replaceSegment}
              onMove={(delta) => {
                const ids = segments.map((item) => item.id);
                const target = index + delta;
                [ids[index], ids[target]] = [ids[target], ids[index]];
                return reshape(() =>
                  api.reorderTellingSegments(telling.id, ids)
                );
              }}
              onMergeWithNext={() =>
                reshape(() =>
                  api.mergeTellingSegments(telling.id, [
                    segment.id,
                    segments[index + 1].id,
                  ])
                )
              }
              onSplit={(at) =>
                reshape(() =>
                  api.splitTellingSegment(telling.id, segment.id, at)
                )
              }
              onDelete={() =>
                reshape(() => api.deleteTellingSegment(telling.id, segment.id))
              }
            />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        {telling.status === "committed" ? (
          <button
            type="button"
            onClick={undo}
            disabled={busy}
            className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Delete these memories
          </button>
        ) : (
          <button
            type="button"
            onClick={commit}
            disabled={busy}
            className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            Save these memories
          </button>
        )}
        {result ? (
          <div className="border rounded p-4 bg-green-50">
            <h3 className="font-semibold text-green-800">Saved</h3>
            <p className="text-sm text-gray-600">{result}</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function SegmentCard({
  tellingId,
  segment,
  busy,
  canMergeWithNext,
  canMoveUp,
  canMoveDown,
  onSaved,
  onMove,
  onMergeWithNext,
  onSplit,
  onDelete,
}: {
  tellingId: string;
  segment: TellingSegment;
  busy: boolean;
  canMergeWithNext: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onSaved: (updated: TellingSegment) => void;
  onMove: (delta: number) => void;
  onMergeWithNext: () => void;
  onSplit: (at: number) => void;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(segment.title ?? "");
  const [text, setText] = useState(segment.text);
  const [saving, setSaving] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const initialDate = segment.event_date ? segment.event_date.slice(0, 10) : "";
  const initialPrecision = PRECISIONS.includes(segment.date_precision ?? "")
    ? (segment.date_precision as string)
    : "exact";
  const [date, setDate] = useState(initialDate);
  const [precision, setPrecision] = useState(initialPrecision);

  function edits(): TellingSegmentUpdate {
    const update: TellingSegmentUpdate = { title };
    if (text !== segment.text) update.text = text;

    // Only send dates the user actually changed. Sending them unconditionally
    // would clear a fuzzy label nobody touched.
    if (date !== initialDate || precision !== initialPrecision) {
      if (date) {
        update.event_date = `${date}T00:00:00`;
        update.date_precision = precision;
        // An explicit date replaces whatever wording described the old one.
        update.date_label = null;
      } else {
        update.event_date = null;
        update.date_precision = "unknown";
        update.date_label = null;
      }
    }

    return update;
  }

  async function save() {
    setSaving(true);
    try {
      onSaved(
        await api.updateTellingSegment(tellingId, segment.id, edits())
      );
    } finally {
      setSaving(false);
    }
  }

  async function reject() {
    setSaving(true);
    try {
      onSaved(
        await api.updateTellingSegment(tellingId, segment.id, {
          status: "rejected",
        })
      );
    } finally {
      setSaving(false);
    }
  }

  function splitHere() {
    // The cursor is the cut: the textarea exists so the user can place it.
    const at = textRef.current?.selectionStart ?? 0;
    if (at > 0 && at < text.length) onSplit(at);
  }

  const disabled = saving || busy;

  return (
    <article
      data-testid="telling-segment"
      className={`border rounded p-4 space-y-3 ${
        segment.status === "rejected" ? "bg-gray-50 opacity-75" : "bg-white"
      }`}
    >
      <h3 className="font-semibold">{segment.title}</h3>
      <p className="text-sm text-gray-500">
        {formatMemoryDate(segment) || "No date"}
      </p>

      <label className="block">
        <span className="block text-sm font-medium mb-1">Text</span>
        <textarea
          ref={textRef}
          className="w-full border rounded p-2 h-24"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>

      {segment.status === "rejected" ? (
        <p className="text-sm text-amber-700">
          Rejected — this will not become a memory.
        </p>
      ) : null}

      <label className="block">
        <span className="block text-sm font-medium mb-1">Title</span>
        <input
          className="w-full border rounded p-2"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>

      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="block text-sm font-medium mb-1">Date</span>
          <input
            type="date"
            className="border rounded p-2"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label className="block">
          <span className="block text-sm font-medium mb-1">Precision</span>
          <select
            className="border rounded p-2"
            value={precision}
            onChange={(event) => setPrecision(event.target.value)}
          >
            {PRECISIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={save}
          disabled={disabled}
          className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={reject}
          disabled={disabled}
          className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          Reject
        </button>
        {canMoveUp ? (
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={disabled}
            className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Move up
          </button>
        ) : null}
        {canMoveDown ? (
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={disabled}
            className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Move down
          </button>
        ) : null}
        {canMergeWithNext ? (
          <button
            type="button"
            onClick={onMergeWithNext}
            disabled={disabled}
            className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Merge with next
          </button>
        ) : null}
        <button
          type="button"
          onClick={splitHere}
          disabled={disabled}
          className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          Split here
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={disabled}
          className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
    </article>
  );
}
