"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { api } from "./api";
import { useIdleTimeout } from "./session";
import { IdleWarningModal } from "@/components/IdleWarningModal";

interface AuthContextType {
  token: string | null;
  isLoading: boolean;
  login: (token: string) => void;
  logout: () => void;
}

// Fallbacks used until the server tells us the configured policy.
const DEFAULT_IDLE_SECONDS = 15 * 60;
const DEFAULT_WARNING_SECONDS = 60;

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [idleSeconds, setIdleSeconds] = useState(DEFAULT_IDLE_SECONDS);
  const [warningSeconds, setWarningSeconds] = useState(DEFAULT_WARNING_SECONDS);
  const router = useRouter();

  useEffect(() => {
    try {
      setToken(localStorage.getItem("token"));
    } catch {
      setToken(null);
    }
    setIsLoading(false);
  }, []);

  // Learn the inactivity policy from the server. Unauthenticated, so this is
  // safe to call before login.
  useEffect(() => {
    api
      .getSessionConfig()
      .then((data) => {
        if (data?.idle_timeout_seconds) setIdleSeconds(data.idle_timeout_seconds);
        if (typeof data?.warning_seconds === "number")
          setWarningSeconds(data.warning_seconds);
      })
      .catch(() => {
        // Keep the defaults; enforcement still works.
      });
  }, []);

  // Keep React state in sync when the API layer silently refreshes the token
  // (or clears it after a failed refresh) directly in localStorage.
  useEffect(() => {
    const sync = (e: StorageEvent) => {
      if (e.key === "token") setToken(e.newValue);
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);

  const login = (newToken: string) => {
    try {
      localStorage.setItem("token", newToken);
    } catch {
      // ignore storage errors
    }
    setToken(newToken);
    router.push("/capture");
  };

  const logout = useCallback(() => {
    try {
      localStorage.removeItem("token");
      // Unlocks are session-scoped, so a sign-out must drop them too.
      sessionStorage.removeItem("unlockedMemoryIds");
    } catch {
      // ignore storage errors
    }
    setToken(null);
    router.push("/login");
  }, [router]);

  const { isWarning, secondsRemaining, stayActive } = useIdleTimeout({
    timeoutMs: idleSeconds * 1000,
    warningMs: warningSeconds * 1000,
    onTimeout: logout,
    // Only police inactivity while actually signed in.
    enabled: Boolean(token),
  });

  return (
    <AuthContext.Provider value={{ token, isLoading, login, logout }}>
      {children}
      {isWarning && token && (
        <IdleWarningModal
          secondsRemaining={secondsRemaining}
          onStayActive={stayActive}
          onLogout={logout}
        />
      )}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function Protected({ children }: { children: ReactNode }) {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!token) router.push("/login");
  }, [token, isLoading, router]);

  if (isLoading || !token) return null;
  return <>{children}</>;
}
