"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchStatus, type Role, type SystemStatus } from "@/lib/api";
import { ROLE_LABELS, useAuth } from "@/lib/auth";

/**
 * Sidebar + top bar shell with role-aware navigation.
 *
 * Nav items are functions of the user's ROLE (who can see/do what) —
 * never of WBS levels. All roles keep access to the WBS browse view.
 * Items landed with their phases: review queue (Phase 8), PM roll-up
 * dashboard (Phase 10).
 */
interface NavItem {
  href: string;
  label: string;
  roles?: Role[];
  active: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  {
    href: "/",
    label: "Projects",
    active: (p) => p === "/" || p.startsWith("/projects"),
  },
  {
    href: "/submit",
    label: "Submit update",
    roles: ["FIELD"],
    active: (p) => p === "/submit",
  },
  {
    href: "/queue",
    label: "Review queue",
    roles: ["PLANNER", "PM"],
    active: (p) => p.startsWith("/queue"),
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    roles: ["PM"],
    active: (p) => p.startsWith("/dashboard"),
  },
];

export function Shell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  // Phase 11: say out loud when the product is running on a fallback.
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchStatus()
      .then((resolved) => {
        if (!cancelled) setStatus(resolved);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleNav = NAV.filter(
    (item) => !item.roles || (user ? item.roles.includes(user.role) : false),
  );

  const renderLink = (item: NavItem, extraClass: string, inverse: boolean) => {
    const active = item.active(pathname);
    const tone = inverse
      ? active
        ? "bg-inverse/10 font-medium text-inverse"
        : "text-inverse/65 hover:bg-inverse/5 hover:text-inverse"
      : active
        ? "bg-page font-medium text-ink"
        : "text-muted hover:bg-page hover:text-ink";
    return (
      <Link key={item.href} href={item.href} className={`${extraClass} ${tone}`}>
        {item.label}
      </Link>
    );
  };

  return (
    <div className="flex min-h-screen">
      {/* Sidebar — structure, not decoration */}
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-56 flex-col bg-sidebar text-inverse md:flex">
        <div className="flex h-12 items-center border-b border-inverse/10 px-4">
          <span className="text-[15px] font-semibold tracking-tight">SiteBridge</span>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {visibleNav.map((item) =>
            renderLink(item, "block rounded px-3 py-1.5 text-[13px] transition-colors", true),
          )}
        </nav>
        <div className="border-t border-inverse/10 px-4 py-3 text-[11px] text-inverse/40">
          Schedule intelligence layer
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col md:pl-56">
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-line bg-surface px-5">
          <div className="flex min-w-0 items-baseline gap-3">
            <h1 className="shrink-0 text-[15px] font-semibold text-ink">{title}</h1>
            {subtitle ? (
              <span className="truncate text-[12px] text-muted">{subtitle}</span>
            ) : null}
            {/* Narrow-viewport nav (sidebar is desktop-only) */}
            <nav className="ml-2 flex gap-2 md:hidden">
              {visibleNav.map((item) => renderLink(item, "text-[13px]", false))}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3 text-[12px]">
            {user ? (
              <>
                <span className="text-muted">{user.full_name}</span>
                <span className="rounded border border-status-neutral/30 bg-status-neutral-bg px-1.5 py-0.5 text-[11px] text-status-neutral">
                  {ROLE_LABELS[user.role]}
                </span>
                <button
                  onClick={logout}
                  className="text-muted transition-colors hover:text-ink"
                >
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </header>

        {/* Phase 11: degraded mode is stated, never silent (label + colour). */}
        {status && status.degraded.length > 0 ? (
          <div
            role="status"
            className="border-b border-banner-warning-icon/30 bg-banner-warning-bg px-5 py-2 text-[12px] leading-5 text-banner-warning-text"
          >
            <span className="font-medium text-banner-warning-icon">Running with fallbacks:</span>{" "}
            {status.degraded.join("  ·  ")}
          </div>
        ) : null}

        <main className="flex-1 p-5">{children}</main>
      </div>
    </div>
  );
}
