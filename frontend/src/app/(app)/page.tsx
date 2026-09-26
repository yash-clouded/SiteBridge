"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, apiPostForm, ApiError, type ImportResponse, type Project } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";

export default function ProjectsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // import form state
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [importing, setImporting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Project[]>("/api/projects")
      .then(setProjects)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function submitImport(formData: FormData) {
    setImporting(true);
    setFormError(null);
    try {
      const res = await apiPostForm<ImportResponse>("/api/projects/import", formData);
      router.push(`/projects/${res.project.id}`);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Import failed.");
      setImporting(false);
    }
  }

  return (
    <Shell title="Projects">
      <div className="mx-auto max-w-6xl space-y-5">
        {/* Import panel — planner-only function (roles gate functions, not tree levels) */}
        {user?.role === "PLANNER" ? (
        <section className="rounded-md border border-line bg-surface">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            Import schedule
          </div>
          <form
            action={submitImport}
            className="flex flex-wrap items-end gap-3 px-4 py-3"
          >
            <label className="block min-w-[210px] flex-1 sm:flex-none sm:w-72">
              <span className="mb-1 block text-[12px] text-muted">Schedule file (CSV/Excel)</span>
              <input
                type="file"
                name="file"
                accept=".csv,.xlsx,.xls"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded border border-line bg-surface px-2 py-1.5 text-[13px] file:mr-3 file:rounded file:border-0 file:bg-page file:px-2 file:py-1 file:text-[12px] file:text-muted"
              />
            </label>
            <label className="block min-w-[150px] flex-1 sm:flex-none sm:w-36">
              <span className="mb-1 block text-[12px] text-muted">Project code</span>
              <input
                name="project_code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                placeholder="e.g. NPU"
                className="block w-full rounded border border-line bg-surface px-2 py-1.5 text-[13px] uppercase placeholder:normal-case placeholder:text-muted"
              />
            </label>
            <label className="block min-w-[200px] flex-1">
              <span className="mb-1 block text-[12px] text-muted">Project name</span>
              <input
                name="project_name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="e.g. North Plant Utilities Upgrade"
                className="block w-full rounded border border-line bg-surface px-2 py-1.5 text-[13px] placeholder:text-muted"
              />
            </label>
            <button
              type="submit"
              disabled={importing || !file}
              className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover disabled:bg-line disabled:text-muted"
            >
              {importing ? "Importing…" : "Import"}
            </button>
            {formError ? (
              <p className="w-full text-[12px] text-status-rejected">{formError}</p>
            ) : null}
          </form>
        </section>
        ) : null}

        {/* Project list */}
        <section className="overflow-hidden rounded-md border border-line bg-surface">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            Imported schedules
          </div>
          {error ? (
            <p className="px-4 py-3 text-[13px] text-status-rejected">{error}</p>
          ) : !projects ? (
            <p className="px-4 py-3 text-[13px] text-muted">Loading…</p>
          ) : projects.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-muted">
              No schedules imported yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[13px]">
              <thead>
                <tr className="border-b border-line bg-page text-left text-[12px] text-muted">
                  <th className="px-4 py-2 font-medium">Code</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Levels</th>
                  <th className="px-3 py-2 text-right font-medium">Nodes</th>
                  <th className="px-3 py-2 text-right font-medium">Activities</th>
                  <th className="px-3 py-2 font-medium">Weighting</th>
                  <th className="px-3 py-2 font-medium">Source file</th>
                  <th className="px-3 py-2 font-medium">Imported</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr
                    key={p.id}
                    className="cursor-pointer border-b border-line last:border-0 hover:bg-page"
                    onClick={() => router.push(`/projects/${p.id}`)}
                  >
                    <td className="px-4 py-2 font-medium">{p.code}</td>
                    <td className="px-3 py-2">{p.name}</td>
                    <td className="px-3 py-2 text-muted">
                      {p.level_count}{" "}
                      <span className="text-muted">({p.level_names.join(" › ")})</span>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.node_count}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.leaf_count}</td>
                    <td className="px-3 py-2 text-muted">{p.weighting_field ?? "—"}</td>
                    <td className="px-3 py-2 text-muted">{p.source_filename ?? "—"}</td>
                    <td className="px-3 py-2 text-muted">
                      {new Date(p.imported_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-accent">›</td>
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
