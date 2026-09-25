/** API client for the SiteBridge backend — attaches the JWT from storage. */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const AUTH_KEY = "sitebridge_auth";

export type Role = "FIELD" | "PLANNER" | "PM";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export function storedAuth(): { token: string; user: User } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.token && parsed?.user ? parsed : null;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const auth = storedAuth();
  return auth ? { Authorization: `Bearer ${auth.token}` } : {};
}

async function handle<T>(resp: Response, allow401 = false): Promise<T> {
  if (!resp.ok) {
    let message = resp.statusText;
    try {
      const body = await resp.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    if (resp.status === 401 && !allow401) {
      // token missing/expired — return to the login screen
      try {
        localStorage.removeItem(AUTH_KEY);
      } catch {
        /* ignore */
      }
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        // Full reload on credential loss — wipes all in-memory state; this
        // module has no access to the Next router.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign("/login");
      }
    }
    throw new ApiError(resp.status, message);
  }
  return resp.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  return handle<T>(resp);
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  return handle<T>(resp);
}

export async function apiPostJson<T>(path: string, body: unknown, allow401 = false): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handle<T>(resp, allow401);
}

/* ---- Phase 1 types ---- */

export interface Project {
  id: number;
  code: string;
  name: string;
  source_filename: string | null;
  imported_at: string;
  level_count: number;
  level_names: string[];
  weighting_field: string | null;
  node_count: number;
  leaf_count: number;
}

export interface WbsNode {
  id: number;
  project_id: number;
  parent_id: number | null;
  code: string;
  name: string;
  level: number;
  level_name: string;
  is_leaf: boolean;
  planned_start: string | null;
  planned_finish: string | null;
  weight: number | null;
  discipline: string | null;
  area: string | null;
  equipment_tag: string | null;
  predecessor_ids: string[];
  successor_ids: string[];
}

export interface ImportResponse {
  project: Project;
  message: string;
}
