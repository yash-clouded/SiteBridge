"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, apiPostForm, ApiError, type ImportResponse, type Project } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";
import { WorkstationShowcase } from "@/components/WorkstationShowcase";

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
    <Shell title="SiteBridge Workstation" subtitle="Integrated project controls interface">
      <WorkstationShowcase />

      {user?.role === "PLANNER" ? (
        <section className="mx-auto mt-6 max-w-6xl rounded-[2px] border border-slate-300 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-2.5">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-900">Import schedule</h2>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Load a new CSV/Excel schedule into the project controls workspace.
            </p>
          </div>
          <form action={submitImport} className="flex flex-wrap items-end gap-3 p-4">
            <label className="block min-w-[220px] flex-1">
              <span className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Schedule file</span>
              <input
                type="file"
                name="file"
                accept=".csv,.xlsx,.xls"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded-[2px] border border-slate-300 bg-white px-2 py-1.5 text-[11px] text-slate-700 file:mr-3 file:rounded-[2px] file:border-0 file:bg-slate-100 file:px-2 file:py-1 file:text-[10px]"
              />
            </label>
            <label className="block w-32">
              <span className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Code</span>
              <input
                name="project_code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                placeholder="NPU"
                className="block w-full rounded-[2px] border border-slate-300 px-2 py-1.5 text-[11px] uppercase outline-none focus:border-[#0d6efd]"
              />
            </label>
            <label className="block min-w-[220px] flex-1">
              <span className="mb-1 block text-[10px] font-bold uppercase text-slate-500">Project name</span>
              <input
                name="project_name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="North Plant Utilities Upgrade"
                className="block w-full rounded-[2px] border border-slate-300 px-2 py-1.5 text-[11px] outline-none focus:border-[#0d6efd]"
              />
            </label>
            <button
              type="submit"
              disabled={importing || !file}
              className="rounded-[2px] bg-[#0d6efd] px-3.5 py-2 text-[11px] font-bold uppercase tracking-wide text-white hover:bg-[#0b5ed7] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {importing ? "Importing…" : "Import Schedule"}
            </button>
            {formError ? <p className="w-full text-[11px] text-red-700">{formError}</p> : null}
          </form>
        </section>
      ) : null}

      <div className="mt-6">
        <section className="mx-auto max-w-6xl overflow-hidden rounded-md border border-line bg-panel">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            Imported schedules
          </div>
          {error ? (
            <p className="px-4 py-3 text-[13px] text-red">{error}</p>
          ) : projects === null ? (
            <p className="px-4 py-3 text-[13px] text-ink-3">Loading…</p>
          ) : projects.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-ink-3">No schedules imported yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-panel-2 text-left text-[12px] text-ink-2">
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
                    <tr key={p.id} className="cursor-pointer border-b border-line last:border-0 hover:bg-panel-2" onClick={() => router.push(`/projects/${p.id}`)}>
                      <td className="px-4 py-2 font-medium">{p.code}</td>
                      <td className="px-3 py-2">{p.name}</td>
                      <td className="px-3 py-2 text-ink-2">{p.level_count} <span className="text-ink-3">({p.level_names.join(" › ")})</span></td>
                      <td className="px-3 py-2 text-right tabular-nums">{p.node_count}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{p.leaf_count}</td>
                      <td className="px-3 py-2 text-ink-2">{p.weighting_field ?? "—"}</td>
                      <td className="px-3 py-2 text-ink-2">{p.source_filename ?? "—"}</td>
                      <td className="px-3 py-2 text-ink-2">{new Date(p.imported_at).toLocaleString()}</td>
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
