import { useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Camera, Upload, Sparkles, AlertTriangle, X, ChevronRight, ChevronLeft,
  RotateCcw, ExternalLink, Check, RefreshCw, ArrowLeft,
} from "lucide-react";
import { toast } from "sonner";
import PrivateImage from "@/components/PrivateImage";

const VIEWS = [
  { key: "front", label: "Front" },
  { key: "left", label: "Left side" },
  { key: "right", label: "Right side" },
  { key: "rear", label: "Rear / back" },
];

const PHOTO_TIPS = [
  "Show your entire body, head to toe.",
  "Use good lighting and a plain background.",
  "Keep the camera at a steady height & distance.",
  "Stand in a similar position for all four photos.",
];

async function fileToBase64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

const peso = (v, c = "PHP") =>
  v == null ? "" : `${c === "PHP" ? "₱" : c + " "}${Number(v).toLocaleString()}`;

export default function TryOnPage() {
  const [params] = useSearchParams();
  const [step, setStep] = useState(1); // 1=gender 2=photos 3=products 4=result
  const [gender, setGender] = useState(null);
  const [photos, setPhotos] = useState({ front: null, left: null, right: null, rear: null });
  const [categories, setCategories] = useState([]);
  const [activeCat, setActiveCat] = useState(null);
  const [products, setProducts] = useState([]);
  const [selected, setSelected] = useState([]); // array of product objects (outfit)

  const [session, setSession] = useState(null);
  const [status, setStatus] = useState("idle"); // idle|processing|completed|failed
  const [carousel, setCarousel] = useState(0);

  // camera
  const [camSlot, setCamSlot] = useState(null);
  const [camError, setCamError] = useState(null);
  const videoRef = useRef(null);
  const pollRef = useRef(null);

  // ---- data loading ----
  useEffect(() => {
    if (!gender) return;
    api.get(`/categories?gender=${gender}`).then(({ data }) => {
      setCategories(data.categories || []);
      setActiveCat((c) => c || data.categories?.[0] || null);
    });
    api.get(`/products?gender=${gender}&limit=200`).then(({ data }) => setProducts(data));
  }, [gender]);

  useEffect(() => {
    const preset = params.get("product");
    if (preset) {
      api.get(`/products/${preset}`).then(({ data }) => {
        setGender(data.gender === "men" ? "men" : data.gender === "women" ? "women" : "women");
        setSelected([data]);
      }).catch(() => {});
    }
  }, [params]);

  // ---- camera ----
  const startCam = async (slot) => {
    setCamSlot(slot);
    setCamError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" }, audio: false,
      });
      // wait for the element to mount
      setTimeout(() => {
        if (videoRef.current) { videoRef.current.srcObject = stream; }
      }, 50);
    } catch (e) {
      setCamError(
        "Camera permission is required to take a photo. Please allow camera access, or use “Upload from device” instead."
      );
    }
  };
  const stopCam = () => {
    if (videoRef.current?.srcObject) {
      videoRef.current.srcObject.getTracks().forEach((t) => t.stop());
      videoRef.current.srcObject = null;
    }
    setCamSlot(null);
    setCamError(null);
  };
  const capture = () => {
    if (!videoRef.current || !videoRef.current.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = videoRef.current.videoWidth;
    canvas.height = videoRef.current.videoHeight;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    setPhotos((p) => ({ ...p, [camSlot]: dataUrl }));
    stopCam();
  };

  const onFile = async (slot, e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast.error("Max 8MB"); return; }
    const b64 = await fileToBase64(f);
    setPhotos((p) => ({ ...p, [slot]: b64 }));
    e.target.value = "";
  };

  const photosDone = VIEWS.every((v) => photos[v.key]);

  // ---- outfit selection ----
  const toggleProduct = (p) => {
    setSelected((s) => (s.find((x) => x.id === p.id) ? s.filter((x) => x.id !== p.id) : [...s, p]));
  };
  const isSelected = (id) => selected.some((x) => x.id === id);
  const catProducts = products.filter((p) => p.category === activeCat);

  // ---- generate + poll ----
  const poll = useCallback((id) => {
    let tries = 0;
    pollRef.current = setInterval(async () => {
      tries += 1;
      try {
        const { data } = await api.get(`/tryon/sessions/${id}`);
        if (data.status !== "processing") {
          clearInterval(pollRef.current);
          setSession(data);
          setStatus(data.status === "COMPLETED" ? "completed" : "failed");
          setCarousel(0);
        }
      } catch {
        // keep trying
      }
      if (tries > 90) { // ~3 min safety
        clearInterval(pollRef.current);
        setStatus("failed");
      }
    }, 2000);
  }, []);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const generate = async () => {
    if (!photosDone) { toast.error("Add all four photos"); setStep(2); return; }
    if (selected.length === 0) { toast.error("Select at least one item"); return; }
    setStep(4);
    setStatus("processing");
    setSession(null);
    try {
      const { data } = await api.post("/tryon/multiview", {
        gender,
        photos,
        product_ids: selected.map((p) => p.id),
      });
      setSession(data);
      poll(data.id);
    } catch (e) {
      setStatus("failed");
      toast.error("Could not start the try-on. Please try again.");
    }
  };

  const retryGenerate = () => { clearInterval(pollRef.current); generate(); };
  const restart = () => {
    clearInterval(pollRef.current);
    setStep(1); setGender(null);
    setPhotos({ front: null, left: null, right: null, rear: null });
    setSelected([]); setSession(null); setStatus("idle");
  };

  // available views (with a rendered file)
  const availViews = session?.views
    ? VIEWS.filter((v) => session.views[v.key]?.file_id)
    : [];
  const curView = availViews[carousel] || availViews[0];

  // touch swipe
  const touchX = useRef(null);
  const onTouchStart = (e) => { touchX.current = e.touches[0].clientX; };
  const onTouchEnd = (e) => {
    if (touchX.current == null) return;
    const dx = e.changedTouches[0].clientX - touchX.current;
    if (dx > 40) setCarousel((c) => (c - 1 + availViews.length) % availViews.length);
    if (dx < -40) setCarousel((c) => (c + 1) % availViews.length);
    touchX.current = null;
  };

  return (
    <main data-testid="tryon-page" className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Stepper */}
      <ol className="mb-8 flex items-center gap-2 flex-wrap text-sm" data-testid="tryon-stepper">
        {[
          { n: 1, label: "Gender" },
          { n: 2, label: "Your photos" },
          { n: 3, label: "Choose outfit" },
          { n: 4, label: "Results" },
        ].map((s, i, arr) => (
          <li key={s.n} className="flex items-center gap-2">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
              step === s.n ? "bg-primary text-primary-foreground border-primary"
              : step > s.n ? "border-border text-foreground" : "border-border text-muted-foreground"
            }`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-mono ${
                step >= s.n ? "bg-brand-gold text-black" : "bg-muted"
              }`}>{s.n}</span>
              {s.label}
            </div>
            {i < arr.length - 1 && <ChevronRight size={14} className="text-muted-foreground" />}
          </li>
        ))}
      </ol>

      {/* STEP 1 · GENDER */}
      {step === 1 && (
        <div className="max-w-2xl mx-auto text-center" data-testid="step-gender">
          <p className="overline-label text-muted-foreground">Step 1</p>
          <h2 className="font-serif text-3xl mt-1">Who are we styling?</h2>
          <p className="text-sm text-muted-foreground mt-2">This tailors the categories and products shown.</p>
          <div className="mt-8 grid grid-cols-2 gap-4">
            {[{ id: "women", label: "Women" }, { id: "men", label: "Men" }].map((g) => (
              <button
                key={g.id}
                data-testid={`gender-${g.id}`}
                onClick={() => { setGender(g.id); setStep(2); }}
                className="rounded-2xl border-2 border-border hover:border-foreground transition p-10 flex flex-col items-center gap-3"
              >
                <span className="font-serif text-2xl">{g.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* STEP 2 · FOUR PHOTOS */}
      {step === 2 && (
        <div data-testid="step-photos" className="max-w-3xl mx-auto">
          <p className="overline-label text-muted-foreground">Step 2</p>
          <h2 className="font-serif text-3xl mt-1">Add four whole-body photos</h2>
          <ul className="mt-3 text-xs text-muted-foreground grid sm:grid-cols-2 gap-x-6 gap-y-1 list-disc pl-5">
            {PHOTO_TIPS.map((t) => <li key={t}>{t}</li>)}
          </ul>

          <div className="mt-6 grid grid-cols-2 gap-4" data-testid="photo-grid">
            {VIEWS.map((v) => (
              <div key={v.key} data-testid={`photo-slot-${v.key}`} className="rounded-2xl border border-border overflow-hidden bg-card">
                <div className="aspect-[3/4] bg-muted relative flex items-center justify-center">
                  {photos[v.key] ? (
                    <>
                      <img src={photos[v.key]} alt={v.label} className="w-full h-full object-cover" />
                      <span className="absolute top-2 left-2 text-[10px] font-mono uppercase bg-background/85 px-2 py-0.5 rounded-full flex items-center gap-1">
                        <Check size={10} className="text-emerald-600" /> {v.label}
                      </span>
                      <button
                        data-testid={`retake-${v.key}`}
                        onClick={() => setPhotos((p) => ({ ...p, [v.key]: null }))}
                        className="absolute top-2 right-2 w-8 h-8 rounded-full bg-background/90 border border-border flex items-center justify-center"
                        aria-label={`Retake ${v.label}`}
                      >
                        <RotateCcw size={14} />
                      </button>
                    </>
                  ) : (
                    <div className="text-center px-3">
                      <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">{v.label}</p>
                      <div className="mt-3 flex flex-col gap-2">
                        <label className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-full border border-border cursor-pointer hover:bg-secondary text-xs" data-testid={`upload-${v.key}`}>
                          <Upload size={12} /> Upload
                          <input type="file" accept="image/*" className="hidden" onChange={(e) => onFile(v.key, e)} />
                        </label>
                        <Button data-testid={`camera-${v.key}`} variant="outline" size="sm" className="rounded-full gap-2 text-xs" onClick={() => startCam(v.key)}>
                          <Camera size={12} /> Camera
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 flex items-center gap-3">
            <Button variant="outline" className="rounded-full gap-2" onClick={() => setStep(1)}>
              <ArrowLeft size={14} /> Back
            </Button>
            <Button
              data-testid="tryon-next-photos"
              className="flex-1 rounded-full h-12"
              disabled={!photosDone}
              onClick={() => setStep(3)}
            >
              {photosDone ? "Continue to outfit" : `Add all 4 photos (${VIEWS.filter((v)=>photos[v.key]).length}/4)`}
            </Button>
          </div>
        </div>
      )}

      {/* STEP 3 · OUTFIT */}
      {step === 3 && (
        <div data-testid="step-products" className="grid lg:grid-cols-12 gap-8">
          <div className="lg:col-span-8">
            <p className="overline-label text-muted-foreground">Step 3</p>
            <h2 className="font-serif text-3xl mt-1">Build your outfit</h2>
            <p className="text-sm text-muted-foreground mt-2">
              Pick everything you want to try on together — we will layer them across all four views.
            </p>

            {/* category tabs (gender-filtered) */}
            <div className="mt-5 flex gap-2 flex-wrap" data-testid="category-tabs">
              {categories.map((c) => (
                <button
                  key={c}
                  data-testid={`category-tab-${c}`}
                  onClick={() => setActiveCat(c)}
                  className={`px-4 py-1.5 rounded-full border text-sm capitalize transition ${
                    activeCat === c ? "bg-foreground text-background border-foreground" : "border-border hover:bg-secondary"
                  }`}
                >
                  {c.replace("-", " ")}
                </button>
              ))}
            </div>

            <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3">
              {catProducts.length === 0 && (
                <p className="col-span-full text-sm text-muted-foreground py-10 text-center">No items in this category.</p>
              )}
              {catProducts.map((p) => (
                <button
                  key={p.id}
                  data-testid={`product-pick-${p.id}`}
                  onClick={() => toggleProduct(p)}
                  className={`relative rounded-xl overflow-hidden border-2 text-left transition ${
                    isSelected(p.id) ? "border-brand-gold ring-2 ring-brand-gold/30" : "border-transparent hover:border-border"
                  }`}
                >
                  <div className="aspect-[4/5] bg-muted">
                    <img src={p.image_url} alt={p.name} className="w-full h-full object-cover" />
                  </div>
                  {isSelected(p.id) && (
                    <span className="absolute top-2 right-2 w-6 h-6 rounded-full bg-brand-gold text-black flex items-center justify-center">
                      <Check size={14} />
                    </span>
                  )}
                  <div className="p-2">
                    <p className="text-xs font-medium truncate">{p.name}</p>
                    <p className="text-[10px] text-muted-foreground">{peso(p.price, p.currency)} · {p.source_platform}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* selection summary */}
          <aside className="lg:col-span-4">
            <div className="bg-card border border-border rounded-2xl p-5 sticky top-24" data-testid="selected-outfit">
              <p className="overline-label text-muted-foreground">Your outfit · {selected.length} item{selected.length === 1 ? "" : "s"}</p>
              {selected.length === 0 && <p className="text-sm text-muted-foreground mt-3">Nothing selected yet.</p>}
              <div className="mt-3 space-y-2 max-h-72 overflow-y-auto">
                {selected.map((p) => (
                  <div key={p.id} className="flex items-center gap-3">
                    <img src={p.image_url} alt="" className="w-12 h-14 rounded object-cover bg-muted" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate">{p.name}</p>
                      <p className="text-[10px] text-muted-foreground capitalize">{p.category}</p>
                    </div>
                    <button onClick={() => toggleProduct(p)} className="text-muted-foreground hover:text-foreground" aria-label="remove">
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-5 space-y-2">
                <Button data-testid="tryon-generate" className="w-full rounded-full h-12 gap-2" disabled={selected.length === 0} onClick={generate}>
                  <Sparkles size={16} /> Try on ({selected.length})
                </Button>
                <Button variant="outline" className="w-full rounded-full gap-2" onClick={() => setStep(2)}>
                  <ArrowLeft size={14} /> Back to photos
                </Button>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* STEP 4 · RESULTS */}
      {step === 4 && (
        <div data-testid="step-result" className="grid lg:grid-cols-12 gap-8">
          <div className="lg:col-span-7">
            {status === "processing" && (
              <div data-testid="tryon-processing" className="h-[520px] rounded-2xl border border-dashed border-border flex flex-col items-center justify-center gap-4">
                <div className="w-12 h-12 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                <p className="text-sm text-muted-foreground">Generating your four views…</p>
                <p className="text-xs text-muted-foreground">This can take a little while for a full outfit.</p>
              </div>
            )}

            {status === "failed" && (
              <div data-testid="tryon-error" className="h-[520px] rounded-2xl border border-red-500/40 bg-red-500/5 flex flex-col items-center justify-center gap-4 text-center px-6">
                <AlertTriangle className="h-8 w-8 text-red-500" />
                <div>
                  <p className="font-medium">Try-on failed</p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                    {session?.error || "Something went wrong while rendering. Please try again."}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button data-testid="try-again" className="rounded-full gap-2" onClick={retryGenerate}>
                    <RefreshCw size={14} /> Try again
                  </Button>
                  <Button data-testid="back-to-photos" variant="outline" className="rounded-full" onClick={() => setStep(2)}>
                    Return to photos
                  </Button>
                </div>
              </div>
            )}

            {status === "completed" && curView && (
              <div data-testid="result-carousel">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-serif text-2xl">AI Try-On Result</h2>
                  <Badge className="uppercase tracking-wider text-[10px] bg-secondary">
                    {session?.engine === "fashn" ? "FASHN" : "Preview (mock)"}
                  </Badge>
                </div>
                <div
                  className="relative rounded-2xl overflow-hidden bg-muted aspect-[3/4]"
                  onTouchStart={onTouchStart}
                  onTouchEnd={onTouchEnd}
                >
                  <PrivateImage fileId={curView.file_id} className="w-full h-full object-cover" alt={curView.label} />
                  <button
                    data-testid="carousel-prev"
                    onClick={() => setCarousel((c) => (c - 1 + availViews.length) % availViews.length)}
                    className="absolute left-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-background/85 border border-border flex items-center justify-center hover:bg-background"
                    aria-label="Previous view"
                  >
                    <ChevronLeft size={18} />
                  </button>
                  <button
                    data-testid="carousel-next"
                    onClick={() => setCarousel((c) => (c + 1) % availViews.length)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-background/85 border border-border flex items-center justify-center hover:bg-background"
                    aria-label="Next view"
                  >
                    <ChevronRight size={18} />
                  </button>
                  <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2">
                    <span data-testid="carousel-index" className="text-xs font-mono bg-background/85 border border-border rounded-full px-3 py-1">
                      {carousel + 1}/{availViews.length} · {curView.label}
                    </span>
                  </div>
                </div>
                {/* thumbnails */}
                <div className="mt-3 grid grid-cols-4 gap-2">
                  {availViews.map((v, i) => (
                    <button
                      key={v.key}
                      data-testid={`view-thumb-${v.key}`}
                      onClick={() => setCarousel(i)}
                      className={`rounded-lg overflow-hidden border-2 aspect-[3/4] ${i === carousel ? "border-brand-gold" : "border-transparent"}`}
                    >
                      <PrivateImage fileId={v.file_id} className="w-full h-full object-cover" alt={v.label} />
                    </button>
                  ))}
                </div>

                {session?.engine !== "fashn" && (
                  <Alert className="mt-4 border-brand-gold/50 bg-brand-gold/5">
                    <AlertTriangle className="h-4 w-4 brand-gold" />
                    <AlertTitle className="font-medium">Preview mode</AlertTitle>
                    <AlertDescription className="text-xs text-muted-foreground">
                      These are free local previews. Add your FASHN API key in Admin → Settings to switch on real AI renders.
                    </AlertDescription>
                  </Alert>
                )}

                <div className="mt-4 flex gap-2">
                  <Button variant="outline" className="rounded-full gap-2" onClick={() => setStep(3)}>Adjust outfit</Button>
                  <Button data-testid="new-tryon" className="rounded-full gap-2" onClick={restart}>New try-on</Button>
                </div>
              </div>
            )}
          </div>

          {/* ITEMS USED */}
          <aside className="lg:col-span-5">
            <div className="bg-card border border-border rounded-2xl p-5" data-testid="items-used">
              <p className="overline-label text-muted-foreground">Items used in this outfit</p>
              <div className="mt-3 space-y-3">
                {(session?.items_used || selected).map((it) => {
                  const id = it.product_id || it.id;
                  const url = it.product_url || it.source_url;
                  const missing = !url || it.url_status === "missing";
                  return (
                    <div key={id} className="flex items-center gap-3">
                      <img src={it.image_url} alt="" className="w-14 h-16 rounded object-cover bg-muted" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{it.name}</p>
                        <p className="text-[11px] text-muted-foreground capitalize">
                          {it.category} · {it.platform || it.source_platform} {it.price != null && `· ${peso(it.price, it.currency)}`}
                        </p>
                        {it.rendered === false && (
                          <p className="text-[10px] text-amber-600 mt-0.5">Shown as a link (not painted onto the photo)</p>
                        )}
                      </div>
                      {missing ? (
                        <span className="text-[10px] text-muted-foreground border border-border rounded-full px-2 py-1">Link unavailable</span>
                      ) : (
                        <a
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`view-product-${id}`}
                          className="text-xs inline-flex items-center gap-1 rounded-full bg-foreground text-background px-3 py-1.5 hover:opacity-90"
                        >
                          View Product <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* CAMERA MODAL */}
      {camSlot && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" data-testid="camera-modal">
          <div className="bg-card rounded-2xl overflow-hidden max-w-md w-full">
            <div className="p-4 flex items-center justify-between border-b border-border">
              <p className="font-medium capitalize">Capture {camSlot} view</p>
              <button onClick={stopCam} aria-label="Close camera"><X size={18} /></button>
            </div>
            <div className="aspect-[3/4] bg-black flex items-center justify-center">
              {camError ? (
                <p className="text-sm text-white/80 px-6 text-center">{camError}</p>
              ) : (
                <video ref={videoRef} autoPlay playsInline className="w-full h-full object-cover" />
              )}
            </div>
            <div className="p-4 flex gap-2">
              {camError ? (
                <label className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2 rounded-full border border-border cursor-pointer hover:bg-secondary text-sm">
                  <Upload size={14} /> Upload from device
                  <input type="file" accept="image/*" className="hidden" onChange={(e) => { onFile(camSlot, e); stopCam(); }} />
                </label>
              ) : (
                <Button data-testid="camera-capture" className="flex-1 rounded-full" onClick={capture}>Capture</Button>
              )}
              <Button data-testid="camera-cancel" variant="ghost" className="rounded-full" onClick={stopCam}>Cancel</Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
