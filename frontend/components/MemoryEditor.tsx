"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { usePrivacy } from "@/lib/privacy";
import { Memory } from "./MemoryCard";
import { MapPinIcon } from "@heroicons/react/24/outline";

interface RelatedMemory {
  id: string;
  title?: string;
  summary?: string;
  event_date?: string;
  date_label?: string;
  shared_entities: string[];
  shared_count: number;
}

interface EntityRef {
  id: string;
  canonical_name: string;
}

const fieldClass =
  "w-full bg-bg-raised border border-line rounded-lg p-2.5 text-ink placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-flash/30 focus:border-flash";
const btnOutline =
  "border border-line rounded-lg px-4 py-2 text-sm font-semibold hover:border-flash hover:text-flash transition disabled:opacity-50";

export function MemoryEditor({ id }: { id: string }) {
  const router = useRouter();
  const { isUnlocked, unlock, relock } = usePrivacy();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [original, setOriginal] = useState<Memory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [togglingLock, setTogglingLock] = useState(false);
  // "exact" shows a date picker; "fuzzy" shows period fields (label + range).
  const [whenMode, setWhenMode] = useState<"exact" | "fuzzy">("exact");
  const [related, setRelated] = useState<RelatedMemory[]>([]);
  const [people, setPeople] = useState<EntityRef[]>([]);
  const [places, setPlaces] = useState<EntityRef[]>([]);

  // Fetch and apply, setting state only from async callbacks. Calling setState
  // synchronously inside an effect triggers cascading renders (and is flagged
  // by react-hooks/set-state-in-effect), so the effect below never does it.
  const fetchMemory = () =>
    api
      .getMemory(id)
      .then((data) => {
        setMemory(data);
        setOriginal(data);
        // Open the editor in whichever mode the memory already uses.
        setWhenMode(
          data?.date_label ||
            data?.date_precision === "range" ||
            data?.date_precision === "decade"
            ? "fuzzy"
            : "exact"
        );
        setError("");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load memory");
      })
      .finally(() => {
        setLoading(false);
      });

  // Related memories are derived from shared entities, so they are fetched
  // separately and are additive -- a failure here must not break the editor.
  const fetchRelated = () =>
    api
      .getRelatedMemories(id)
      .then((data) => setRelated(data?.items ?? []))
      .catch(() => setRelated([]));

  // Mentioned people/places are only linkable once we know their entity ids;
  // this list is small and additive, same as related memories above.
  const fetchEntities = () => {
    api
      .getEntities("person", 200, 0)
      .then((data) => setPeople(data?.items ?? []))
      .catch(() => setPeople([]));
    api
      .getEntities("place", 200, 0)
      .then((data) => setPlaces(data?.items ?? []))
      .catch(() => setPlaces([]));
  };

  const reload = () => {
    setLoading(true);
    fetchMemory();
  };

  useEffect(() => {
    fetchMemory();
    fetchRelated();
    fetchEntities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memory || !original) return;
    setSaving(true);
    setError("");
    try {
      // Send only what actually changed. Rewriting the source text triggers
      // full reprocessing, so untouched fields must not be resent.
      const payload: Record<string, unknown> = {};
      if (memory.raw_input !== original.raw_input) payload.raw_input = memory.raw_input;
      if (memory.title !== original.title) payload.title = memory.title;
      if (memory.summary !== original.summary) payload.summary = memory.summary;
      if (memory.mood !== original.mood) payload.mood = memory.mood;
      if ((memory.tags || []).join(",") !== (original.tags || []).join(","))
        payload.tags = memory.tags;
      if ((memory.people || []).join(",") !== (original.people || []).join(","))
        payload.people = memory.people;
      if (memory.location !== original.location) payload.location = memory.location;
      if (memory.importance_level !== original.importance_level)
        payload.importance_level = memory.importance_level;

      // Date fields are sent together so the backend can keep them consistent
      // (an exact date clears a stale fuzzy label and vice versa).
      const datesChanged =
        memory.event_date !== original.event_date ||
        memory.date_label !== original.date_label ||
        memory.date_precision !== original.date_precision ||
        memory.event_date_end !== original.event_date_end;
      if (datesChanged) {
        payload.event_date = memory.event_date ?? null;
        payload.date_label = memory.date_label ?? null;
        payload.date_precision = memory.date_precision ?? null;
        payload.event_date_end = memory.event_date_end ?? null;
      }

      if (Object.keys(payload).length === 0) {
        router.push("/search");
        return;
      }

      await api.updateMemory(id, payload);
      router.push("/search");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update memory");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this memory?")) return;
    try {
      await api.deleteMemory(id);
      router.push("/search");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const togglePrivacy = async () => {
    if (!memory) return;
    setTogglingLock(true);
    setError("");
    try {
      const next = !memory.is_private;
      await api.updateMemory(id, { is_private: next });
      if (next) {
        // A freshly locked memory is hidden from the session immediately.
        relock(id);
      } else {
        // Making it public means it no longer needs an unlock token.
        relock(id);
      }
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to change privacy");
    } finally {
      setTogglingLock(false);
    }
  };

  if (loading) return <p className="text-ink-muted">Loading&hellip;</p>;
  if (error) return <p className="text-coral">{error}</p>;
  if (!memory) return <p className="text-ink-muted">Memory not found.</p>;

  const update = (key: keyof Memory, value: unknown) =>
    setMemory((m) => (m ? { ...m, [key]: value } : null));

  const sourceChanged =
    original !== null && memory.raw_input !== original.raw_input;

  // The server withholds content when the memory is private and this session
  // has not unlocked it. Show an unlock gate instead of an empty editor.
  if (memory.is_locked) {
    return (
      <div className="max-w-2xl text-center py-16">
        <div className="text-5xl mb-4">🔒</div>
        <h1 className="text-2xl font-bold mb-2">This memory is private</h1>
        <p className="text-ink-muted mb-6">
          Its contents are hidden until you unlock it for this session.
        </p>
        <button
          onClick={() => {
            unlock(id);
            reload();
          }}
          className="bg-flash text-flash-ink px-5 py-2.5 rounded-lg font-semibold hover:bg-flash-dark"
        >
          Unlock memory
        </button>
      </div>
    );
  }

  const findEntity = (list: EntityRef[], name: string) =>
    list.find((e) => e.canonical_name.toLowerCase() === name.toLowerCase());

  const mentionedPeople = (memory.people || [])
    .map((name) => ({ name, entity: findEntity(people, name) }))
    .filter((m) => m.entity);
  const mentionedPlace = memory.location
    ? findEntity(places, memory.location)
    : undefined;

  const importance = memory.importance_level || 5;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-8 items-start max-w-[920px]">
      <form onSubmit={save} className="min-w-0 space-y-6">
        <h1 className="text-2xl font-bold">Edit memory</h1>

        <section className="space-y-1">
          <Field
            label="Original text"
            hint="The memory exactly as you told it. This is the source everything else is derived from."
          >
            <textarea
              className={`${fieldClass} h-40`}
              placeholder="e.g. On May 25th 2011, Maxwell Joseph Francis Cloutier was born."
              value={memory.raw_input || ""}
              onChange={(e) => update("raw_input", e.target.value)}
            />
          </Field>
          {sourceChanged ? (
            <p className="text-sm text-flash bg-flash/10 border border-flash/30 rounded-lg p-2.5">
              <strong>You changed the original text.</strong> Saving re-runs the AI
              to regenerate the title, summary, mood, tags and date below. Any
              field you edited on this screen is kept as you set it.
            </p>
          ) : (
            <p className="text-xs text-ink-faint">
              Change this only if the memory itself was recorded wrong — the AI
              will re-read it and rebuild the fields below.
            </p>
          )}
        </section>

        <hr className="border-line" />

        <section className="space-y-4">
          <h2 className="font-semibold text-ink">Details</h2>
          <Field
            label="Title"
            hint="Short heading, shown in lists and on the timeline."
          >
            <input
              type="text"
              className={fieldClass}
              placeholder="e.g. Birth of Maxwell Joseph Francis Cloutier"
              value={memory.title || ""}
              onChange={(e) => update("title", e.target.value)}
            />
          </Field>
          <Field
            label="Summary"
            hint="One or two sentences describing the memory."
          >
            <textarea
              className={`${fieldClass} h-28`}
              placeholder="e.g. Maxwell was born on May 25, 2011."
              value={memory.summary || ""}
              onChange={(e) => update("summary", e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Mood" hint="One word, e.g. joyful.">
              <input
                type="text"
                className={fieldClass}
                placeholder="joyful"
                value={memory.mood || ""}
                onChange={(e) => update("mood", e.target.value)}
              />
            </Field>
            <Field label="Location" hint="Where it happened, if relevant.">
              <input
                type="text"
                className={fieldClass}
                placeholder="e.g. Conway, South Carolina"
                value={memory.location || ""}
                onChange={(e) => update("location", e.target.value)}
              />
            </Field>
            <Field label="Tags" hint="Comma separated. Used for filtering.">
              <input
                type="text"
                className={fieldClass}
                placeholder="birth, family, milestone"
                value={(memory.tags || []).join(", ")}
                onChange={(e) =>
                  update(
                    "tags",
                    e.target.value.split(",").map((t) => t.trim()).filter(Boolean)
                  )
                }
              />
            </Field>
            <Field label="People" hint="Comma separated names mentioned.">
              <input
                type="text"
                className={fieldClass}
                placeholder="Maxwell Joseph Francis Cloutier"
                value={(memory.people || []).join(", ")}
                onChange={(e) =>
                  update(
                    "people",
                    e.target.value.split(",").map((p) => p.trim()).filter(Boolean)
                  )
                }
              />
            </Field>
          </div>

          <Field
            label="When did this happen?"
            hint="Use a precise date when you know it. Use 'Sometime...' for memories you can only place roughly, like a decade or a life stage."
          >
            <div className="flex gap-2 mb-2">
              <button
                type="button"
                onClick={() => setWhenMode("exact")}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border transition ${
                  whenMode === "exact"
                    ? "bg-flash text-flash-ink border-flash"
                    : "bg-surface text-ink-muted border-line hover:border-flash hover:text-flash"
                }`}
              >
                Exact date
              </button>
              <button
                type="button"
                onClick={() => setWhenMode("fuzzy")}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border transition ${
                  whenMode === "fuzzy"
                    ? "bg-flash text-flash-ink border-flash"
                    : "bg-surface text-ink-muted border-line hover:border-flash hover:text-flash"
                }`}
              >
                Sometime / approximate
              </button>
            </div>

            {whenMode === "exact" ? (
              <input
                type="datetime-local"
                className={fieldClass}
                value={
                  memory.event_date
                    ? new Date(memory.event_date).toISOString().slice(0, 16)
                    : ""
                }
                onChange={(e) => {
                  const value = e.target.value;
                  setMemory((current) => {
                    if (!current) return null;
                    if (!value) {
                      return {
                        ...current,
                        event_date: undefined,
                        date_precision: undefined,
                        date_label: undefined,
                        event_date_end: undefined,
                      };
                    }
                    // A precise date supersedes any fuzzy period. Leaving the
                    // old label or a stale "decade" precision behind sent the
                    // memory straight back to where it was.
                    return {
                      ...current,
                      event_date: new Date(value).toISOString(),
                      date_precision: "exact",
                      date_label: undefined,
                      event_date_end: undefined,
                    };
                  });
                }}
              />
            ) : (
              <div className="space-y-3 border border-line rounded-lg p-3 bg-bg-raised">
                <label className="block">
                  <span className="block text-xs font-medium text-ink-muted mb-1">
                    How would you describe it? (shown on the timeline)
                  </span>
                  <input
                    type="text"
                    className={fieldClass}
                    placeholder="e.g. Middle school, the 80s, my twenties"
                    value={memory.date_label || ""}
                    onChange={(e) =>
                      update("date_label", e.target.value || undefined)
                    }
                  />
                </label>
                <div className="flex gap-3">
                  <label className="flex-1">
                    <span className="block text-xs font-medium text-ink-muted mb-1">
                      Earliest year
                    </span>
                    <input
                      type="number"
                      min={1000}
                      max={2999}
                      className={fieldClass}
                      placeholder="1987"
                      value={
                        memory.event_date ? new Date(memory.event_date).getFullYear() : ""
                      }
                      onChange={(e) => {
                        const year = Number(e.target.value);
                        // Partial input ("19") is valid to type but too small to
                        // anchor yet; NaN (non-numeric) must not reach Date.UTC,
                        // which produced "Invalid time value" crashes.
                        if (!Number.isFinite(year) || year < 1000 || year > 2999) {
                          if (!e.target.value) update("event_date", undefined);
                          return;
                        }
                        update("event_date", new Date(Date.UTC(year, 0, 1)).toISOString());
                        update("date_precision", "range");
                      }}
                    />
                  </label>
                  <label className="flex-1">
                    <span className="block text-xs font-medium text-ink-muted mb-1">
                      Latest year (optional)
                    </span>
                    <input
                      type="number"
                      min={1000}
                      max={2999}
                      className={fieldClass}
                      placeholder="1990"
                      value={
                        memory.event_date_end
                          ? new Date(memory.event_date_end).getFullYear()
                          : ""
                      }
                      onChange={(e) => {
                        const year = Number(e.target.value);
                        if (!Number.isFinite(year) || year < 1000 || year > 2999) {
                          if (!e.target.value) update("event_date_end", undefined);
                          return;
                        }
                        update(
                          "event_date_end",
                          new Date(Date.UTC(year, 11, 31)).toISOString()
                        );
                        update("date_precision", "range");
                      }}
                    />
                  </label>
                </div>
                <p className="text-xs text-ink-faint">
                  Years anchor it on the timeline. The description is what you
                  actually see, so it can stay vague.
                </p>
              </div>
            )}
          </Field>

          <Field
            label={`Importance: ${importance}/10`}
            hint="How significant this memory is, 1 (minor) to 10 (life-changing)."
          >
            <div className="flex items-center gap-1 mb-1">
              {Array.from({ length: 10 }).map((_, i) => (
                <span
                  key={i}
                  className={`w-1.5 h-1.5 rounded-full ${
                    i < importance ? "bg-flash" : "bg-line"
                  }`}
                />
              ))}
            </div>
            <input
              type="range"
              min={1}
              max={10}
              value={importance}
              onChange={(e) => update("importance_level", Number(e.target.value))}
              className="w-full accent-flash"
            />
          </Field>
        </section>

        <section className="bg-surface border border-line rounded-2xl p-4 space-y-2">
          <div className="flex items-center justify-between gap-4">
            <div>
              <span className="block font-medium text-sm text-ink">
                Privacy
              </span>
              <span className="block text-xs text-ink-muted">
                {memory.is_private
                  ? "Private. Hidden behind a lock until you unlock it for the session."
                  : "Public within your account. Visible in lists, search and the timeline."}
              </span>
            </div>
            <button
              type="button"
              onClick={togglePrivacy}
              disabled={togglingLock}
              className={`${btnOutline} shrink-0 ${
                !memory.is_private ? "bg-surface-2" : ""
              }`}
            >
              {togglingLock
                ? "Working..."
                : memory.is_private
                  ? "Remove privacy lock"
                  : "Make private"}
            </button>
          </div>
          {memory.is_private && isUnlocked(id) && (
            <button
              type="button"
              onClick={() => {
                relock(id);
                reload();
              }}
              className="text-sm text-flash hover:underline"
            >
              Re-lock now (hide again)
            </button>
          )}
        </section>

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={saving}
            className="bg-flash text-flash-ink px-5 py-2.5 rounded-lg font-semibold hover:bg-flash-dark disabled:opacity-50 transition"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button
            type="button"
            onClick={remove}
            className="bg-coral text-white px-5 py-2.5 rounded-lg font-semibold hover:bg-coral-dark transition"
          >
            Delete
          </button>
        </div>
        {error && <p className="text-coral">{error}</p>}
      </form>

      <aside className="space-y-3 lg:sticky lg:top-8">
        <p className="stamp text-ink-faint">Mentioned</p>
        {mentionedPeople.length === 0 && !mentionedPlace ? (
          <p className="text-sm text-ink-faint">Nothing linked yet.</p>
        ) : (
          <>
            {mentionedPeople.map(({ name, entity }) => (
              <Link
                key={entity!.id}
                href={`/entities/${entity!.id}`}
                className="flex items-center gap-2.5 bg-surface border border-line rounded-xl p-3 hover:border-flash transition"
              >
                <span className="w-7 h-7 rounded-full bg-violet/15 text-violet flex items-center justify-center font-display text-xs shrink-0">
                  {name.charAt(0).toUpperCase()}
                </span>
                <span className="text-sm font-medium text-ink truncate">{name}</span>
              </Link>
            ))}
            {mentionedPlace && (
              <Link
                href={`/entities/${mentionedPlace.id}`}
                className="flex items-center gap-2.5 bg-surface border border-line rounded-xl p-3 hover:border-flash transition"
              >
                <span className="w-7 h-7 rounded-full bg-mint/15 text-mint flex items-center justify-center shrink-0">
                  <MapPinIcon className="w-3.5 h-3.5" />
                </span>
                <span className="text-sm font-medium text-ink truncate">
                  {memory.location}
                </span>
              </Link>
            )}
          </>
        )}

        {related.length > 0 && (
          <>
            <p className="stamp text-ink-faint pt-2">Related memories</p>
            {related.map((item) => (
              <Link
                key={item.id}
                href={`/memories/${item.id}`}
                className="block bg-surface border border-line rounded-xl p-3 hover:border-flash transition"
              >
                <p className="text-sm font-medium text-ink truncate">
                  {item.title || item.summary || "Untitled memory"}
                </p>
                <p className="stamp text-ink-faint mt-1">
                  Shares {item.shared_entities.join(", ")}
                </p>
              </Link>
            ))}
          </>
        )}
      </aside>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block font-medium text-sm text-ink mb-1">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink-faint mt-1">{hint}</span>}
    </label>
  );
}
