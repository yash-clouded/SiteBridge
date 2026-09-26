// SiteBridge portal configuration — API base URL only, never secrets.
// Local dev points at the FastAPI server on port 8000; the deployed build
// (Vercel) rewrites this file at build time from the API_BASE env var.
window.__SITEBRIDGE_API_URL__ = "http://localhost:8000";
