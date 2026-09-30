"use client";

import { useEffect, useState } from "react";

import { api, type Telling, type TellingSegment } from "@/lib/api";

export function TellingReview({ tellingId }: { tellingId: string }) {
  const [telling, setTelling] = useState<Telling | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [committing, setCommitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getTelling(tellingId)
      .then((loaded) => {
        if (!cancelled) setTelling(loaded);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this telling.");
      });
    return () => {
      cancelled = true;
    };
  }, [tellingId]);

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
    setCommitting(true);
    try {
      const committed = await api.commitTelling(tellingId);
      setTelling(committed);
      const created = committed.segments.filter(
        (segment) => segment.memory_id
      ).length;
      setResult(`${created} ${created === 1 ? "memory" : "memories"} created.`);
    } finally {
      setCommitting(false);
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!telling) return <p className="text-gray-500">Loading…</p>;

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <section>
        <h1 className="text-2xl font-bold mb-4">Tell a story</h1>
        <div className="border rounded p-4 bg-gray-50">
          <p className="text-xs uppercase tracking-wide text-gray-500 mb-2">
            What you said
          </p>
          <p
            data-testid="telling-transcript"
            className="whitespace-pre-wrap text-gray-700"
          >
            {telling.raw_transcript}
          </p>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-bold mb-4">Proposed memories</h2>
        <div className="space-y-4">
          {telling.segments.map((segment) => (
            <SegmentCard
              key={segment.id}
              tellingId={telling.id}
              segment={segment}
              onSaved={replaceSegment}
            />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        {telling.status === "committed" ? null : (
          <button
            type="button"
            onClick={commit}
            disabled={committing}
            className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            Save these memories
          </button>
        )}
        {result && (
          <div className="border rounded p-4 bg-green-50">
            <h3 className="font-semibold text-green-800">Saved</h3>
            <p className="text-sm text-gray-600">{result}</p>
          </div>
        )}
      </section>
    </div>
  );
}

function SegmentCard({
  tellingId,
  segment,
  onSaved,
}: {
  tellingId: string;
  segment: TellingSegment;
  onSaved: (updated: TellingSegment) => void;
}) {
  const [title, setTitle] = useState(segment.title ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      onSaved(await api.updateTellingSegment(tellingId, segment.id, { title }));
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

  return (
    <article
      data-testid="telling-segment"
      className={`border rounded p-4 space-y-3 ${
        segment.status === "rejected" ? "bg-gray-50 opacity-75" : "bg-white"
      }`}
    >
      <h3 className="font-semibold">{segment.title}</h3>
      <p className="text-sm text-gray-600">{segment.text}</p>
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
      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={reject}
          disabled={saving}
          className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </article>
  );
}
