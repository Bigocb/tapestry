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

  if (error) return <p>{error}</p>;
  if (!telling) return <p>Loading…</p>;

  return (
    <div>
      <section>
        <h1>Tell a story</h1>
        <p data-testid="telling-transcript">{telling.raw_transcript}</p>
      </section>

      <section>
        <h2>Proposed memories</h2>
        {telling.segments.map((segment) => (
          <SegmentCard
            key={segment.id}
            tellingId={telling.id}
            segment={segment}
            onSaved={replaceSegment}
          />
        ))}
      </section>

      <section>
        {telling.status === "committed" ? null : (
          <button type="button" onClick={commit} disabled={committing}>
            Save these memories
          </button>
        )}
        {result ? <p>{result}</p> : null}
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
    <article data-testid="telling-segment">
      <h3>{segment.title}</h3>
      <p>{segment.text}</p>
      {segment.status === "rejected" ? (
        <p>Rejected — this will not become a memory.</p>
      ) : null}
      <label>
        Title
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <button type="button" onClick={save} disabled={saving}>
        Save
      </button>
      <button type="button" onClick={reject} disabled={saving}>
        Reject
      </button>
    </article>
  );
}
