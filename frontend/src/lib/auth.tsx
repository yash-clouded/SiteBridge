"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPostJson, AUTH_KEY, storedAuth, type Role, type TokenResponse, type User } from "./api";

/** Human labels for the three roles (function-based, never WBS-level-based). */
export const ROLE_LABELS: Record<Role, string> = {
  CLIENT: "Client",
  PROJECT_MANAGER: "Project Manager",
  CONTRACTOR: "Contractor",
  SITE_ENGINEER: "Site Engineer",
  SITE_OPERATIVES: "Site Operatives",
  PLANNER: "Planner / Project Controls",
  DISCIPLINE_ENGINEER: "Discipline Engineer",
  FIELD: "Site Operatives (Legacy)",
  PM: "Project Manager (Legacy)",
};

/**
 * Where each role lands after login — the first real screen is always the
 * user's actual work, never a welcome page.
 *
 * Field users land on their submission screen (Phase 3), planners on the
 * review queue (Phase 8) where their decisions live, and the PM on the
 * roll-up dashboard (Phase 10) that reports what everyone decided.
 */
const HOME_BY_ROLE: Record<Role, string> = {
  CLIENT: "/dashboard",
  PROJECT_MANAGER: "/dashboard",
  CONTRACTOR: "/",
  SITE_ENGINEER: "/queue",
  SITE_OPERATIVES: "/submit",
  PLANNER: "/queue",
  DISCIPLINE_ENGINEER: "/queue",
  FIELD: "/submit",
  PM: "/dashboard",
};

export function landingPathFor(role: Role): string {
  return HOME_BY_ROLE[role] ?? "/";
}

interface AuthState {
  user: User | null;
  token: string | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // Read persisted session once on the client, after hydration — reading
  // client-only storage in state initializers would mismatch server HTML.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- hydration-safe read of client-only storage */
    const auth = storedAuth();
    if (auth) {
      setUser(auth.user);
      setToken(auth.token);
    }
    setReady(true);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<User> => {
    // allow401: a wrong password must surface as a form error, not a redirect
    const res = await apiPostJson<TokenResponse>(
      "/api/auth/login",
      { email, password },
      true,
    );
    localStorage.setItem(
      AUTH_KEY,
      JSON.stringify({ token: res.access_token, user: res.user }),
    );
    setUser(res.user);
    setToken(res.access_token);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    try {
      localStorage.removeItem(AUTH_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
    setToken(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, token, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
