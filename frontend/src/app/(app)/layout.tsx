"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/**
 * Auth gate for the app area: unauthenticated visitors are sent to the
 * plain login screen. Roles decide which *functions* render inside —
 * never which WBS levels are visible (all roles browse the full tree).
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[13px] text-ink-3">
        Loading…
      </div>
    );
  }
  if (!user) return null; // redirecting to /login
  return <>{children}</>;
}
