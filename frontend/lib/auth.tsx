"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { useRouter } from "next/navigation";

interface AuthContextType {
  token: string | null;
  isLoading: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    try {
      setToken(localStorage.getItem("token"));
    } catch {
      setToken(null);
    }
    setIsLoading(false);
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

  const logout = () => {
    try {
      localStorage.removeItem("token");
    } catch {
      // ignore storage errors
    }
    setToken(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider value={{ token, isLoading, login, logout }}>
      {children}
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
