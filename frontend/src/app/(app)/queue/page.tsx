"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  approveReport,
  fetchMatch,
  fetchQueue,
  processReport,
  rejectReport,
  reopenReport,
  type Candidate,
  type ConfidenceBand,
  type MatchOut,
  type QueueItem,
  type QueueOut,
  type ReviewStatus,
  type RuleCheck,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/Shell";

type Filter = "all" | "pending" | "approved" | "rejected";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "pending", label: "Awaiting decision" },
  { key: "all", label: "All" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

const STATUS_LABELS: Record<ReviewStatus, string> = {
  PENDING: "Awaiting decision",
  NEEDS_MANUAL: "Needs manual mapping",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

const STATUS_STYLE: Record<ReviewStatus, string> = {
  PENDING: "border-status-pending/30 bg-status-pending-bg text-status-pending",
  NEEDS_MANUAL: "border-status-corrected/30 bg-status-corrected-bg text-status-corrected",
  APPROVED: "border-status-approved/30 bg-status-approved-bg text-status-approved",
  REJECTED: "border-status-rejected/30 bg-status-rejected-bg text-status-rejected",
};

const BAND_LABELS: Record<ConfidenceBand, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const BAND_STYLE: Record<ConfidenceBand, string> = {
  high: "border-status-approved/30 bg-status-approved-bg text-status-approved",
  medium: "border-status-neutral/30 bg-status-neutral-bg text-status-neutral",
  low: "border-status-pending/30 bg-status-pending-bg text-status-pending",
};

const RULE_STYLE: Record<RuleCheck["result"], string> = {
  pass: "border-status-approved/30 bg-status-approved-bg text-status-approved",
  fail: "border-status-rejected/30 bg-status-rejected-bg text-status-rejected",
  unknown: "border-status-neutral/30 bg-status-neutral-bg text-status-neutral",
};

/** Summary counts are statuses too — same 5 pairs, never decoration. */
const COUNT_STYLE: Record<string, string> = {
  pending: "border-status-pending/30 bg-status-pending-bg text-status-pending",
  needs_manual: "border-status-corrected/30 bg-status-corrected-bg text-status-corrected",
  approved: "border-status-approved/30 bg-status-approved-bg text-status-approved",
  rejected: "border-status-rejected/30 bg-status-rejected-bg text-status-rejected",
  no_event: "border-status-neutral/30 bg-status-neutral-bg text-status-neutral",
};

function preview(text: string, n = 96): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > n ? `${flat.slice(0, n)}…` : flat;
}

function StatusBadge({ status }: { status: ReviewStatus | null }) {
  if (!status) {
    return (
      <span className="rounded border border-status-neutral/30 bg-status-neutral-bg px-1.5 py-0.5 text-[11px] text-status-neutral">
        No event yet
      </span>
    );
  }
  return (
    <span
      className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function BandBadge({ band, score }: { band: ConfidenceBand | null; score: number }) {
  const percent = `${Math.round(score * 100)}%`;
  if (!band) {
    return <span className="tabular-nums text-muted">{percent}</span>;
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${BAND_STYLE[band]}`}
      title={BAND_LABELS[band]}
    >
      <span>{BAND_LABELS[band]}</span>
      <span className="tabular-nums opacity-80">{percent}</span>
    </span>
  );
}

function RuleChips({ rules }: { rules: RuleCheck[] }) {
  if (rules.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {rules.map((rule) => (
        <span
          key={rule.rule}
          title={rule.detail ?? rule.rule}
          className={`rounded border px-1.5 py-0.5 text-[11px] ${RULE_STYLE[rule.result]}`}
        >
          {rule.rule.replace("_", " ")} · {rule.result}
        </span>
      ))}
    </span>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="text-[13px] text-ink">{value ?? "—"}</div>
    </div>
  );
}

export default function QueuePage() {
  const { user } = useAuth();
  const canDecide = user?.role === "PLANNER";

  const [queue, setQueue] = useState<QueueOut | null>(null);
  const [filter, setFilter] = useState<Filter>("pending");
  const [loadedFilter, setLoadedFilter] = useState<Filter | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<MatchOut | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchQueue({ filter })
      .then((fresh) => {
        if (cancelled) return;
        setQueue(fresh);
        setLoadedFilter(filter);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [filter]);

  const reload = useCallback(async () => {
    const fresh = await fetchQueue({ filter });
    setQueue(fresh);
    if (expandedId != null) {
      try {
        setDetail(await fetchMatch(expandedId));
      } catch {
        setDetail(null);
      }
    }
  }, [filter, expandedId]);

  async function act(
    id: number,
    kind: "approve" | "reject" | "reopen" | "process",
    candidateId?: number,
  ) {
    setBusyId(id);
    setError(null);
    setNotice(null);
    try {
      if (kind === "approve") {
        await approveReport(id, candidateId != null ? { candidate_id: candidateId } : {});
        setNotice(`Report ${id} approved.`);
      } else if (kind === "reject") {
        await rejectReport(id);
        setNotice(`Report ${id} rejected — the evidence is kept.`);
      } else if (kind === "reopen") {
        await reopenReport(id);
        setNotice(`Report ${id} reopened.`);
      } else {
        await processReport(id);
        setNotice(`Report ${id} extracted, matched and verified.`);
      }
      setRejectingId(null);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That action did not go through.");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleDetail(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetail(null);
    setDetailError(null);
    try {
      setDetail(await fetchMatch(id));
    } catch (e) {
      setDetailError(e instanceof ApiError ? e.message : "Could not load the match.");
    }
  }

  function actionsFor(item: QueueItem) {
    if (!canDecide) return null;
    const id = item.report.id;
    const busy = busyId === id;
    const status = item.review_status;

    if (status === null) {
      return (
        <button
          onClick={() => act(id, "process")}
          disabled={busy}
          className="rounded border border-line bg-surface px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-accent hover:text-accent disabled:border-line disabled:bg-line disabled:text-muted"
        >
          {busy ? "Extracting…" : "Extract & match"}
        </button>
      );
    }

    if (status === "PENDING" || status === "NEEDS_MANUAL") {
      return (
        <div className="flex items-center justify-end gap-1.5">
          <button
            onClick={() => act(id, "approve")}
            disabled={busy || !item.top}
            title={item.top ? `Approve ${item.top.activity.code}` : "No candidate to approve"}
            className="rounded bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition-colors hover:bg-accent-hover disabled:bg-line disabled:text-muted"
          >
            {busy ? "Working…" : "Approve"}
          </button>
          {rejectingId === id ? (
            <span className="flex items-center gap-1.5">
              <button
                onClick={() => act(id, "reject")}
                disabled={busy}
                className="rounded border border-status-rejected/40 bg-status-rejected-bg px-2.5 py-1 text-[12px] font-medium text-status-rejected transition-colors hover:bg-status-rejected hover:text-white disabled:border-line disabled:bg-line disabled:text-muted"
              >
                Confirm reject
              </button>
              <button
                onClick={() => setRejectingId(null)}
                className="rounded border border-line px-2 py-1 text-[12px] text-muted hover:bg-page"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setRejectingId(id)}
              disabled={busy}
              className="rounded border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-status-rejected hover:text-status-rejected disabled:border-line disabled:bg-line disabled:text-muted"
            >
              Reject
            </button>
          )}
        </div>
      );
    }

    return (
      <div className="flex items-center justify-end gap-1.5">
        <button
          onClick={() => act(id, "reopen")}
          disabled={busy}
          className="rounded border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-accent hover:text-accent disabled:border-line disabled:bg-line disabled:text-muted"
        >
          {busy ? "Working…" : "Reopen"}
        </button>
        {status === "APPROVED" && rejectingId === id ? (
          <button
            onClick={() => act(id, "reject")}
            disabled={busy}
            className="rounded border border-status-rejected/40 bg-status-rejected-bg px-2.5 py-1 text-[12px] font-medium text-status-rejected hover:bg-status-rejected hover:text-white disabled:border-line disabled:bg-line disabled:text-muted"
          >
            Confirm reject
          </button>
        ) : status === "APPROVED" ? (
          <button
            onClick={() => setRejectingId(id)}
            disabled={busy}
            className="rounded border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-status-rejected hover:text-status-rejected disabled:border-line disabled:bg-line disabled:text-muted"
          >
            Reject
          </button>
        ) : null}
      </div>
    );
  }

  const counts = queue?.counts ?? {};
  const loading = loadedFilter !== filter;

  return (
    <Shell title="Review queue" subtitle="Approve field evidence against the schedule">
      <div className="mx-auto max-w-6xl space-y-4">
        {/* Summary + filters */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1.5 text-[12px]">
            {[
              { key: "pending", label: "Awaiting decision" },
              { key: "needs_manual", label: "Needs manual mapping" },
              { key: "approved", label: "Approved" },
              { key: "rejected", label: "Rejected" },
              { key: "no_event", label: "No event yet" },
            ].map((c) => (
              <span
                key={c.key}
                className={`rounded border px-2 py-1 ${COUNT_STYLE[c.key]}`}
              >
                {c.label}{" "}
                <span className="font-medium tabular-nums">{counts[c.key] ?? 0}</span>
              </span>
            ))}
          </div>
          <div className="ml-auto flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                aria-pressed={filter === f.key}
                className={`rounded px-2.5 py-1 text-[12px] transition-colors ${
                  filter === f.key
                    ? "bg-accent text-white"
                    : "border border-line bg-surface text-muted hover:bg-page"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <p className="rounded border border-status-rejected/30 bg-status-rejected-bg px-3 py-2 text-[13px] text-status-rejected">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="rounded border border-status-approved/30 bg-status-approved-bg px-3 py-2 text-[13px] text-status-approved">
            {notice}
          </p>
        ) : null}

        <section className="overflow-hidden rounded-md border border-line bg-surface">
          <div className="border-b border-line px-4 py-2.5 text-[13px] font-medium">
            Reports
          </div>
          {!queue || loading ? (
            <p className="px-4 py-3 text-[13px] text-muted">Loading…</p>
          ) : queue.items.length === 0 ? (
            <p className="rounded border border-banner-warning-icon/30 bg-banner-warning-bg px-4 py-3 text-[13px] text-banner-warning-text">
              Nothing in this view. Field submissions appear here as soon as they are
              extracted — or{" "}
              <Link href="/" className="text-accent underline-offset-2 hover:underline">
                import a schedule
              </Link>{" "}
              to get started.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-page text-left text-[12px] text-muted">
                    <th className="px-4 py-2 font-medium">Received</th>
                    <th className="px-3 py-2 font-medium">Report</th>
                    <th className="px-3 py-2 font-medium">Top candidate</th>
                    <th className="px-3 py-2 font-medium">Confidence</th>
                    <th className="px-3 py-2 font-medium">Rules</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 text-right font-medium">Decision</th>
                    <th className="w-16" />
                  </tr>
                </thead>
                <tbody>
                  {queue.items.map((item) => {
                    const id = item.report.id;
                    const expanded = expandedId === id;
                    return (
                      <Fragment key={id}>
                        <tr className="border-b border-line align-top">
                          <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-muted">
                            {new Date(item.report.created_at).toLocaleString()}
                          </td>
                          <td className="max-w-[300px] px-3 py-2.5">
                            <div className="truncate text-ink">{preview(item.report.raw_text)}</div>
                            <div className="mt-0.5 text-[11px] text-muted">
                              {item.report.source_type} · report #{id}
                            </div>
                          </td>
                          <td className="max-w-[260px] px-3 py-2.5">
                            {item.top ? (
                              <>
                                <div className="truncate">
                                  <span className="font-medium">{item.top.activity.code}</span>{" "}
                                  {item.top.activity.name}
                                </div>
                                <div className="mt-0.5 text-[11px] text-muted">
                                  {item.top.activity.area ?? "—"} ·{" "}
                                  {item.top.activity.discipline ?? "—"}
                                  {item.candidate_count > 1
                                    ? ` · ${item.candidate_count} candidates`
                                    : ""}
                                </div>
                              </>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            {item.top ? (
                              <BandBadge band={item.top.confidence_band} score={item.top.score} />
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <RuleChips rules={item.top?.rules ?? []} />
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusBadge status={item.review_status} />
                          </td>
                          <td className="px-3 py-2.5">{actionsFor(item)}</td>
                          <td className="px-2 py-2.5 text-right">
                            <button
                              onClick={() => toggleDetail(id)}
                              aria-expanded={expanded}
                              aria-label={expanded ? `Hide report ${id}` : `Open report ${id}`}
                              className="rounded border border-line px-2 py-1 text-[12px] text-muted transition-colors hover:border-accent hover:text-accent"
                            >
                              {expanded ? "Hide" : "Open"}
                            </button>
                          </td>
                        </tr>
                        {expanded ? (
                          <tr className="border-b border-line bg-page">
                            <td colSpan={8} className="px-4 py-3">
                              {detailError ? (
                                <p className="text-[13px] text-status-rejected">{detailError}</p>
                              ) : !detail ? (
                                <p className="text-[13px] text-muted">Loading match…</p>
                              ) : (
                                <DetailPanel
                                  detail={detail}
                                  canDecide={canDecide}
                                  busy={busyId === id}
                                  onApprove={(candidateId) => act(id, "approve", candidateId)}
                                  onReopen={() => act(id, "reopen")}
                                />
                              )}
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </Shell>
  );
}

function DetailPanel({
  detail,
  canDecide,
  busy,
  onApprove,
  onReopen,
}: {
  detail: MatchOut;
  canDecide: boolean;
  busy: boolean;
  onApprove: (candidateId: number) => void;
  onReopen: () => void;
}) {
  const { event, report, candidates } = detail;
  const decidable = (r: RuleCheck) => r.result !== "unknown";
  const translated = report.translation_status === "translated" && !!report.translated_text;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-muted">Extracted event</div>
          {event ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
              <Field
                label="Extracted by"
                value={
                  event.model?.startsWith("heuristic")
                    ? "Pattern (no LLM)"
                    : (event.model ?? null)
                }
              />
              <Field label="Description" value={event.description} />
              <Field label="Discipline" value={event.discipline} />
              <Field label="Location" value={event.location} />
              <Field label="Tag" value={event.tag} />
              <Field label="Date" value={event.event_date} />
              <Field label="Status" value={event.status} />
              <Field label="Progress" value={event.progress != null ? `${event.progress}%` : null} />
              <Field label="Quantity" value={event.quantity} />
              <Field label="Reviewed by" value={event.review_note ?? null} />
            </div>
          ) : (
            <p className="text-[13px] text-muted">
              {detail.extraction_error ?? "No execution event — run extraction first."}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-muted">
            {translated ? "Input (translated)" : "Raw evidence"}
          </div>
          {translated ? (
            <div className="space-y-1.5">
              <p className="whitespace-pre-wrap rounded border border-line bg-page px-2.5 py-2 text-[13px] leading-5 text-ink">
                {report.translated_text}
              </p>
              <p className="text-[11px] text-muted">
                Translated from {report.language_code} — extraction read this text. The
                submission below is kept verbatim as evidence.
              </p>
            </div>
          ) : null}
          <p className="whitespace-pre-wrap rounded border border-line bg-surface px-2.5 py-2 text-[13px] leading-5 text-ink">
            {report.raw_text}
          </p>
          <p className="text-[11px] text-muted">
            report #{report.id} · {report.source_type} ·{" "}
            {report.extraction_status === "extracted"
              ? "extracted"
              : `extraction ${report.extraction_status}`}
            {report.translation_status === "failed" ? " · translation failed" : null}
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded border border-line bg-surface">
        <div className="flex items-center justify-between border-b border-line px-3 py-2 text-[12px] font-medium">
          <span>Candidates, ranked by final confidence</span>
          {event?.review_status === "APPROVED" && canDecide ? (
            <button
              onClick={onReopen}
              disabled={busy}
              className="rounded border border-line px-2 py-1 text-[12px] text-muted hover:border-accent hover:text-accent disabled:border-line disabled:bg-line disabled:text-muted"
            >
              Reopen
            </button>
          ) : null}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[13px]">
            <thead>
              <tr className="border-b border-line bg-page text-left text-[11px] text-muted">
                <th className="px-3 py-1.5 font-medium">#</th>
                <th className="px-3 py-1.5 font-medium">Activity</th>
                <th className="px-3 py-1.5 font-medium">Confidence</th>
                <th className="px-3 py-1.5 font-medium">Rules</th>
                <th className="px-3 py-1.5 font-medium">Actuals</th>
                <th className="px-3 py-1.5 text-right font-medium">Decision</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c: Candidate) => (
                <tr
                  key={c.id}
                  className={`border-b border-line last:border-0 ${c.approved ? "bg-status-approved-bg/40" : ""}`}
                >
                  <td className="px-3 py-2 tabular-nums text-muted">{c.rank}</td>
                  <td className="px-3 py-2">
                    <span className="font-medium">{c.activity.code}</span>{" "}
                    {c.activity.name}
                    <span className="ml-2 text-[11px] text-muted">
                      {c.activity.area ?? "—"} · {c.activity.discipline ?? "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <BandBadge band={c.confidence_band} score={c.score} />
                  </td>
                  <td className="px-3 py-2">
                    <RuleChips rules={c.rules} />
                    <span className="mt-1 block text-[11px] text-muted">
                      {c.rules.filter(decidable).length} of {c.rules.length} rules decidable
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[12px] text-muted">
                    {c.activity.actual_report_id != null
                      ? `${c.activity.actual_status ?? "reported"}${
                          c.activity.actual_progress != null
                            ? ` · ${c.activity.actual_progress}%`
                            : ""
                        }`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {c.approved ? (
                      <span className="rounded border border-status-approved/30 bg-status-approved-bg px-2 py-1 text-[11px] text-status-approved">
                        Approved choice
                      </span>
                    ) : canDecide && detail.event?.review_status !== "REJECTED" ? (
                      <button
                        onClick={() => onApprove(c.id)}
                        disabled={busy}
                        className="rounded border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-accent hover:text-accent disabled:border-line disabled:bg-line disabled:text-muted"
                      >
                        Choose this
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
