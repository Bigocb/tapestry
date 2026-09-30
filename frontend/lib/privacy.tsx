"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";
import { relockMemory, unlockMemory } from "./api";

// Notify subscribers when the unlock list changes within this tab.
const CHANGE_EVENT = "tapestry:unlock-change";

function emitChange() {
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(callback: () => void) {
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function getSnapshot(): string {
  // sessionStorage is the source of truth. Returning the raw string keeps the
  // snapshot referentially stable, which useSyncExternalStore requires.
  try {
    return sessionStorage.getItem("unlockedMemoryIds") ?? "[]";
  } catch {
    return "[]";
  }
}

function getServerSnapshot(): string {
  return "[]";
}

interface PrivacyContextType {
  unlockedIds: string[];
  isUnlocked: (id: string) => boolean;
  unlock: (id: string) => void;
  relock: (id: string) => void;
}

/**
 * Privacy state is read straight from sessionStorage via useSyncExternalStore
 * rather than mirrored into useState, so there is no setState-in-effect and no
 * hydration mismatch. It also means a page refresh naturally re-locks
 * everything, because sessionStorage is cleared per tab session.
 */
export function usePrivacy(): PrivacyContextType {
  const serialized = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot
  );

  const unlockedIds = useMemo<string[]>(() => {
    try {
      const parsed = JSON.parse(serialized);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [serialized]);

  const unlock = useCallback((id: string) => {
    unlockMemory(id);
    emitChange();
  }, []);

  const relock = useCallback((id: string) => {
    relockMemory(id);
    emitChange();
  }, []);

  const isUnlocked = useCallback(
    (id: string) => unlockedIds.includes(id),
    [unlockedIds]
  );

  return { unlockedIds, isUnlocked, unlock, relock };
}

/** Retained so the root layout keeps working; state now lives in the store. */
export function PrivacyProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
