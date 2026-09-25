"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { landingPathFor, useAuth } from "@/lib/auth";

/**
 * Plain sign-in screen — an internal tool's login, not a landing page.
 * After login the user goes straight to their role's real work screen.
 */
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
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Is the API running?");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-4 text-center">
          <span className="text-[17px] font-semibold tracking-tight text-ink">SiteBridge</span>
        </div>
        <form
          onSubmit={onSubmit}
          className="rounded-md border border-line bg-panel px-5 py-5"
        >
          <h1 className="mb-4 text-[14px] font-medium text-ink">Sign in</h1>
          <label className="mb-3 block">
            <span className="mb-1 block text-[12px] text-ink-2">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              placeholder="you@sitebridge.dev"
              className="block w-full rounded border border-line-2 bg-panel px-2.5 py-1.5 text-[13px] placeholder:text-ink-3"
            />
          </label>
          <label className="mb-4 block">
            <span className="mb-1 block text-[12px] text-ink-2">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="block w-full rounded border border-line-2 bg-panel px-2.5 py-1.5 text-[13px]"
            />
          </label>
          {error ? <p className="mb-3 text-[12px] text-red">{error}</p> : null}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-3 text-center text-[11px] leading-5 text-ink-3">
          Demo accounts (password <span className="font-medium">demo1234</span>):
          <br />
          field@sitebridge.dev · planner@sitebridge.dev · pm@sitebridge.dev
        </p>
      </div>
    </div>
  );
}
