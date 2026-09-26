"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  fetchProjects,
  fetchRollup,
  type Project,
  type RollupBucket,
  type RollupOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";

type Tab = "by_wbs" | "by_area" | "by_discipline";

const TABS: { key: Tab; label: string }[] = [
  { key: "by_wbs", label: "WBS branch" },
  { key: "by_area", label: "Area" },
  { key: "by_discipline", label: "Discipline" },
];

function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function percent(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-line bg-panel px-4 py-3">
      <div className="text-[12px] text-ink-2">{label}</div>
      <div className="mt-1 text-[26px] font-semibold leading-7 tabular-nums text-ink">{value}</div>
      <div className="mt-1 text-[12px] leading-4 text-ink-3">{hint}</div>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [rollup, setRollup] = useState<RollupOut | null>(null);
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("by_wbs");

  useEffect(() => {
    let cancelled = false;
    fetchProjects()
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
        if (list[0]) setProjectId(list[0].id);
      })
      .catch(() => {
        if (!cancelled) setProjects([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (projectId == null) return undefined;
    let cancelled = false;
    fetchRollup(projectId)
      .then((resolved) => {
        if (cancelled) return;
        setRollup(resolved);
        setLoadedFor(projectId);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? null,
    [projects, projectId],
  );
  const loading = projectId != null && loadedFor !== projectId;
  const buckets: RollupBucket[] = rollup ? rollup[tab] : [];
  const seriesMax = Math.max(1, ...(rollup?.series.map((p) => p.approved) ?? [0]));

  if (user && user.role !== "PM") {
    return (
      <Shell title="Work progress">
        <p className="text-[13px] text-ink-2">
          The roll-up dashboard reports the whole project — it is for the PM role.
          {user.role === "PLANNER" ? " Your decisions live in the review queue." : ""}
        </p>
      </Shell>
    );
  }

  return (
    <Shell
      title="Roll-up dashboard"
      subtitle={project ? `${project.code} — ${project.name}` : undefined}
    >
      <div className="mx-auto max-w-6xl space-y-5">
        <section className="flex items-center justify-between rounded-md border border-line bg-panel px-4 py-2.5">
          <span className="text-[13px] font-medium">Project roll-up</span>
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
        </section>

        {projects.length === 0 ? (
          <section className="rounded-md border border-line bg-panel px-4 py-6 text-[13px] text-ink-3">
            No schedule imported yet.{" "}
            <Link href="/" className="text-accent underline-offset-2 hover:underline">
              Import one
            </Link>{" "}
            to see coverage, progress and approvals.
          </section>
        ) : error ? (
          <section className="rounded-md border border-line bg-red-bg px-4 py-3 text-[13px] text-red">
            {error}
          </section>
        ) : !rollup || loading ? (
          <section className="rounded-md border border-line bg-panel px-4 py-3 text-[13px] text-ink-3">
            Loading roll-up…
          </section>
        ) : (
          <>
            {/* Headline numbers */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                label="Schedule coverage"
                value={pct(rollup.coverage)}
                hint={`${rollup.reported} of ${rollup.activities} activities carry approved evidence`}
              />
              <Kpi
                label="Average progress"
                value={percent(rollup.avg_progress)}
                hint={
                  rollup.avg_progress == null
                    ? "No reported activity states a percentage"
                    : "Mean over reported activities that state progress"
                }
              />
              <Kpi
                label="Awaiting decision"
                value={rollup.pending_review}
                hint={`${rollup.needs_manual} flagged for manual mapping`}
              />
              <Kpi
                label="Approved"
                value={rollup.approved}
                hint={`${rollup.rejected} rejected`}
              />
            </div>

            {/* Coverage bar — labelled, never colour alone */}
            <section className="rounded-md border border-line bg-panel px-4 py-3">
              <div className="mb-2 flex items-center justify-between text-[12px]">
                <span className="font-medium text-ink">Reported vs. untouched</span>
                <span className="text-ink-3">
                  {rollup.reported} reported · {rollup.activities - rollup.reported} not reported
                </span>
              </div>
              <div className="flex h-3 overflow-hidden rounded-sm border border-line-2 bg-panel-2">
                <div
                  className="bg-accent"
                  style={{
                    width: `${Math.max(rollup.coverage * 100, rollup.reported > 0 ? 2 : 0)}%`,
                  }}
                  title={`${rollup.reported} reported`}
                />
              </div>
              <p className="mt-1.5 text-[12px] text-ink-3">
                An activity without approved evidence is <span className="text-ink-2">unreported</span>,
                never 0% complete.
              </p>
            </section>

            <div className="grid gap-5 lg:grid-cols-2">
              {/* Approvals over time */}
              <section className="overflow-hidden rounded-md border border-line bg-panel">
                <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
                  Approvals per day
                </div>
                {rollup.series.length === 0 ? (
                  <p className="px-4 py-3 text-[13px] text-ink-3">
                    No approvals yet — approve a report in the{" "}
                    <Link href="/queue" className="text-accent underline-offset-2 hover:underline">
                      review queue
                    </Link>
                    .
                  </p>
                ) : (
                  <ul className="divide-y divide-line">
                    {rollup.series.map((point) => (
                      <li key={point.day} className="flex items-center gap-3 px-4 py-2 text-[13px]">
                        <span className="w-20 shrink-0 text-ink-2">{dayLabel(point.day)}</span>
                        <span className="h-2.5 rounded-sm bg-accent" style={{ width: `${(point.approved / seriesMax) * 70}%` }} />
                        <span className="tabular-nums text-ink">{point.approved}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Review pipeline */}
              <section className="overflow-hidden rounded-md border border-line bg-panel">
                <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
                  Review pipeline
                </div>
                <ul className="divide-y divide-line text-[13px]">
                  {[
                    ["Awaiting decision", rollup.pending_review],
                    ["Needs manual mapping", rollup.needs_manual],
                    ["Approved", rollup.approved],
                    ["Rejected", rollup.rejected],
                  ].map(([label, count]) => (
                    <li key={String(label)} className="flex items-center justify-between px-4 py-2">
                      <span className="text-ink-2">{label}</span>
                      <span className="tabular-nums font-medium text-ink">{count}</span>
                    </li>
                  ))}
                </ul>
                <p className="border-t border-line px-4 py-2 text-[12px] text-ink-3">
                  Counts come from execution events — a report with no event yet is not in the
                  pipeline.
                </p>
              </section>
            </div>

            {/* Breakdowns */}
            <section className="overflow-hidden rounded-md border border-line bg-panel">
              <div className="flex items-center justify-between border-b border-line px-4 py-2">
                <span className="text-[13px] font-medium">Where the work is</span>
                <div className="flex gap-3 text-[13px]">
                  {TABS.map((item) => (
                    <button
                      key={item.key}
                      onClick={() => setTab(item.key)}
                      className={`border-b-2 px-1 pb-1 transition-colors ${
                        tab === item.key
                          ? "border-accent font-medium text-accent"
                          : "border-transparent text-ink-2 hover:text-ink"
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              {buckets.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-ink-3">Nothing to break down yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-[13px]">
                    <thead>
                      <tr className="border-b border-line bg-panel-2 text-left text-[12px] text-ink-2">
                        <th className="px-4 py-2 font-medium">
                          {tab === "by_wbs" ? "Branch" : tab === "by_area" ? "Area" : "Discipline"}
                        </th>
                        <th className="px-3 py-2 text-right font-medium">Activities</th>
                        <th className="px-3 py-2 text-right font-medium">Reported</th>
                        <th className="px-3 py-2 text-right font-medium">Coverage</th>
                        <th className="px-3 py-2 text-right font-medium">Avg progress</th>
                        <th className="px-3 py-2 font-medium">Last update</th>
                        <th className="px-4 py-2 font-medium">Statuses</th>
                      </tr>
                    </thead>
                    <tbody>
                      {buckets.map((bucket) => (
                        <tr key={bucket.key || "—"} className="border-b border-line last:border-0">
                          <td className="max-w-[260px] truncate px-4 py-2 text-ink">
                            {bucket.key || <span className="text-ink-3">Not stated</span>}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-2">
                            {bucket.activities}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink">
                            {bucket.reported}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-2">
                            {bucket.activities ? pct(bucket.reported / bucket.activities) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-2">
                            {percent(bucket.avg_progress)}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-ink-2">
                            {bucket.last_update
                              ? new Date(`${bucket.last_update}T00:00:00`).toLocaleDateString()
                              : "—"}
                          </td>
                          <td className="px-4 py-2">
                            {Object.keys(bucket.by_status).length === 0 ? (
                              <span className="text-ink-3">—</span>
                            ) : (
                              <span className="flex flex-wrap gap-1">
                                {Object.entries(bucket.by_status).map(([label, count]) => (
                                  <span
                                    key={label}
                                    className="rounded border border-line-2 bg-panel-2 px-1.5 py-0.5 text-[11px] text-ink-2"
                                  >
                                    {label}: {count}
                                  </span>
                                ))}
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

            <p className="text-[12px] text-ink-3">
              Reported = an activity with approved evidence (Phase 8). Progress is averaged over
              reported activities that state a value, and stays blank when none does.
            </p>
          </>
        )}
      </div>
    </Shell>
  );
}
