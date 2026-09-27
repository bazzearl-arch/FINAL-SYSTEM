import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    // If returning from Google OAuth callback, skip /me — AuthCallback will exchange session_id first.
    if (typeof window !== "undefined" && window.location.hash?.includes("session_id=")) {
      setChecking(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async (email, password) => {
    try {
      const { data } = await api.post("/auth/login", { email, password });
      if (data.requires_2fa_setup) return { ok: true, twofa: "setup", mfa_token: data.mfa_token, email: data.email };
      if (data.requires_2fa) return { ok: true, twofa: "verify", mfa_token: data.mfa_token, email: data.email };
      setUser(data);
      return { ok: true, user: data };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const register = async (email, password, name) => {
    try {
      const { data } = await api.post("/auth/register", { email, password, name });
      if (data.requires_2fa_setup) return { ok: true, twofa: "setup", mfa_token: data.mfa_token, email: data.email };
      if (data.requires_2fa) return { ok: true, twofa: "verify", mfa_token: data.mfa_token, email: data.email };
      setUser(data);
      return { ok: true, user: data };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  // --- Two-factor (TOTP) handshake ---
  const twofaSetup = async (mfaToken) => {
    try {
      const { data } = await api.post("/auth/2fa/setup", { mfa_token: mfaToken });
      return { ok: true, ...data };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const twofaEnable = async (mfaToken, code) => {
    try {
      const { data } = await api.post("/auth/2fa/enable", { mfa_token: mfaToken, code });
      setUser(data);
      return { ok: true, user: data };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const twofaVerify = async (mfaToken, code) => {
    try {
      const { data } = await api.post("/auth/2fa/verify", { mfa_token: mfaToken, code });
      setUser(data);
      return { ok: true, user: data };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch (e) { /* noop */ }
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, checking, login, register, logout, refresh, setUser, twofaSetup, twofaEnable, twofaVerify }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
