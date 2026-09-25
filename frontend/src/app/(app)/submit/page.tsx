"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiGet,
  apiPostForm,
  apiPostJson,
  ApiError,
  type Project,
  type ReportOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";

type Mode = "text" | "file";
type TextSource = "text" | "voice" | "dpr";

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
  const [reports, setReports] = useState<ReportOut[] | null>(null);
  const [newestId, setNewestId] = useState<number | null>(null);

  const [mode, setMode] = useState<Mode>("text");
  const [source, setSource] = useState<TextSource>("text");
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
    apiGet<ReportOut[]>("/api/reports")
      .then(setReports)
      .catch(() => setReports([]));
  }, []);

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? null,
    [projects, projectId],
  );

  function record(report: ReportOut) {
    setReports((prev) => [report, ...(prev ?? [])]);
    setNewestId(report.id);
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
        <p className="text-[13px] text-ink-2">
          Submissions are made from the field — this screen is for Field Users.
        </p>
      </Shell>
    );
  }

  return (
    <Shell title="Submit update" subtitle={project ? `${project.code} — ${project.name}` : undefined}>
      <div className="mx-auto max-w-5xl space-y-5">
        {/* New submission */}
        <section className="rounded-md border border-line bg-panel">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="text-[13px] font-medium">New field report</span>
            <label className="flex items-center gap-2 text-[12px] text-ink-2">
              Project
              <select
                value={projectId ?? ""}
                onChange={(e) => setProjectId(Number(e.target.value))}
                className="rounded border border-line-2 bg-panel px-2 py-1 text-[13px] text-ink"
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
                      : "border-transparent text-ink-2 hover:text-ink"
                  }`}
                >
                  {m === "text" ? "Type / transcript" : "Upload file"}
                </button>
              ))}
            </div>
          </div>

          {mode === "text" ? (
            <form onSubmit={submitText} className="px-4 py-3">
              <div className="mb-2 flex items-center gap-2 text-[12px] text-ink-2">
                Source
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value as TextSource)}
                  className="rounded border border-line-2 bg-panel px-2 py-1 text-[13px] text-ink"
                >
                  <option value="text">Typed note</option>
                  <option value="voice">Voice transcript (transcribed upstream)</option>
                  <option value="dpr">DPR note</option>
                </select>
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
                rows={5}
                placeholder="e.g. Installed 24-inch spool pieces in rack bays 1 to 3, Area B. Hydrotest scheduled next week."
                className="block w-full resize-y rounded border border-line-2 bg-panel px-2.5 py-2 text-[13px] leading-5 placeholder:text-ink-3"
              />
              <div className="mt-3 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={submitting || !text.trim()}
                  className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
                >
                  {submitting ? "Submitting…" : "Submit report"}
                </button>
                {error ? <span className="text-[12px] text-red">{error}</span> : null}
              </div>
            </form>
          ) : (
            <form onSubmit={submitFile} className="px-4 py-3">
              <input
                type="file"
                accept=".txt,.csv,.log,.xlsx,.xls,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded border border-line-2 bg-panel px-2 py-1.5 text-[13px] file:mr-3 file:rounded file:border-0 file:bg-surface file:px-2 file:py-1 file:text-[12px] file:text-ink-2"
              />
              <p className="mt-1.5 text-[12px] text-ink-3">
                PDF, Excel or text. Evidence pointer (page / sheet rows) is stored with the raw input.
              </p>
              <div className="mt-3 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={submitting || !file}
                  className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
                >
                  {submitting ? "Uploading…" : "Upload report"}
                </button>
                {error ? <span className="text-[12px] text-red">{error}</span> : null}
              </div>
            </form>
          )}
        </section>

        {/* My submissions — evidence-backed history (status column joins Phase 4) */}
        <section className="overflow-hidden rounded-md border border-line bg-panel">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            My submissions
          </div>
          {!reports ? (
            <p className="px-4 py-3 text-[13px] text-ink-3">Loading…</p>
          ) : reports.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-ink-3">No submissions yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-panel-2 text-left text-[12px] text-ink-2">
                    <th className="px-4 py-2 font-medium">Time</th>
                    <th className="px-3 py-2 font-medium">Source</th>
                    <th className="px-3 py-2 font-medium">Evidence</th>
                    <th className="px-3 py-2 font-medium">Preview</th>
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
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums text-ink-2">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-ink-2">
                        {SOURCE_LABELS[r.source_type] ?? r.source_type}
                      </td>
                      <td className="px-3 py-2 text-ink-2">
                        {r.filename ? <span className="text-ink">{r.filename}</span> : null}
                        {r.filename ? <span className="text-ink-3"> · </span> : null}
                        {formatPointer(r)}
                      </td>
                      <td className="max-w-[380px] truncate px-3 py-2 text-ink-2">
                        {preview(r.raw_text)}
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
