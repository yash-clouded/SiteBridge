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

/* ---- Phase 3 types ---- */

export interface ReportOut {
  id: number;
  project_id: number;
  user_id: number;
  source_type: string; // text | voice | dpr | txt | excel | pdf
  raw_text: string;
  filename: string | null;
  pointer: Record<string, unknown>; // evidence pointer (page/row/timestamp)
  extraction_status: string; // pending | extracted | failed | disabled
  extraction_error: string | null;
  // Multilingual intake: raw_text is verbatim, translated_text is the
  // English rendering extraction read (null unless a translation happened).
  translation_status: string; // none | skipped | translated | failed | disabled
  language_code: string | null; // detected/declared source: "hi-IN"
  translated_text: string | null;
  translation_error: string | null;
  translation_model: string | null;
  created_at: string;
}

/* ---- Phases 4-7: events, candidates, confidence ---- */

export type ReviewStatus = "PENDING" | "NEEDS_MANUAL" | "APPROVED" | "REJECTED";
export type ConfidenceBand = "high" | "medium" | "low";
export type RuleResultValue = "pass" | "fail" | "unknown";

export interface ExecutionEvent {
  id: number;
  project_id: number;
  field_report_id: number;
  description: string | null;
  discipline: string | null;
  location: string | null;
  tag: string | null;
  event_date: string | null;
  status: string | null;
  quantity: number | null;
  progress: number | null;
  model: string | null;
  prompt_version: string;
  review_status: ReviewStatus;
  reviewed_at: string | null;
  reviewed_by: number | null;
  review_note: string | null;
  extracted_at: string;
  raw_model_response: string | null;
}

export interface ActivitySummary {
  id: number;
  code: string;
  name: string;
  level: number;
  level_name: string;
  discipline: string | null;
  area: string | null;
  equipment_tag: string | null;
  planned_start: string | null;
  planned_finish: string | null;
  // Phase 8: written by an approval; null = not reported / not approved
  actual_status: string | null;
  actual_progress: number | null;
  actual_date: string | null;
  actual_report_id: number | null;
}

export interface RuleCheck {
  rule: string;
  result: RuleResultValue;
  detail: string | null;
  wbs_node_id: number;
}

export interface ConfidenceBreakdown {
  final: number;
  band: ConfidenceBand;
  retrieval: number;
  rules: {
    score: number | null;
    pass: number;
    fail: number;
    unknown: number;
    decidable: number;
    total: number;
    weight: number;
  };
  formula: string;
}

export interface Candidate {
  id: number;
  rank: number;
  wbs_node_id: number;
  score: number;
  semantic_score: number;
  kg_score: number;
  breakdown: Record<string, unknown> & { confidence?: ConfidenceBreakdown };
  activity: ActivitySummary;
  rules: RuleCheck[];
  confidence_band: ConfidenceBand | null;
  approved: boolean;
}

export interface MatchOut {
  report: ReportOut;
  extraction_status: string;
  extraction_error: string | null;
  event: ExecutionEvent | null;
  candidates: Candidate[];
}

/** A submission plus its outcome (Phase 10): what happened to it. */
export interface ReportListItem extends ReportOut {
  review_status: ReviewStatus | null; // null = no event extracted yet
  extracted_by: string | null; // "heuristic-v1" | <model name>
  mapped_activity: string | null; // "A1011 — Excavate foundation ..."
}

/* ---- Phase 8: review queue ---- */

export interface QueueTop {
  candidate_id: number;
  wbs_node_id: number;
  score: number;
  confidence_band: ConfidenceBand | null;
  activity: ActivitySummary;
  rules: RuleCheck[];
}

export interface QueueItem {
  report: ReportOut;
  event: ExecutionEvent | null;
  review_status: ReviewStatus | null;
  top: QueueTop | null;
  candidate_count: number;
}

export interface QueueOut {
  project_id: number | null;
  items: QueueItem[];
  counts: Record<string, number>;
}

/* ---- Phase 9: roll-up ---- */

export interface RollupBucket {
  key: string;
  activities: number;
  reported: number;
  avg_progress: number | null;
  last_update: string | null;
  by_status: Record<string, number>;
}

export interface RollupSeriesPoint {
  day: string;
  approved: number;
}

export interface RollupOut {
  project_id: number;
  activities: number;
  reported: number;
  coverage: number;
  avg_progress: number | null;
  pending_review: number;
  needs_manual: number;
  approved: number;
  rejected: number;
  by_area: RollupBucket[];
  by_discipline: RollupBucket[];
  by_wbs: RollupBucket[];
  series: RollupSeriesPoint[];
  updated_at: string | null;
}

/* ---- Phase 11: runtime status ---- */

export interface SystemStatus {
  llm: {
    configured: boolean;
    model: string;
    endpoint: string;
    fallback_configured: boolean;
    fallback_model: string | null;
    rungs: string[];
  };
  embeddings: {
    provider: string;
    model: string;
    dim: number;
    input_type: boolean;
    fallback_local: boolean;
  };
  extraction: {
    mode: string; // llm | heuristic | disabled
    fallback: string;
    auto_on_intake: boolean;
  };
  translation: {
    on_intake: boolean;
    configured: boolean; // SARVAM_API_KEY present (never the key)
    model: string;
    target_language: string;
  };
  database: boolean;
  degraded: string[];
}

/* ---- Phase 4-8 actions ---- */

export function fetchQueue(params: { projectId?: number; filter?: string } = {}) {
  const query = new URLSearchParams();
  if (params.projectId != null) query.set("project_id", String(params.projectId));
  if (params.filter) query.set("filter", params.filter);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiGet<QueueOut>(`/api/queue${suffix}`);
}

export function fetchMatch(reportId: number) {
  return apiGet<MatchOut>(`/api/reports/${reportId}/match`);
}

export function approveReport(
  reportId: number,
  body: { candidate_id?: number; note?: string } = {},
) {
  return apiPostJson<MatchOut>(`/api/reports/${reportId}/approve`, body);
}

export function rejectReport(reportId: number, note?: string) {
  return apiPostJson<MatchOut>(`/api/reports/${reportId}/reject`, { note });
}

export function reopenReport(reportId: number, note?: string) {
  return apiPostJson<MatchOut>(`/api/reports/${reportId}/reopen`, { note });
}

export function processReport(reportId: number) {
  return apiPostJson<MatchOut>(`/api/reports/${reportId}/process`, {});
}

export function fetchRollup(projectId: number) {
  return apiGet<RollupOut>(`/api/projects/${projectId}/rollup`);
}

/* ---- Phase 10-11 actions ---- */

export function fetchProjects() {
  return apiGet<Project[]>("/api/projects");
}

export function fetchReports(projectId?: number) {
  const suffix = projectId != null ? `?project_id=${projectId}` : "";
  return apiGet<ReportListItem[]>(`/api/reports${suffix}`);
}

export function fetchStatus() {
  return apiGet<SystemStatus>("/api/status");
}
