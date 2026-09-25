/**
 * Route group layout for authenticated app pages.
 * Phase 1 has no auth yet; Phase 2 adds the login/role gate here —
 * roles are a separate hierarchy from the WBS and never gate by level.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
