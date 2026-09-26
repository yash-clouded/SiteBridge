"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiGet,
  apiPostForm,
  apiPostJson,
  ApiError,
  fetchReports,
  type Project,
  type ReportListItem,
  type ReportOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";

type Mode = "text" | "file";
type TextSource = "text" | "voice" | "dpr";

/** Which rung extracted it (Phase 11) — a label, never colour alone. */
function extractionLabel(r: ReportListItem): { text: string; className: string } {
  if (r.extracted_by) {
    if (r.extracted_by.startsWith("heuristic")) {
      return { text: "Pattern (no LLM)", className: "text-status-pending" };
    }
    return { text: r.extracted_by, className: "text-muted" };
  }
  if (r.extraction_status === "failed") return { text: "Failed", className: "text-status-rejected" };
  if (r.extraction_status === "disabled") return { text: "Not extracted", className: "text-muted" };
  return { text: "Pending", className: "text-muted" };
}

const OUTCOME_LABELS: Record<string, string> = {
  PENDING: "Awaiting decision",
  NEEDS_MANUAL: "Needs manual mapping",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

const OUTCOME_STYLE: Record<string, string> = {
  PENDING: "text-status-pending",
  NEEDS_MANUAL: "text-status-corrected",
  APPROVED: "text-status-approved",
  REJECTED: "text-status-rejected",
};

/** Sarvam translate languages (23) — "auto" runs /text-lid detection first. */
const LANGUAGES: { value: string; label: string }[] = [
  { value: "auto", label: "Auto-detect" },
  { value: "hi-IN", label: "Hindi" },
  { value: "bn-IN", label: "Bengali" },
  { value: "ta-IN", label: "Tamil" },
  { value: "te-IN", label: "Telugu" },
  { value: "mr-IN", label: "Marathi" },
  { value: "gu-IN", label: "Gujarati" },
  { value: "kn-IN", label: "Kannada" },
  { value: "ml-IN", label: "Malayalam" },
  { value: "pa-IN", label: "Punjabi" },
  { value: "od-IN", label: "Odia" },
  { value: "ur-IN", label: "Urdu" },
  { value: "as-IN", label: "Assamese" },
  { value: "ne-IN", label: "Nepali" },
  { value: "mai-IN", label: "Maithili" },
  { value: "kok-IN", label: "Konkani" },
  { value: "sd-IN", label: "Sindhi" },
  { value: "sa-IN", label: "Sanskrit" },
  { value: "sat-IN", label: "Santali" },
  { value: "ks-IN", label: "Kashmiri" },
  { value: "brx-IN", label: "Bodo" },
  { value: "doi-IN", label: "Dogri" },
  { value: "mni-IN", label: "Manipuri" },
  { value: "en-IN", label: "English" },
];

function langShort(code: string | null): string {
  return code ? code.split("-")[0] : "—";
}

/** Translation outcome as a label — never colour alone (Phase 7 discipline). */
function translationChip(r: ReportListItem): {
  text: string;
  className: string;
  title?: string;
} {
  switch (r.translation_status) {
    case "translated":
      return {
        text: `${langShort(r.language_code)} → en`,
        className: "text-accent",
        title: `Translated by ${r.translation_model ?? "Sarvam"} before extraction`,
      };
    case "skipped":
      return {
        text: `${langShort(r.language_code)} · English`,
        className: "text-muted",
        title: "Already English — nothing to translate",
      };
    case "failed":
      return {
        text: "Translation failed",
        className: "text-status-pending",
        title: r.translation_error ?? "Extracted from the text as submitted",
      };
    case "disabled":
      return {
        text: "—",
        className: "text-muted",
        title: "Translation is not configured (SARVAM_API_KEY unset)",
      };
    default:
      return { text: "—", className: "text-muted" };
  }
}

const SOURCE_LABELS: Record<string, string> = {
  text: "Typed note",
  voice: "Voice transcript",
  dpr: "DPR note",
  txt: "Text file",
  excel: "Spreadsheet",
  pdf: "PDF",
};

/** Human-readable evidence pointer, e.g. "DPR · rows 1–14", "p. 2". */
function formatPointer(r: ReportOut): string {
  const p = r.pointer ?? {};
  if (typeof p.page_offsets === "object" && Array.isArray(p.pages)) {
    const pages = p.pages as number[];
    return pages.length === 1 ? `page ${pages[0]}` : `pages ${pages[0]}–${pages[pages.length - 1]}`;
  }
  if (Array.isArray(p.sheets)) {
    const sheets = p.sheets as { sheet: string; start: number; end: number }[];
    if (sheets.length === 1) {
      return `${sheets[0].sheet} · rows ${sheets[0].start}–${sheets[0].end}`;
    }
    if (sheets.length > 1) {
      return `${sheets.map((s) => s.sheet).join(", ")} · ${sheets.length} tabs`;
    }
  }
  if (typeof p.sheet === "string") {
    const rows = p.rows as { start?: number; end?: number } | undefined;
    if (rows?.start != null && rows?.end != null) {
      return `${p.sheet} · rows ${rows.start}–${rows.end}`;
    }
    return `${p.sheet}`;
  }
  if (typeof p.timestamp === "string") return `at ${p.timestamp.slice(11, 19)} UTC`;
  if (typeof p.day === "string") return `day ${p.day}`;
  if (typeof p.chars === "number") return `${p.chars} chars`;
  return "—";
}

function preview(text: string, n = 90): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > n ? `${flat.slice(0, n)}…` : flat;
}

export default function SubmitPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [reports, setReports] = useState<ReportListItem[] | null>(null);
  const [newestId, setNewestId] = useState<number | null>(null);

  const [mode, setMode] = useState<Mode>("text");
  const [source, setSource] = useState<TextSource>("text");
  const [language, setLanguage] = useState<string>("auto");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Project[]>("/api/projects")
      .then((list) => {
        setProjects(list);
        if (list.length > 0) setProjectId(list[0].id);
      })
      .catch(() => setProjects([]));
    fetchReports()
      .then(setReports)
      .catch(() => setReports([]));
  }, []);

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? null,
    [projects, projectId],
  );

  /** Re-read the list so the outcome columns reflect the run that just happened. */
  function record(report: ReportOut) {
    setNewestId(report.id);
    fetchReports()
      .then(setReports)
      .catch(() => {
        /* keep the current list — the submission itself already succeeded */
      });
  }

  async function submitText(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId) return;
    setSubmitting(true);
    setError(null);
    try {
      const pointer: Record<string, unknown> =
        source === "voice"
          ? { timestamp: new Date().toISOString() }
          : source === "dpr"
            ? { day: new Date().toISOString().slice(0, 10) }
            : {};
      const report = await apiPostJson<ReportOut>("/api/reports/text", {
        project_id: projectId,
        raw_text: text,
        source_type: source,
        pointer,
        language,
      });
      record(report);
      setText("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitFile(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !file) return;
    setSubmitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("project_id", String(projectId));
      const report = await apiPostForm<ReportOut>("/api/reports/file", form);
      record(report);
      setFile(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (user && user.role !== "FIELD") {
    return (
      <Shell title="Submit update">
        <p className="text-[13px] text-muted">
          Submissions are made from the field — this screen is for Field Users.
        </p>
      </Shell>
    );
  }

  return (
    <Shell title="Submit update" subtitle={project ? `${project.code} — ${project.name}` : undefined}>
      <div className="mx-auto max-w-5xl space-y-5">
        {/* New submission */}
        <section className="rounded-md border border-line bg-surface">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="text-[13px] font-medium">New field report</span>
            <label className="flex items-center gap-2 text-[12px] text-muted">
              Project
              <select
                value={projectId ?? ""}
                onChange={(e) => setProjectId(Number(e.target.value))}
                className="rounded border border-line bg-surface px-2 py-1 text-[13px] text-ink"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} — {p.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="border-b border-line px-4 pt-2">
            <div className="flex gap-4 text-[13px]">
              {(["text", "file"] as Mode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`border-b-2 px-1 pb-2 transition-colors ${
                    mode === m
                      ? "border-accent font-medium text-accent"
                      : "border-transparent text-muted hover:text-ink"
                  }`}
                >
                  {m === "text" ? "Type / transcript" : "Upload file"}
                </button>
              ))}
            </div>
          </div>

          {mode === "text" ? (
            <form onSubmit={submitText} className="px-4 py-3">
              <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-muted">
                <label className="flex items-center gap-2">
                  Source
                  <select
                    value={source}
                    onChange={(e) => setSource(e.target.value as TextSource)}
                    className="rounded border border-line bg-surface px-2 py-1 text-[13px] text-ink"
                  >
                    <option value="text">Typed note</option>
                    <option value="voice">Voice transcript (transcribed upstream)</option>
                    <option value="dpr">DPR note</option>
                  </select>
                </label>
                <label className="flex items-center gap-2">
                  Language
                  <select
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="rounded border border-line bg-surface px-2 py-1 text-[13px] text-ink"
                  >
                    {LANGUAGES.map((l) => (
                      <option key={l.value} value={l.value}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-muted">
                  Non-English text is translated to English before extraction.
                </span>
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
                rows={5}
                placeholder="e.g. Installed 24-inch spool pieces in rack bays 1 to 3, Area B. Hydrotest scheduled next week."
                className="block w-full resize-y rounded border border-line bg-surface px-2.5 py-2 text-[13px] leading-5 placeholder:text-muted"
              />
              <div className="mt-3 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={submitting || !text.trim()}
                  className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover disabled:bg-line disabled:text-muted"
                >
                  {submitting ? "Submitting…" : "Submit report"}
                </button>
                {error ? <span className="text-[12px] text-status-rejected">{error}</span> : null}
              </div>
            </form>
          ) : (
            <form onSubmit={submitFile} className="px-4 py-3">
              <input
                type="file"
                accept=".txt,.csv,.log,.xlsx,.xls,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded border border-line bg-surface px-2 py-1.5 text-[13px] file:mr-3 file:rounded file:border-0 file:bg-page file:px-2 file:py-1 file:text-[12px] file:text-muted"
              />
              <p className="mt-1.5 text-[12px] text-muted">
                PDF, Excel or text. Evidence pointer (page / sheet rows) is stored with the raw input.
              </p>
              <div className="mt-3 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={submitting || !file}
                  className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover disabled:bg-line disabled:text-muted"
                >
                  {submitting ? "Uploading…" : "Upload report"}
                </button>
                {error ? <span className="text-[12px] text-status-rejected">{error}</span> : null}
              </div>
            </form>
          )}
        </section>

        {/* My submissions — evidence-backed history (status column joins Phase 4) */}
        <section className="overflow-hidden rounded-md border border-line bg-surface">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            My submissions
          </div>
          {!reports ? (
            <p className="px-4 py-3 text-[13px] text-muted">Loading…</p>
          ) : reports.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-muted">No submissions yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1240px] text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-page text-left text-[12px] text-muted">
                    <th className="px-4 py-2 font-medium">Time</th>
                    <th className="px-3 py-2 font-medium">Source</th>
                    <th className="px-3 py-2 font-medium">Evidence</th>
                    <th className="px-3 py-2 font-medium">Preview</th>
                    <th className="px-3 py-2 font-medium">Language</th>
                    <th className="px-3 py-2 font-medium">Extraction</th>
                    <th className="px-4 py-2 font-medium">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr
                      key={r.id}
                      className={`border-b border-line last:border-0 ${
                        r.id === newestId ? "row-in" : ""
                      }`}
                    >
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-muted">
                        {SOURCE_LABELS[r.source_type] ?? r.source_type}
                      </td>
                      <td className="px-3 py-2 text-muted">
                        {r.filename ? <span className="text-ink">{r.filename}</span> : null}
                        {r.filename ? <span className="text-muted"> · </span> : null}
                        {formatPointer(r)}
                      </td>
                      <td className="max-w-[380px] truncate px-3 py-2 text-muted">
                        {preview(r.raw_text)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span
                          className={translationChip(r).className}
                          title={translationChip(r).title}
                        >
                          {translationChip(r).text}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span className={extractionLabel(r).className}>
                          {extractionLabel(r).text}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        {!r.review_status ? (
                          <span className="text-muted">—</span>
                        ) : (
                          <span className={OUTCOME_STYLE[r.review_status] ?? "text-muted"}>
                            {OUTCOME_LABELS[r.review_status] ?? r.review_status}
                            {r.mapped_activity ? (
                              <span className="block max-w-[260px] truncate text-[12px] text-muted">
                                {r.mapped_activity}
                              </span>
                            ) : null}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </Shell>
  );
}
