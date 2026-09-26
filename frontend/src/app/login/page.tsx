"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { landingPathFor, useAuth } from "@/lib/auth";

function SiteBridgeMark() {
  return (
    <svg viewBox="0 0 100 115" fill="none" className="h-8 w-8 shrink-0" aria-hidden="true">
      <polygon points="50,2 96,28.5 96,86.5 50,113 4,86.5 4,28.5" fill="#36658a" />
      <polygon
        points="50,8 90,31.5 90,83.5 50,107 10,83.5 10,31.5"
        fill="#36658a"
        stroke="#ffffff"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <line x1="50" y1="57.5" x2="50" y2="107" stroke="#ffffff" strokeWidth="2.2" />
      <line x1="50" y1="57.5" x2="10" y2="34.5" stroke="#ffffff" strokeWidth="2.2" />
      <line x1="50" y1="57.5" x2="90" y2="34.5" stroke="#ffffff" strokeWidth="2.2" />
      <line x1="10" y1="57.5" x2="90" y2="57.5" stroke="#ffffff" strokeWidth="2.2" />
      <polygon points="50,57.5 30,20 50,33 70,20" fill="none" stroke="#ffffff" strokeWidth="2.2" />
      <polygon points="50,57.5 35,92 50,69 65,92" fill="none" stroke="#ffffff" strokeWidth="2.2" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const user = await login(email, password);
      router.replace(landingPathFor(user.role));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Authentication rejected. Check the API and your credentials.",
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#111317] text-slate-300">
      <header className="flex items-center justify-between border-b border-[#242a33] bg-[#181b22] px-6 py-3">
        <div className="flex items-center gap-3">
          <SiteBridgeMark />
          <span className="text-sm font-bold uppercase tracking-[0.16em] text-slate-100">
            Site Bridge
          </span>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center p-4">
        <div className="w-full max-w-sm rounded-[2px] border border-[#2d3440] bg-[#1a1e26] p-6 shadow-lg">
          <div className="mb-5 border-b border-[#2d3440] pb-3">
            <h1 className="text-sm font-bold uppercase tracking-wide text-slate-100">
              Workstation Entry
            </h1>
            <p className="mt-0.5 text-[11px] text-slate-400">
              Secure SiteBridge project-control access
            </p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold uppercase text-slate-300">
                Operator Email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                placeholder="field@sitebridge.dev"
                className="w-full rounded-[2px] border border-[#343b49] bg-[#12151a] px-2.5 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-[#0d6efd]"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold uppercase text-slate-300">
                Access Password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full rounded-[2px] border border-[#343b49] bg-[#12151a] px-2.5 py-2 text-xs text-slate-200 outline-none focus:border-[#0d6efd]"
              />
            </label>

            {error ? (
              <div className="border border-[#6b2a2a] bg-[#341818] p-2 text-[11px] text-red-300">
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={submitting}
              className="mt-2 w-full rounded-[2px] bg-[#0d6efd] py-2.5 text-xs font-semibold uppercase tracking-wider text-white transition-colors hover:bg-[#0b5ed7] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Connecting…" : "Connect Session"}
            </button>
          </form>

          <div className="mt-5 border-t border-[#2d3440] pt-3 text-center font-mono text-[10px] leading-5 text-slate-500">
            Demo accounts: field@sitebridge.dev · planner@sitebridge.dev · pm@sitebridge.dev
            <br />
            Password: demo1234
          </div>
        </div>
      </main>

      <footer className="border-t border-[#242a33] bg-[#14171d] px-6 py-2.5 text-center font-mono text-[10px] text-slate-500">
        SITEBRIDGE · ENGINEERING CONTROLS
      </footer>
    </div>
  );
}
