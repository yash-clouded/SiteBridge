"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet, type Project, type WbsNode } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { WbsBrowser } from "@/components/WbsBrowser";

export default function ProjectWbsPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [nodes, setNodes] = useState<WbsNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      apiGet<Project[]>("/api/projects").then(
        (list) => list.find((p) => String(p.id) === String(id)) ?? null,
      ),
      apiGet<WbsNode[]>(`/api/projects/${id}/wbs`),
    ])
      .then(([p, n]) => {
        if (!p) {
          setError("Project not found.");
          return;
        }
        setProject(p);
        setNodes(n);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <Shell title="Work breakdown structure">
        <p className="text-[13px] text-status-rejected">{error}</p>
      </Shell>
    );
  }

  if (!project || !nodes) {
    return (
      <Shell title="Work breakdown structure">
        <p className="text-[13px] text-muted">Loading…</p>
      </Shell>
    );
  }

  return (
    <Shell title="Work breakdown structure" subtitle={`${project.code} — ${project.name}`}>
      <div className="mx-auto max-w-7xl space-y-4">
        {/* Project meta strip — level structure is data, read from the import */}
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-[13px]">
          <span className="text-muted">
            <span className="font-medium text-ink">{project.level_count} levels</span>{" "}
            {project.level_names.map((n, i) => (
              <span key={n}>
                {i > 0 ? <span className="text-muted"> › </span> : null}
                {n}
              </span>
            ))}
          </span>
          <span className="text-muted">
            <span className="tabular-nums font-medium text-ink">{project.node_count}</span> nodes
          </span>
          <span className="text-muted">
            <span className="tabular-nums font-medium text-ink">{project.leaf_count}</span> leaf activities
          </span>
          <span className="text-muted">
            weighting: <span className="text-ink">{project.weighting_field ?? "none"}</span>
          </span>
          <span className="text-muted">source: {project.source_filename}</span>
        </div>

        <WbsBrowser nodes={nodes} levelNames={project.level_names} />
      </div>
    </Shell>
  );
}
