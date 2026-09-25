"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Sidebar + top bar shell.
 * Phase 1 has a single real destination; role-based navigation items are
 * added in Phase 2 (roles live entirely outside the WBS hierarchy).
 */
const NAV: { href: string; label: string; exact?: boolean }[] = [
  { href: "/", label: "Projects", exact: true },
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

  return (
    <div className="flex min-h-screen">
      {/* Sidebar — structure, not decoration */}
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-56 flex-col bg-ink text-white md:flex">
        <div className="flex h-12 items-center border-b border-white/10 px-4">
          <span className="text-[15px] font-semibold tracking-tight">SiteBridge</span>
        </div>
        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.map((item) => {
            const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded px-3 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "bg-white/10 font-medium text-white"
                    : "text-white/65 hover:bg-white/5 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
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
              {NAV.map((item) => {
                const active = item.exact
                  ? pathname === item.href
                  : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`text-[13px] ${active ? "font-medium text-accent" : "text-ink-2"}`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-[12px] text-ink-3">
            {/* Role/user slot — populated in Phase 2 */}
          </div>
        </header>

        <main className="flex-1 p-5">{children}</main>
      </div>
    </div>
  );
}
