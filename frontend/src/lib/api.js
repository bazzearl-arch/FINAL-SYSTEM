import axios from "axios";

const CONFIGURED_BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

// Auth relies on httpOnly cookies. Those cookies are only sent/stored when the
// request is first-party (same origin as the page). This app can be opened from
// more than one Emergent host (e.g. the preview URL and the deployed URL). If the
// page is served from a different host than the configured backend URL, calling
// the configured URL would be cross-origin and the browser would block the auth
// cookies (login "works" then immediately drops). To stay robust we fall back to
// same-origin requests whenever the serving host differs from the configured one.
function resolveApiBase() {
  const configured = CONFIGURED_BACKEND_URL;
  try {
    if (configured && typeof window !== "undefined") {
      const backendHost = new URL(configured).host;
      if (window.location.host !== backendHost) {
        return ""; // same-origin relative → first-party cookies always work
      }
    }
  } catch (e) {
    return configured;
  }
  return configured;
}

const API_ROOT = resolveApiBase();
export const BACKEND_URL = API_ROOT;
export const API = API_ROOT ? `${API_ROOT}/api` : "/api";

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  }
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
