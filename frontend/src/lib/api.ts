/** Minimal API client for the SiteBridge backend (Phase 1). */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let message = resp.statusText;
    try {
      const body = await resp.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, message);
  }
  return resp.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  return handle<T>(resp);
}

export async function apiPostForm<T>(
  path: string,
  form: FormData,
): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, { method: "POST", body: form });
  return handle<T>(resp);
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
