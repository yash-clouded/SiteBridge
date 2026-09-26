"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchStatus, type Role, type SystemStatus } from "@/lib/api";
import { ROLE_LABELS, useAuth } from "@/lib/auth";

interface NavItem {
  href: string;
  label: string;
  icon: "grid" | "report" | "queue" | "dashboard";
  roles?: Role[];
  active: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  {
    href: "/",
    label: "Projects",
    icon: "grid",
    active: (p) => p === "/" || p.startsWith("/projects"),
  },
  {
    href: "/submit",
    label: "Send Work Report",
    icon: "report",
    roles: ["FIELD", "SITE_OPERATIVES", "CONTRACTOR"],
    active: (p) => p === "/submit",
  },
  {
    href: "/queue",
    label: "Schedule Desk",
    icon: "queue",
    roles: ["PLANNER", "SITE_ENGINEER", "DISCIPLINE_ENGINEER"],
    active: (p) => p.startsWith("/queue"),
  },
  {
    href: "/dashboard",
    label: "Work Progress",
    icon: "dashboard",
    roles: ["PM", "CLIENT", "PROJECT_MANAGER"],
    active: (p) => p.startsWith("/dashboard"),
  },
];

function Icon({ name }: { name: NavItem["icon"] }) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    className: "h-4 w-4 shrink-0",
  };

  if (name === "grid") {
    return (
      <svg {...common}>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
    );
  }

  if (name === "report") {
    return (
      <svg {...common}>
        <path d="M6 3h9l4 4v14H6z" />
        <path d="M15 3v5h5M9 12h6M9 16h6" />
      </svg>
    );
  }

  if (name === "queue") {
    return (
      <svg {...common}>
        <path d="M4 6h16M4 12h16M4 18h10" />
        <circle cx="18" cy="18" r="2" />
      </svg>
    );
  }

  return (
    <svg {...common}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

function SiteBridgeMark() {
  return (
    <svg viewBox="0 0 100 115" fill="none" className="h-6 w-6 shrink-0" aria-hidden="true">
      <polygon points="50,2 96,28.5 96,86.5 50,113 4,86.5 4,28.5" fill="#36658a" />
      <polygon
        points="50,8 90,31.5 90,83.5 50,107 10,83.5 10,31.5"
        fill="#36658a"
        stroke="#ffffff"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <line x1="50" y1="57.5" x2="50" y2="107" stroke="#ffffff" strokeWidth="2.5" />
      <line x1="50" y1="57.5" x2="10" y2="34.5" stroke="#ffffff" strokeWidth="2.5" />
      <line x1="50" y1="57.5" x2="90" y2="34.5" stroke="#ffffff" strokeWidth="2.5" />
      <line x1="10" y1="57.5" x2="90" y2="57.5" stroke="#ffffff" strokeWidth="2.5" />
    </svg>
  );
}

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
  const [collapsed, setCollapsed] = useState(false);
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

  return (
    <div className="min-h-screen bg-[#eaedf1] text-slate-900">
      <header className="fixed inset-x-0 top-0 z-30 flex h-11 items-center justify-between border-b border-[#2d3440] bg-[#1e232a] px-4 text-slate-300">
        <div className="flex min-w-0 items-center gap-3">
          <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
            Role
          </span>
          <span className="rounded-[2px] border border-[#3d495c] bg-[#293241] px-2 py-0.5 font-mono text-[10px] font-bold uppercase text-slate-100">
            {user ? ROLE_LABELS[user.role] : "—"}
          </span>
          <span className="text-slate-600">|</span>
          <span className="truncate text-[11px] text-slate-400">
            Operator: <strong className="text-slate-100">{user?.full_name ?? "—"}</strong>
            {user ? (
              <>
                {" "}(
                <span className="font-mono text-slate-300">{user.email}</span>)
              </>
            ) : null}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span className="hidden font-mono text-[10px] text-slate-500 sm:inline">
            AREA: <strong className="text-slate-300">SITE CONTROL</strong>
          </span>
          <button
            onClick={logout}
            className="rounded-[2px] border border-[#444e5f] bg-[#2d333f] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300 transition-colors hover:bg-[#394150] hover:text-white"
          >
            Disconnect
          </button>
        </div>
      </header>

      <aside
        className={`fixed bottom-0 left-0 top-11 z-20 hidden flex-col border-r border-[#2d3440] bg-[#1a1d24] text-slate-300 transition-[width] duration-150 md:flex ${collapsed ? "w-14" : "w-56"}`}
      >
        <div className="flex items-center justify-between border-b border-[#2d3440] bg-[#15171d] px-2.5 py-2.5">
          {!collapsed ? (
            <div className="flex min-w-0 items-center gap-2">
              <SiteBridgeMark />
              <div className="truncate">
                <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-200">
                  Site Bridge
                </div>
                <div className="font-mono text-[8px] uppercase tracking-widest text-slate-500">
                  Engineering Controls
                </div>
              </div>
            </div>
          ) : (
            <SiteBridgeMark />
          )}
          <button
            onClick={() => setCollapsed((value) => !value)}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            className="rounded-[2px] p-1 text-slate-500 transition-colors hover:bg-[#252a33] hover:text-white"
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-2">
          {visibleNav.map((item) => {
            const active = item.active(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={collapsed ? item.label : undefined}
                className={`flex items-center rounded-[2px] border px-2 py-2 text-[11px] font-medium transition-colors ${
                  active
                    ? "border-[#384353] bg-[#252a33] text-slate-100"
                    : "border-transparent text-slate-400 hover:border-[#303845] hover:bg-[#20252e] hover:text-slate-200"
                } ${collapsed ? "justify-center" : "gap-2"}`}
              >
                <Icon name={item.icon} />
                {!collapsed ? <span className="truncate">{item.label}</span> : null}
              </Link>
            );
          })}
        </nav>

        {!collapsed ? (
          <div className="border-t border-[#2d3440] bg-[#15171d] p-2.5">
            <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
              Login Status
            </div>
            <div className="mt-1 truncate text-[11px] font-semibold text-slate-200">
              {user?.full_name ?? "—"}
            </div>
            <div className="truncate font-mono text-[9px] text-slate-500">
              {user?.email ?? "—"}
            </div>
            <div className="mt-1 inline-block rounded-[2px] border border-[#37404f] bg-[#232933] px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase text-slate-300">
              {user ? ROLE_LABELS[user.role] : "—"}
            </div>
          </div>
        ) : null}
      </aside>

      <div className={`min-h-screen pt-11 ${collapsed ? "md:pl-14" : "md:pl-56"}`}>
        <section className="border-b border-[#cfd5de] bg-white px-4 py-2.5 shadow-sm">
          <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h1 className="truncate text-[12px] font-bold uppercase tracking-[0.08em] text-slate-900">
                {title}
              </h1>
              {subtitle ? (
                <p className="mt-0.5 truncate text-[10px] text-slate-500">{subtitle}</p>
              ) : null}
            </div>
            {status?.degraded.length ? (
              <div className="rounded-[2px] border border-amber-300 bg-amber-50 px-2 py-1 text-[10px] text-amber-800">
                <span className="font-bold uppercase">Fallback:</span>{" "}
                {status.degraded.join(" · ")}
              </div>
            ) : null}
          </div>
        </section>

        <main className="p-3 sm:p-4">{children}</main>
      </div>
    </div>
  );
}
