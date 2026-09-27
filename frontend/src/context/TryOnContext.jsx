import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const TryOnContext = createContext(null);

const STORAGE_KEY = "aitryonph.tryon.v1";

/**
 * Global try-on state.
 *
 * Lives ABOVE the Router so state + polling survive route changes.
 * When the user leaves /try-on while a render is running, the poll keeps
 * running in the background. When they come back, the results carousel is
 * already there (or still processing).
 *
 * Persists { step, gender, sessionId } in localStorage so a page reload
 * mid-render can resume polling and jump straight to the result screen.
 * (photos + selected are kept in memory only — they're large and only
 * useful during an active flow.)
 */
export function TryOnProvider({ children }) {
  const { user } = useAuth() || {};
  const [step, setStep] = useState(1);
  const [gender, setGender] = useState(null);
  const [photos, setPhotos] = useState({ front: null, left: null, right: null, rear: null });
  const [selected, setSelected] = useState([]);
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | processing | completed | failed
  const [carousel, setCarousel] = useState(0);

  const pollRef = useRef(null);
  const pollingId = useRef(null); // session id currently being polled

  // ---- localStorage hydration ----
  useEffect(() => {
    if (!user) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved?.user_id && saved.user_id !== user.id) {
        // different user - drop
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      if (saved?.step) setStep(saved.step);
      if (saved?.gender) setGender(saved.gender);
      if (saved?.session_id) {
        // resume polling on this session
        setStatus("processing");
        setStep(4);
        api.get(`/tryon/sessions/${saved.session_id}`).then(({ data }) => {
          setSession(data);
          if (data.status === "processing") {
            startPoll(saved.session_id);
          } else {
            setStatus(data.status === "COMPLETED" ? "completed" : "failed");
          }
        }).catch(() => {
          localStorage.removeItem(STORAGE_KEY);
          setStatus("idle");
          setStep(1);
        });
      }
    } catch (_e) { /* silent */ }
  }, [user?.id]);

  // ---- localStorage persistence ----
  useEffect(() => {
    if (!user) return;
    const payload = {
      user_id: user.id,
      step,
      gender,
      session_id: session?.id || null,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (_e) { /* quota */ }
  }, [user, step, gender, session?.id]);

  // ---- poll helper ----
  const startPoll = useCallback((id) => {
    if (!id) return;
    if (pollingId.current === id) return; // already polling this session
    if (pollRef.current) clearInterval(pollRef.current);
    pollingId.current = id;
    let tries = 0;
    pollRef.current = setInterval(async () => {
      tries += 1;
      try {
        const { data } = await api.get(`/tryon/sessions/${id}`);
        if (data.status !== "processing") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          pollingId.current = null;
          setSession(data);
          setStatus(data.status === "COMPLETED" ? "completed" : "failed");
          setCarousel(0);
        } else {
          // update partial views if any (progressive)
          setSession(data);
        }
      } catch (_e) { /* keep retrying */ }
      if (tries > 120) { // ~4 min safety
        clearInterval(pollRef.current);
        pollRef.current = null;
        pollingId.current = null;
        setStatus("failed");
      }
    }, 2500);
  }, []);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  // ---- actions ----
  const startGenerate = useCallback(async ({ gender: g, photos: ph, product_ids }) => {
    setStep(4);
    setStatus("processing");
    setSession(null);
    setCarousel(0);
    try {
      const { data } = await api.post("/tryon/multiview", {
        gender: g,
        photos: ph,
        product_ids,
      });
      setSession(data);
      startPoll(data.id);
    } catch (e) {
      setStatus("failed");
      return { ok: false, error: e?.response?.data?.detail || "Could not start try-on" };
    }
    return { ok: true };
  }, [startPoll]);

  const retry = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    pollingId.current = null;
    return startGenerate({ gender, photos, product_ids: selected.map((p) => p.id) });
  }, [gender, photos, selected, startGenerate]);

  const reset = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    pollingId.current = null;
    setStep(1);
    setGender(null);
    setPhotos({ front: null, left: null, right: null, rear: null });
    setSelected([]);
    setSession(null);
    setStatus("idle");
    setCarousel(0);
    try { localStorage.removeItem(STORAGE_KEY); } catch (_e) { /* silent */ }
  }, []);

  const value = {
    step, setStep,
    gender, setGender,
    photos, setPhotos,
    selected, setSelected,
    session, setSession,
    status, setStatus,
    carousel, setCarousel,
    startGenerate,
    retry,
    reset,
    isPolling: !!pollRef.current,
  };

  return <TryOnContext.Provider value={value}>{children}</TryOnContext.Provider>;
}

export function useTryOn() {
  const ctx = useContext(TryOnContext);
  if (!ctx) throw new Error("useTryOn must be used inside <TryOnProvider>");
  return ctx;
}
