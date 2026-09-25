"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Role } from "@/lib/api";
import { ROLE_LABELS, useAuth } from "@/lib/auth";

/**
 * Sidebar + top bar shell with role-aware navigation.
 *
 * Nav items are functions of the user's ROLE (who can see/do what) —
 * never of WBS levels. All roles keep access to the WBS browse view.
 * Items are added as their phases land: the planner review queue (Phase 8)
 * is in; the PM rollup dashboard (Phase 10) is next.
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

  const visibleNav = NAV.filter(
    (item) => !item.roles || (user ? item.roles.includes(user.role) : false),
  );

  const renderLink = (item: NavItem, extraClass: string) => {
    const active = item.active(pathname);
    return (
      <Link
        key={item.href}
        href={item.href}
        className={`${extraClass} ${
          active
            ? "bg-white/10 font-medium text-white"
            : "text-white/65 hover:bg-white/5 hover:text-white"
        }`}
      >
        {item.label}
      </Link>
    );
  };

  return (
    <div className="flex min-h-screen">
      {/* Sidebar — structure, not decoration */}
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-56 flex-col bg-ink text-white md:flex">
        <div className="flex h-12 items-center border-b border-white/10 px-4">
          <span className="text-[15px] font-semibold tracking-tight">SiteBridge</span>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {visibleNav.map((item) => renderLink(item, "block rounded px-3 py-1.5 text-[13px] transition-colors"))}
        </nav>
        <div className="border-t border-white/10 px-4 py-3 text-[11px] text-white/40">
          Schedule intelligence layer
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col md:pl-56">
        {/* Top bar */}
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-line bg-panel px-5">
          <div className="flex min-w-0 items-baseline gap-3">
            <h1 className="shrink-0 text-[15px] font-semibold text-ink">{title}</h1>
            {subtitle ? (
              <span className="truncate text-[12px] text-ink-3">{subtitle}</span>
            ) : null}
            {/* Narrow-viewport nav (sidebar is desktop-only) */}
            <nav className="ml-2 flex gap-2 md:hidden">
              {visibleNav.map((item) => renderLink(item, "text-[13px]"))}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3 text-[12px]">
            {user ? (
              <>
                <span className="text-ink-2">{user.full_name}</span>
                <span className="rounded border border-line-2 bg-panel-2 px-1.5 py-0.5 text-[11px] text-ink-2">
                  {ROLE_LABELS[user.role]}
                </span>
                <button
                  onClick={logout}
                  className="text-ink-3 transition-colors hover:text-ink"
                >
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </header>

        <main className="flex-1 p-5">{children}</main>
      </div>
    </div>
  );
}
