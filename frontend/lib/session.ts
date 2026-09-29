"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Activity events that count as "the user is here".
 *
 * Deliberately broad: scrolling, typing, clicking or moving the mouse all reset
 * the clock. `visibilitychange` is included so switching back to the tab counts
 * as activity rather than logging you out instantly.
 */
const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  "mousemove",
  "mousedown",
  "keydown",
  "scroll",
  "touchstart",
  "focus",
];

interface IdleTimeoutOptions {
  /** Total idle time before logout, in milliseconds. */
  timeoutMs: number;
  /** How long before logout to start warning, in milliseconds. */
  warningMs: number;
  /** Called once the idle period is fully exceeded. */
  onTimeout: () => void;
  /** Disable the timer entirely (e.g. when logged out). */
  enabled: boolean;
}

interface IdleTimeoutState {
  /** True while the warning is showing. */
  isWarning: boolean;
  /** Seconds left before logout, while warning. */
  secondsRemaining: number;
  /** Reset the clock and dismiss the warning. */
  stayActive: () => void;
}

/**
 * Track user activity and fire `onTimeout` after a quiet period.
 *
 * Elapsed time is measured from a timestamp rather than accumulated ticks, so
 * backgrounded tabs (whose timers are throttled or paused) still time out
 * correctly the moment they are looked at again.
 */
export function useIdleTimeout({
  timeoutMs,
  warningMs,
  onTimeout,
  enabled,
}: IdleTimeoutOptions): IdleTimeoutState {
  // Lazily initialised so we never call the impure Date.now() during render.
  const lastActivityRef = useRef<number | null>(null);
  const warningRef = useRef(false);
  const [isWarning, setIsWarning] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);

  // Keep the latest callback without making it an effect dependency, so the
  // interval is not torn down and recreated on every render.
  const onTimeoutRef = useRef(onTimeout);
  useEffect(() => {
    onTimeoutRef.current = onTimeout;
  }, [onTimeout]);

  const setWarning = useCallback((active: boolean) => {
    warningRef.current = active;
    setIsWarning(active);
  }, []);

  const stayActive = useCallback(() => {
    lastActivityRef.current = Date.now();
    setWarning(false);
    setSecondsRemaining(0);
  }, [setWarning]);

  useEffect(() => {
    if (!enabled) return;

    // Start fresh whenever the timer is (re)enabled. This runs inside the
    // subscription setup rather than as a render-phase state write.
    lastActivityRef.current = Date.now();

    const markActive = () => {
      lastActivityRef.current = Date.now();
    };

    ACTIVITY_EVENTS.forEach((event) =>
      window.addEventListener(event, markActive, { passive: true })
    );
    document.addEventListener("visibilitychange", markActive);

    const tick = () => {
      const last = lastActivityRef.current ?? Date.now();
      const elapsed = Date.now() - last;
      const remaining = timeoutMs - elapsed;

      if (remaining <= 0) {
        onTimeoutRef.current();
        return;
      }

      if (remaining <= warningMs) {
        if (!warningRef.current) setWarning(true);
        setSecondsRemaining(Math.ceil(remaining / 1000));
      } else if (warningRef.current) {
        // Fresh activity pushed us back above the warning threshold.
        setWarning(false);
        setSecondsRemaining(0);
      }
    };

    const interval = window.setInterval(tick, 1000);

    return () => {
      window.clearInterval(interval);
      ACTIVITY_EVENTS.forEach((event) =>
        window.removeEventListener(event, markActive)
      );
      document.removeEventListener("visibilitychange", markActive);
    };
  }, [enabled, timeoutMs, warningMs, setWarning]);

  return { isWarning, secondsRemaining, stayActive };
}
