"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { MapPinIcon } from "@heroicons/react/24/outline";

interface EntityMemoryRef {
  id: string;
  title?: string;
  summary?: string;
  role?: string;
  event_date?: string;
  date_label?: string;
  created_at: string;
}

interface EntityDetail {
  id: string;
  kind: string;
  canonical_name: string;
  description?: string;
  attributes?: Record<string, unknown>;
  parent_entity_id?: string;
  mention_count: number;
  first_seen_at?: string;
  last_seen_at?: string;
  aliases: string[];
  memories: EntityMemoryRef[];
  // Optional: an entity fetched before facts existed has no such field.
  facts?: EntityFact[];
}

interface EntityFact {
  id: string;
  source: string;
  source_id: string;
  label: string;
  description?: string | null;
  url?: string | null;
  fetched_at: string;
}

interface LookupCandidate {
  source: string;
  source_id: string;
  label: string;
  description?: string | null;
  url: string;
  // Present only for an address verification, which resolves to a point.
  latitude?: number | null;
  longitude?: number | null;
  address?: string | null;
}

interface EntitySummaryBase {
  id: string;
  canonical_name: string;
  kind: string;
  mention_count: number;
}

interface MergeSuggestion {
  source: EntitySummaryBase;
  target: EntitySummaryBase;
  reason: string;
}

interface AppliedMerge {
  merge_id: string;
  source_id: string;
  target_id: string;
  source_name: string;
  target_name: string;
}

function formatWhen(memory: EntityMemoryRef): string {
  if (memory.date_label) return memory.date_label;
  if (memory.event_date) {
    return new Date(memory.event_date).toLocaleDateString();
  }
  return new Date(memory.created_at).toLocaleDateString();
}

// The address lives in the entity's kind-specific attributes, but is edited and
// shown as its own thing so the card never has to know that.
function addressOf(entity: EntityDetail): string {
  const value = (entity.attributes ?? {}).address;
  return typeof value === "string" ? value : "";
}

const actionBoxClass = "bg-surface border border-line rounded-2xl p-5";
const fieldClass =
  "bg-bg-raised border border-line rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-flash/30 focus:border-flash";
const btnOutline =
  "border border-line rounded-lg px-4 py-2 text-sm font-semibold hover:border-flash hover:text-flash transition disabled:opacity-50 disabled:hover:border-line disabled:hover:text-ink";
const btnSolid =
  "bg-flash text-flash-ink rounded-lg px-4 py-2 text-sm font-bold hover:bg-flash-dark transition disabled:opacity-40";

export function EntityDetailView({ id }: { id: string }) {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [suggestions, setSuggestions] = useState<MergeSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [lastMerge, setLastMerge] = useState<AppliedMerge | null>(null);
  const [notice, setNotice] = useState("");
  const [candidates, setCandidates] = useState<EntitySummaryBase[]>([]);
  const [target, setTarget] = useState("");
  const [found, setFound] = useState<LookupCandidate[]>([]);
  const [lookingUp, setLookingUp] = useState(false);
  const [lookedUp, setLookedUp] = useState(false);

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [address, setAddress] = useState("");
  const [verified, setVerified] = useState<LookupCandidate[]>([]);
  const [chosen, setChosen] = useState<LookupCandidate | null>(null);
  const [verifying, setVerifying] = useState(false);

  const startEditing = () => {
    if (!entity) return;
    setName(entity.canonical_name);
    setDescription(entity.description ?? "");
    setAddress(addressOf(entity));
    setVerified([]);
    setChosen(null);
    setEditing(true);
  };

  const verifyAddress = async () => {
    if (!entity || !address.trim()) return;
    setVerifying(true);
    try {
      setVerified(await api.verifyAddress(entity.id, address.trim()));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not verify that");
    } finally {
      setVerifying(false);
    }
  };

  const useAddress = (candidate: LookupCandidate) => {
    setAddress(candidate.address ?? candidate.label);
    setChosen(candidate);
    setVerified([]);
  };

  const saveEdits = async () => {
    if (!entity) return;
    const changes: {
      canonical_name?: string;
      description?: string | null;
      address?: string | null;
      latitude?: number | null;
      longitude?: number | null;
    } = {};

    // Only send what actually changed: an omitted field is left alone, and a
    // present null clears it.
    if (name.trim() && name.trim() !== entity.canonical_name) {
      changes.canonical_name = name.trim();
    }
    if (description.trim() !== (entity.description ?? "")) {
      changes.description = description.trim() || null;
    }
    if (entity.kind === "place" && address.trim() !== addressOf(entity)) {
      changes.address = address.trim() || null;
      // Coordinates only travel with the address they were verified against.
      changes.latitude = chosen?.latitude ?? null;
      changes.longitude = chosen?.longitude ?? null;
    }

    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }

    setBusy(true);
    try {
      await api.updateEntity(entity.id, changes);
      setEditing(false);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save that");
    } finally {
      setBusy(false);
    }
  };

  const lookUp = async () => {
    if (!entity) return;
    setLookingUp(true);
    try {
      setFound(await api.lookupEntity(entity.id));
      setLookedUp(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLookingUp(false);
    }
  };

  const keep = async (candidate: LookupCandidate) => {
    if (!entity) return;
    setBusy(true);
    try {
      await api.keepEntityFact(entity.id, {
        source: candidate.source,
        source_id: candidate.source_id,
        label: candidate.label,
        description: candidate.description ?? null,
        url: candidate.url,
      });
      setFound([]);
      setLookedUp(false);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not keep that");
    } finally {
      setBusy(false);
    }
  };

  const discard = async (factId: string) => {
    if (!entity) return;
    setBusy(true);
    try {
      await api.discardEntityFact(entity.id, factId);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not discard that");
    } finally {
      setBusy(false);
    }
  };

  const [moving, setMoving] = useState<Set<string>>(new Set());
  const [newName, setNewName] = useState("");
  const [lastSplit, setLastSplit] = useState<string | null>(null);

  const toggleMoving = (memoryId: string) => {
    const next = new Set(moving);
    if (next.has(memoryId)) next.delete(memoryId);
    else next.add(memoryId);
    setMoving(next);
  };

  const splitOut = async () => {
    if (!entity || moving.size === 0 || !newName.trim()) return;
    setBusy(true);
    try {
      const result = await api.splitEntity(entity.id, {
        name: newName.trim(),
        memory_ids: Array.from(moving),
      });
      setLastSplit(result.split_id);
      setNotice(
        `Moved ${result.moved_mention_count} ${
          result.moved_mention_count === 1 ? "memory" : "memories"
        } into “${newName.trim()}”.`
      );
      setMoving(new Set());
      setNewName("");
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Split failed");
    } finally {
      setBusy(false);
    }
  };

  const undoTheSplit = async () => {
    if (!lastSplit) return;
    setBusy(true);
    try {
      await api.undoEntitySplit(lastSplit);
      setNotice("Split undone.");
      setLastSplit(null);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not undo the split");
    } finally {
      setBusy(false);
    }
  };

  const load = useCallback(() => {
    return api
      .getEntity(id)
      .then((data) => {
        setEntity(data);
        setError("");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load entity");
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    let active = true;
    load();
    api
      .getMergeSuggestions()
      .then((data) => {
        if (!active) return;
        // Only suggestions involving this entity are actionable here.
        setSuggestions(
          (data || []).filter(
            (s: MergeSuggestion) =>
              s.source.id === id || s.target.id === id
          )
        );
      })
      .catch(() => {
        /* suggestions are optional */
      });
    return () => {
      active = false;
    };
  }, [id, load]);

  useEffect(() => {
    if (!entity) return;
    let active = true;

    // Anything of the same kind can be a target. Until this existed the only
    // reachable merges were the pairs the automation proposed, so a duplicate
    // it had not noticed could not be merged at all.
    api
      .getEntities(entity.kind, 200, 0)
      .then((data: { items?: EntitySummaryBase[] }) => {
        if (!active) return;
        setCandidates(
          (data?.items ?? []).filter((item) => item.id !== entity.id)
        );
      })
      .catch(() => {
        /* the picker is optional */
      });

    return () => {
      active = false;
    };
  }, [entity]);

  const mergeIntoChosen = async () => {
    if (!entity || !target) return;
    const chosen = candidates.find((item) => item.id === target);
    const name = chosen?.canonical_name ?? "the other entity";

    setBusy(true);
    try {
      const result = await api.mergeEntities(entity.id, target);
      setLastMerge({
        merge_id: result.merge_id,
        source_id: entity.id,
        target_id: target,
        source_name: entity.canonical_name,
        target_name: name,
      });
      setNotice(`Merged ${entity.canonical_name} into ${name}.`);
      setTarget("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setBusy(false);
    }
  };

  const doMerge = async (suggestion: MergeSuggestion) => {
    if (!entity) return;
    setBusy(true);
    setNotice("");
    try {
      const result = await api.mergeEntities(
        suggestion.source.id,
        suggestion.target.id
      );
      setLastMerge({
        merge_id: result.merge_id,
        source_id: suggestion.source.id,
        target_id: suggestion.target.id,
        source_name: suggestion.source.canonical_name,
        target_name: suggestion.target.canonical_name,
      });
      setNotice(
        `Merged ${suggestion.source.canonical_name} into ${suggestion.target.canonical_name}.`
      );
      setSuggestions([]);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!lastMerge) return;
    setBusy(true);
    try {
      await api.undoEntityMerge(lastMerge.merge_id);
      setNotice(
        `Undid the merge of ${lastMerge.source_name} into ${lastMerge.target_name}.`
      );
      setLastMerge(null);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="text-ink-muted">Loading&hellip;</p>;
  if (error) return <p className="text-coral">{error}</p>;
  if (!entity) return <p className="text-ink-muted">Entity not found.</p>;

  const kindLabel =
    entity.kind === "person"
      ? "Person"
      : entity.kind === "place"
        ? "Place"
        : "Organization";
  const isPerson = entity.kind === "person";

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <p className="stamp text-ink-muted">{kindLabel}</p>
        <div className="flex items-center gap-4 mt-2">
          <span
            className={`shrink-0 w-14 h-14 rounded-full flex items-center justify-center font-display text-xl ${
              isPerson ? "bg-violet/15 text-violet" : "bg-mint/15 text-mint"
            }`}
          >
            {isPerson ? (
              entity.canonical_name.charAt(0).toUpperCase()
            ) : (
              <MapPinIcon className="w-6 h-6" />
            )}
          </span>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold">{entity.canonical_name}</h1>
            <p className="stamp text-ink-muted mt-1">
              {entity.mention_count}{" "}
              {entity.mention_count === 1 ? "mention" : "mentions"}
            </p>
          </div>
          {!editing && (
            <button type="button" onClick={startEditing} className={btnOutline}>
              Edit
            </button>
          )}
        </div>

        {!editing && (entity.description || (entity.kind === "place" && addressOf(entity))) && (
          <div className="mt-4 space-y-1">
            {entity.description && (
              <p className="text-ink-muted text-sm">{entity.description}</p>
            )}
            {entity.kind === "place" && addressOf(entity) && (
              <p className="text-ink-faint text-sm flex items-center gap-1.5">
                <MapPinIcon className="w-4 h-4 shrink-0" />
                {addressOf(entity)}
              </p>
            )}
          </div>
        )}

        {editing && (
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="stamp text-ink-faint">Name</span>
              <input
                aria-label="Name"
                className={`${fieldClass} w-full mt-1`}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="block">
              <span className="stamp text-ink-faint">Description</span>
              <textarea
                aria-label="Description"
                rows={2}
                className={`${fieldClass} w-full mt-1`}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            {entity.kind === "place" && (
              <div>
                <span className="stamp text-ink-faint">Address</span>
                <div className="flex gap-2 mt-1">
                  <input
                    aria-label="Address"
                    className={`${fieldClass} flex-1 min-w-0`}
                    value={address}
                    onChange={(event) => {
                      setAddress(event.target.value);
                      setChosen(null);
                    }}
                  />
                  <button
                    type="button"
                    onClick={verifyAddress}
                    disabled={verifying || !address.trim()}
                    className={`${btnOutline} shrink-0`}
                  >
                    {verifying ? "Verifying…" : "Verify"}
                  </button>
                </div>
                {chosen && (
                  <p className="stamp text-mint mt-1.5">
                    Verified · {chosen.latitude?.toFixed(5)},{" "}
                    {chosen.longitude?.toFixed(5)}
                  </p>
                )}
                {verified.length > 0 && (
                  <ul className="mt-2 space-y-1.5">
                    {verified.map((candidate) => (
                      <li
                        key={candidate.source_id}
                        className="flex items-start justify-between gap-3 text-sm border border-line rounded-lg p-2.5"
                      >
                        <span className="text-ink-muted min-w-0">
                          {candidate.address ?? candidate.label}
                        </span>
                        <button
                          type="button"
                          onClick={() => useAddress(candidate)}
                          className="text-flash underline shrink-0 text-xs font-semibold"
                        >
                          Use this
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {verified.length === 0 && !verifying && !chosen && address.trim() && (
                  <p className="stamp text-ink-faint mt-1.5 normal-case tracking-normal">
                    Verified against OpenStreetMap. Nothing is saved until you
                    press Save.
                  </p>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={saveEdits}
                disabled={busy}
                className={btnSolid}
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={busy}
                className={btnOutline}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {notice && (
        <div className="bg-mint/10 border border-mint/30 rounded-xl p-3 text-sm flex items-center justify-between gap-3">
          <span className="text-ink">{notice}</span>
          {lastMerge && (
            <button
              onClick={undo}
              disabled={busy}
              className="text-mint underline disabled:opacity-50 shrink-0"
            >
              Undo merge
            </button>
          )}
          {lastSplit && (
            <button
              onClick={undoTheSplit}
              disabled={busy}
              className="text-mint underline disabled:opacity-50 shrink-0"
            >
              Undo split
            </button>
          )}
        </div>
      )}

      {entity.aliases.length > 0 && (
        <section>
          <p className="stamp text-ink-faint mb-2">Also known as</p>
          <div className="flex flex-wrap gap-2">
            {entity.aliases.map((alias) => (
              <span
                key={alias}
                className="text-xs bg-surface-2 border border-line text-ink-muted px-2.5 py-1 rounded-full"
              >
                {alias}
              </span>
            ))}
          </div>
        </section>
      )}

      {(entity.facts ?? []).length > 0 && (
        <section className="bg-violet/8 border border-violet/30 rounded-2xl p-5">
          <p className="stamp text-violet mb-2">Found elsewhere</p>
          <ul className="space-y-3">
            {(entity.facts ?? []).map((fact) => (
              <li key={fact.id} className="text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-ink">{fact.label}</p>
                    {fact.description && (
                      <p className="text-ink-muted mt-0.5">{fact.description}</p>
                    )}
                    <p className="stamp text-ink-faint mt-2">
                      from {fact.source}
                      {fact.url ? (
                        <>
                          {" · "}
                          <a
                            href={fact.url}
                            target="_blank"
                            rel="noreferrer"
                            className="underline text-violet normal-case tracking-normal"
                          >
                            {fact.source_id}
                          </a>
                        </>
                      ) : null}
                      {" · fetched "}
                      {new Date(fact.fetched_at).toLocaleDateString()}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => discard(fact.id)}
                    disabled={busy}
                    className="text-xs text-ink-faint underline shrink-0 disabled:opacity-50 hover:text-ink-muted"
                  >
                    Discard
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <p className="stamp text-ink-faint mt-3 normal-case tracking-normal italic">
            Looked up, not remembered — {entity.canonical_name} never told us
            this.
          </p>
        </section>
      )}

      {entity.kind === "place" && (
        <section className={actionBoxClass}>
          <p className="font-semibold mb-1">Look this place up</p>
          <p className="text-sm text-ink-muted mb-3">
            Searches Wikidata by name. Nothing is kept until you choose it.
          </p>
          <button
            type="button"
            onClick={lookUp}
            disabled={lookingUp || busy}
            className={btnOutline}
          >
            {lookingUp ? "Looking…" : "Look this up"}
          </button>

          {lookedUp && found.length === 0 && (
            <p className="text-sm text-ink-muted mt-3">
              Nothing found under that name.
            </p>
          )}

          {found.length > 0 && (
            <ul className="mt-3 space-y-2">
              {found.map((candidate) => (
                <li
                  key={`${candidate.source}-${candidate.source_id}`}
                  className="flex items-start justify-between gap-3 text-sm border border-line rounded-lg p-3"
                >
                  <div>
                    <p className="font-medium text-ink">{candidate.label}</p>
                    {candidate.description && (
                      <p className="text-ink-muted mt-0.5">{candidate.description}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => keep(candidate)}
                    disabled={busy}
                    className={`${btnSolid} shrink-0`}
                  >
                    Keep this
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {suggestions.length > 0 && (
        <section className="bg-flash/10 border border-flash/30 rounded-2xl p-5">
          <p className="font-semibold mb-1">Possible duplicate</p>
          {suggestions.map((s) => (
            <div
              key={`${s.source.id}-${s.target.id}`}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="text-ink">
                &ldquo;{s.source.canonical_name}&rdquo; may be the same as{" "}
                &ldquo;{s.target.canonical_name}&rdquo;.
              </span>
              <button
                onClick={() => doMerge(s)}
                disabled={busy}
                className={`${btnSolid} shrink-0`}
              >
                {busy ? "Merging..." : "Merge them"}
              </button>
            </div>
          ))}
          <p className="text-xs text-ink-faint mt-2">
            Merging keeps the more-used name and is reversible.
          </p>
        </section>
      )}

      <section className={actionBoxClass}>
        <p className="font-semibold mb-1">
          Merge into another {kindLabel.toLowerCase()}
        </p>
        <p className="text-sm text-ink-muted mb-3">
          Moves every memory from this one to the entity you choose. Reversible.
        </p>
        <div className="flex gap-2 flex-wrap">
          <select
            aria-label="Merge into"
            className={`${fieldClass} flex-1 min-w-[160px]`}
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">Choose an entity…</option>
            {candidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.canonical_name}
                {candidate.mention_count
                  ? ` (${candidate.mention_count})`
                  : ""}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={mergeIntoChosen}
            disabled={busy || !target}
            className={btnSolid}
          >
            Merge
          </button>
        </div>
      </section>

      <section>
        <p className="stamp text-ink-faint mb-3">Memories</p>
        <ul className="space-y-2.5">
          {entity.memories.map((memory) => (
            <li key={memory.id} className="border border-line rounded-xl p-3.5 bg-surface flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1 accent-violet w-4 h-4"
                aria-label={memory.title || memory.summary || memory.id}
                checked={moving.has(memory.id)}
                onChange={() => toggleMoving(memory.id)}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-ink text-sm">
                    {memory.title || memory.summary || "Untitled memory"}
                  </span>
                  {memory.role && (
                    <span className="stamp text-violet bg-violet/15 px-2 py-0.5 rounded-full">
                      {memory.role}
                    </span>
                  )}
                </div>
                <p className="stamp text-ink-faint mt-1">{formatWhen(memory)}</p>
                <Link
                  href={`/memories/${memory.id}`}
                  className="text-xs text-flash font-semibold hover:underline inline-block mt-1.5"
                >
                  Open memory
                </Link>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={actionBoxClass}>
        <p className="font-semibold mb-1">Split memories into a new entity</p>
        <p className="text-sm text-ink-muted mb-3">
          Tick the memories that are a different{" "}
          {kindLabel.toLowerCase()}. This is for when two of them were read as
          one, which undoing a merge cannot fix.
        </p>
        <div className="flex gap-2 flex-wrap">
          <input
            aria-label="New entity name"
            placeholder="Name for the new entity"
            className={`${fieldClass} flex-1 min-w-[160px]`}
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
          <button
            type="button"
            onClick={splitOut}
            disabled={busy || moving.size === 0 || !newName.trim()}
            className={btnSolid}
          >
            Split out {moving.size > 0 ? `(${moving.size})` : ""}
          </button>
        </div>
      </section>
    </div>
  );
}
