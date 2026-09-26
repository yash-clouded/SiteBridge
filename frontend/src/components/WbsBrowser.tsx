"use client";

import { useMemo, useState } from "react";
import type { WbsNode } from "@/lib/api";

type View = "tree" | "table";
type SortKey = "code" | "level" | "planned_finish" | null;

const COLUMNS: { key: string; label: string; className?: string }[] = [
  { key: "code", label: "Code", className: "w-28" },
  { key: "name", label: "Name" },
  { key: "level", label: "Level", className: "w-36" },
  { key: "planned_start", label: "Planned start", className: "w-28" },
  { key: "planned_finish", label: "Planned finish", className: "w-28" },
  { key: "weight", label: "Weight", className: "w-20 text-right" },
  { key: "discipline", label: "Discipline", className: "w-24" },
  { key: "area", label: "Area", className: "w-24" },
  { key: "equipment_tag", label: "Tag", className: "w-24" },
];

/**
 * Dense tree/table browser for the imported WBS.
 * Tree view reflects the imported hierarchy (containers + leaf activities);
 * table view is the flat list with sorting. Level labels come from the
 * imported level names — never hardcoded.
 */
export function WbsBrowser({ nodes, levelNames }: { nodes: WbsNode[]; levelNames: string[] }) {
  const [view, setView] = useState<View>("tree");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>(null);
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  // Default: root and its children expanded, so the top-down structure reads immediately
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(nodes.filter((n) => n.level <= 2).map((n) => n.id)),
  );

  const childrenByParent = useMemo(() => {
    const map = new Map<number | null, WbsNode[]>();
    for (const n of nodes) {
      const list = map.get(n.parent_id) ?? [];
      list.push(n);
      map.set(n.parent_id, list);
    }
    return map;
  }, [nodes]);

  const q = query.trim().toLowerCase();
  const matches = (n: WbsNode) =>
    !q ||
    n.code.toLowerCase().includes(q) ||
    n.name.toLowerCase().includes(q) ||
    (n.discipline ?? "").toLowerCase().includes(q) ||
    (n.area ?? "").toLowerCase().includes(q) ||
    (n.equipment_tag ?? "").toLowerCase().includes(q);

  /** Visible rows honoring expansion; while filtering, every match is shown. */
  const treeRows = useMemo(() => {
    const rows: { node: WbsNode; depth: number }[] = [];
    const walk = (parent: number | null, depth: number) => {
      for (const n of childrenByParent.get(parent) ?? []) {
        if (q) {
          // search descends everywhere so matches under non-matching
          // containers are still found
          if (matches(n)) rows.push({ node: n, depth });
          walk(n.id, depth + 1);
        } else {
          rows.push({ node: n, depth }); // reached => visible
          if (expanded.has(n.id)) walk(n.id, depth + 1);
        }
      }
    };
    walk(null, 0);
    return rows;
  }, [childrenByParent, expanded, q]); // eslint-disable-line react-hooks/exhaustive-deps

  const tableRows = useMemo(() => {
    let rows = q ? nodes.filter(matches) : [...nodes];
    if (sortKey) {
      rows = [...rows].sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
        return String(av).localeCompare(String(bv)) * sortDir;
      });
    }
    return rows;
  }, [nodes, q, sortKey, sortDir]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function sortBy(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(1);
    }
  }

  const hasChildren = (n: WbsNode) => (childrenByParent.get(n.id)?.length ?? 0) > 0;
  const rows = view === "tree" ? treeRows : tableRows;

  return (
    <section className="overflow-hidden rounded-md border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <div className="flex overflow-hidden rounded border border-line text-[13px]">
          <button
            onClick={() => setView("tree")}
            className={`px-3 py-1 transition-colors ${
              view === "tree" ? "bg-accent text-white" : "bg-surface text-muted hover:bg-page"
            }`}
          >
            Tree
          </button>
          <button
            onClick={() => setView("table")}
            className={`border-l border-line px-3 py-1 transition-colors ${
              view === "table" ? "bg-accent text-white" : "bg-surface text-muted hover:bg-page"
            }`}
          >
            Table
          </button>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by code, name, discipline, area, tag…"
          className="min-w-[180px] flex-1 rounded border border-line px-2.5 py-1 text-[13px] placeholder:text-muted sm:w-80 sm:flex-none"
        />
        <span className="ml-auto text-[12px] text-muted">
          {rows.length} of {nodes.length} nodes
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1060px] text-[13px]">
          <thead>
            <tr className="border-b border-line bg-page text-left text-[12px] text-muted">
              {COLUMNS.map((c) => {
                const sortable =
                  view === "table" && ["code", "level", "planned_finish"].includes(c.key);
                return (
                  <th
                    key={c.key}
                    className={`px-3 py-2 font-medium ${c.className ?? ""} ${
                      sortable ? "cursor-pointer select-none hover:text-ink" : ""
                    }`}
                    onClick={() => sortable && sortBy(c.key as SortKey)}
                  >
                    {c.label}
                    {sortable && sortKey === c.key ? (sortDir === 1 ? " ↑" : " ↓") : ""}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-6 text-center text-[13px] text-muted">
                  No nodes match “{query}”.
                </td>
              </tr>
            ) : view === "tree" ? (
              treeRows.map(({ node, depth }) => (
                <Row
                  key={node.id}
                  node={node}
                  depth={depth}
                  expandable={hasChildren(node)}
                  expanded={expanded.has(node.id)}
                  onToggle={() => toggle(node.id)}
                />
              ))
            ) : (
              tableRows.map((node) => (
                <Row
                  key={node.id}
                  node={node}
                  depth={node.level - 1}
                  expandable={false}
                  expanded={false}
                  onToggle={() => undefined}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line px-4 py-2 text-[12px] text-muted">
        Level structure as imported:{" "}
        {levelNames.map((n, i) => `L${i + 1} ${n}`).join("  ·  ")}
      </div>
    </section>
  );
}

function Row({
  node,
  depth,
  expandable,
  expanded,
  onToggle,
}: {
  node: WbsNode;
  depth: number;
  expandable: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <tr
      className={`border-b border-line last:border-0 ${
        node.is_leaf ? "hover:bg-page" : "bg-page"
      }`}
    >
      <td className="px-3 py-1.5">
        <span className="flex items-center gap-1.5" style={{ paddingLeft: depth * 18 }}>
          <button
            onClick={onToggle}
            disabled={!expandable}
            className={`flex h-4 w-4 items-center justify-center rounded-sm text-[10px] ${
              expandable ? "text-muted hover:bg-line" : "text-transparent"
            }`}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expandable ? (expanded ? "▾" : "▸") : "·"}
          </button>
          <span className={node.is_leaf ? "" : "font-medium"}>{node.code}</span>
        </span>
      </td>
      <td className={`px-3 py-1.5 ${node.is_leaf ? "" : "font-medium text-ink"}`}>
        {node.name}
        {!node.is_leaf ? <span className="ml-2 font-normal text-muted">{node.level_name}</span> : null}
      </td>
      <td className="px-3 py-1.5 text-muted">
        L{node.level} <span className="text-muted">{node.level_name}</span>
      </td>
      <td className="px-3 py-1.5 tabular-nums text-muted">{node.planned_start ?? "—"}</td>
      <td className="px-3 py-1.5 tabular-nums text-muted">{node.planned_finish ?? "—"}</td>
      <td className="px-3 py-1.5 text-right tabular-nums text-muted">{node.weight ?? "—"}</td>
      <td className="px-3 py-1.5 text-muted">{node.discipline ?? "—"}</td>
      <td className="px-3 py-1.5 text-muted">{node.area ?? "—"}</td>
      <td className="px-3 py-1.5 text-muted">{node.equipment_tag ?? "—"}</td>
    </tr>
  );
}
