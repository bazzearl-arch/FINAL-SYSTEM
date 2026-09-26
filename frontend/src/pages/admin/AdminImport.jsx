import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { AlertTriangle, CheckCircle2, XCircle, RefreshCw, Wallet } from "lucide-react";
import { toast } from "sonner";

const EXAMPLE_JSON = JSON.stringify(
  [
    {
      name: "Sample Sneaker",
      image_url: "https://images.unsplash.com/photo-1549298916-b41d501d3772?w=800",
      category: "shoes",
      brand: "SampleBrand",
      price: 1499,
      currency: "PHP",
      style: ["Casual", "Streetwear"],
      source_platform: "manual",
      source_id: "sneaker-001",
    },
  ],
  null,
  2
);

const EXAMPLE_CSV = `product_name,gender,category,price,currency,image_url,product_url,platform,garment_photo_type
Classic White Tee,men,tops,499,PHP,https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600,https://shopee.ph/classic-white-tee-i.111.222,Shopee,model
Pleated Midi Skirt,women,bottoms,899,PHP,https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?w=600,https://www.lazada.com.ph/products/pleated-midi-skirt-i123.html,Lazada,flat-lay`;

export default function AdminImport() {
  const [json, setJson] = useState(EXAMPLE_JSON);
  const [csv, setCsv] = useState(EXAMPLE_CSV);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [lastResult, setLastResult] = useState(null);
  const [settings, setSettings] = useState(null);
  const [credits, setCredits] = useState(null);
  const [creditsBusy, setCreditsBusy] = useState(false);

  const loadJobs = async () => {
    try { const { data } = await api.get("/admin/import/jobs"); setJobs(data); } catch (_e) { /* silent */ }
  };
  const loadSettings = async () => {
    try { const { data } = await api.get("/admin/settings"); setSettings(data); } catch (_e) { /* silent */ }
  };
  const loadCredits = async ({ silent } = {}) => {
    setCreditsBusy(true);
    try {
      const { data } = await api.get("/admin/fashn/credits");
      setCredits(data);
      if (!silent && data?.ok) toast.success(`FASHN credits: ${data.total}`);
      if (!silent && !data?.ok && data?.configured) toast.error(data.error || "Could not fetch credits");
    } catch (e) {
      if (!silent) toast.error("Could not fetch FASHN credits");
    } finally {
      setCreditsBusy(false);
    }
  };
  useEffect(() => { loadJobs(); loadSettings(); loadCredits({ silent: true }); }, []);

  const saveSettings = async (patch) => {
    try {
      const { data } = await api.put("/admin/settings", patch);
      setSettings(data);
      toast.success("Settings saved");
    } catch { toast.error("Could not save settings"); }
  };

  const submitCsv = async () => {
    setBusy(true); setLastResult(null);
    try {
      const { data } = await api.post("/admin/import/csv", { payload: csv });
      setLastResult({ ...data, message: `CSV: ${data.saved} saved, ${data.errors} errors` });
      if (data.saved > 0) toast.success(`Imported ${data.saved} products`);
      else toast.error("No products imported — check your columns");
    } catch (e) { toast.error("CSV import failed"); }
    setBusy(false); loadJobs();
  };

  const submitJson = async () => {
    setBusy(true); setLastResult(null);
    try {
      const { data } = await api.post("/admin/import/json", { payload: json, auto_save: true });
      setLastResult(data);
      if (data.status === "success") toast.success(`Imported ${data.saved} products`);
      else if (data.status === "partial") toast.warning(`Partial: ${data.saved} saved, ${data.errors} errors`);
      else toast.error(data.message);
    } catch (e) { toast.error("Import failed"); }
    setBusy(false); loadJobs();
  };

  const submitUrl = async () => {
    if (!url) { toast.error("Paste a URL"); return; }
    setBusy(true); setLastResult(null);
    try {
      const { data } = await api.post("/admin/import/url", { url, auto_save: true });
      setLastResult(data);
      if (data.status === "success") toast.success(`Imported ${data.saved} from ${data.source}`);
      else if (data.status === "partial") toast.warning(`Partial from ${data.source}: ${data.saved} saved`);
      else toast.error(`${data.source}: ${data.message?.slice(0,120) || "Failed"}`);
    } catch (e) { toast.error("Import failed"); }
    setBusy(false); loadJobs();
  };

  return (
    <div data-testid="admin-import">
      <p className="overline-label text-muted-foreground">Product Sources</p>
      <h1 className="font-serif text-3xl mt-2 mb-6">Import catalog</h1>

      {/* Try-On engine settings */}
      <div className="mb-6 bg-card border border-border rounded-2xl p-6" data-testid="tryon-settings">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <p className="overline-label text-muted-foreground">Try-On Engine</p>
            <h3 className="font-serif text-xl mt-1">Rendering settings</h3>
          </div>
          {settings && (
            <span className={`text-xs rounded-full px-3 py-1 border ${settings.fashn_key_configured ? "border-emerald-500/40 text-emerald-600" : "border-amber-500/40 text-amber-600"}`}>
              FASHN key: {settings.fashn_key_configured ? "configured" : "not set"}
            </span>
          )}
        </div>
        {settings && (
          <div className="mt-4 grid sm:grid-cols-3 gap-4 text-sm">
            <div>
              <Label className="text-xs">Engine</Label>
              <select
                data-testid="setting-engine"
                value={settings.engine}
                onChange={(e) => saveSettings({ engine: e.target.value })}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2"
              >
                <option value="mock">Mock (free preview)</option>
                <option value="fashn" disabled={!settings.fashn_key_configured}>
                  FASHN (real AI{settings.fashn_key_configured ? "" : " — add key"})
                </option>
              </select>
            </div>
            <div>
              <Label className="text-xs">Quality mode</Label>
              <select
                data-testid="setting-mode"
                value={settings.mode}
                onChange={(e) => saveSettings({ mode: e.target.value })}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2"
              >
                <option value="fast">Fast (cheapest)</option>
                <option value="balanced">Balanced</option>
                <option value="quality">Quality</option>
              </select>
            </div>
            <div>
              <Label className="text-xs">Resolution</Label>
              <select
                data-testid="setting-resolution"
                value={settings.resolution}
                onChange={(e) => saveSettings({ resolution: e.target.value })}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2"
              >
                <option value="1k">1K</option>
                <option value="2k">2K</option>
                <option value="4k">4K</option>
              </select>
            </div>
          </div>
        )}
        {settings && !settings.fashn_key_configured && (
          <p className="text-xs text-muted-foreground mt-3">
            To enable real AI renders, add your FASHN API key as <code className="font-mono">FASHN_API_KEY</code> on the backend, then switch the engine to FASHN.
          </p>
        )}
      </div>

      {settings?.fashn_key_configured && (
        (() => {
          const total = credits?.ok ? credits.total : null;
          const lowThreshold = 20;
          const low = total !== null && total < lowThreshold;
          const empty = total !== null && total <= 0;
          const perViewCost = { fast: 1, balanced: 2, quality: 4 }[settings?.mode || "balanced"] || 2;
          const rendersLeft = total !== null ? Math.floor(total / (perViewCost * 4)) : null; // 1-item, 4 views
          const barColor = empty
            ? "bg-red-500"
            : low
              ? "bg-amber-500"
              : "bg-emerald-500";
          const pct = total === null ? 0 : Math.min(100, Math.round((total / 100) * 100));
          return (
            <div
              className={`mb-6 rounded-2xl border p-6 ${
                empty
                  ? "border-red-500/40 bg-red-500/5"
                  : low
                    ? "border-amber-500/40 bg-amber-500/5"
                    : "border-border bg-card"
              }`}
              data-testid="fashn-credit-meter"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl bg-background/60 border border-border p-2.5">
                    <Wallet className="h-5 w-5 text-emerald-600" />
                  </div>
                  <div>
                    <p className="overline-label text-muted-foreground">FASHN Credits</p>
                    <h3 className="font-serif text-xl mt-1">
                      {credits?.ok ? (
                        <>
                          <span data-testid="fashn-credit-total">{total}</span>
                          <span className="text-muted-foreground text-base ml-1">credits</span>
                        </>
                      ) : credits?.configured === false ? (
                        "Not configured"
                      ) : credits === null ? (
                        <span className="text-muted-foreground">Loading…</span>
                      ) : (
                        <span className="text-red-600">Unavailable</span>
                      )}
                    </h3>
                    {credits?.ok && (
                      <p className="text-xs text-muted-foreground mt-1">
                        On-demand: <span data-testid="fashn-credit-ondemand">{credits.on_demand}</span>
                        {" · "}Subscription: <span data-testid="fashn-credit-sub">{credits.subscription}</span>
                        {rendersLeft !== null && (
                          <> {" · "}~<span data-testid="fashn-renders-left">{rendersLeft}</span> single-item try-ons left at {settings?.mode || "balanced"}/{settings?.resolution || "1k"}</>
                        )}
                      </p>
                    )}
                    {credits && !credits.ok && credits.configured && (
                      <p className="text-xs text-red-600 mt-1" data-testid="fashn-credit-error">
                        {credits.error}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => loadCredits()}
                    disabled={creditsBusy}
                    data-testid="fashn-credit-refresh"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${creditsBusy ? "animate-spin" : ""}`} />
                    Refresh
                  </Button>
                  <a
                    href="https://app.fashn.ai/billing"
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-muted-foreground underline hover:text-foreground"
                    data-testid="fashn-topup-link"
                  >
                    Top up ↗
                  </a>
                </div>
              </div>

              {credits?.ok && (
                <div className="mt-4">
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full ${barColor} transition-all`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  {empty && (
                    <p className="text-xs text-red-600 mt-2" data-testid="fashn-credit-empty">
                      Out of credits. Top up before running more try-ons — new sessions will fail.
                    </p>
                  )}
                  {low && !empty && (
                    <p className="text-xs text-amber-600 mt-2" data-testid="fashn-credit-low">
                      Low balance ({total} credits). About {rendersLeft} single-item try-ons left — consider topping up.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })()
      )}

      <Alert className="mb-6 border-amber-500/50 bg-amber-500/5">
        <AlertTriangle className="h-4 w-4 text-amber-600" />
        <AlertTitle>Scraper honesty notice</AlertTitle>
        <AlertDescription className="text-sm text-muted-foreground">
          Lazada and Shopee load product data via JavaScript and actively block basic scraping.
          Expect frequent failures — jobs are logged with their true status (no fabricated success).
          For production data, use their official partner/affiliate feeds and paste them as CSV or JSON below.
        </AlertDescription>
      </Alert>

      <Tabs defaultValue="csv">
        <TabsList className="rounded-full bg-muted p-1 h-auto mb-6">
          <TabsTrigger data-testid="import-tab-csv" value="csv" className="rounded-full px-5">CSV Upload</TabsTrigger>
          <TabsTrigger data-testid="import-tab-url" value="url" className="rounded-full px-5">Web URL Scrape</TabsTrigger>
          <TabsTrigger data-testid="import-tab-json" value="json" className="rounded-full px-5">JSON Feed</TabsTrigger>
        </TabsList>

        <TabsContent value="csv">
          <div className="bg-card border border-border rounded-2xl p-6 space-y-4">
            <Label>Paste CSV — columns: product_name, gender, category, price, currency, image_url, product_url, platform, garment_photo_type</Label>
            <Textarea
              data-testid="import-csv-input"
              value={csv}
              onChange={(e) => setCsv(e.target.value)}
              rows={10}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              gender: men/women/unisex · category: tops, bottoms, one-pieces, outerwear, shoes, bags, jewelry, hats, accessories ·
              product_url must be the EXACT item page (rows without it are flagged “missing”).
            </p>
            <Button data-testid="import-csv-submit" onClick={submitCsv} disabled={busy} className="rounded-full">
              {busy ? "Importing…" : "Import CSV"}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="url">
          <div className="bg-card border border-border rounded-2xl p-6 space-y-4">
            <Label>Product URL (Lazada, Shopee, or any site with JSON-LD product schema)</Label>
            <Input
              data-testid="import-url-input"
              value={url}
              onChange={(e)=>setUrl(e.target.value)}
              placeholder="https://www.lazada.com.ph/products/..."
            />
            <Button data-testid="import-url-submit" onClick={submitUrl} disabled={busy} className="rounded-full">
              {busy ? "Scraping…" : "Fetch & Import"}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="json">
          <div className="bg-card border border-border rounded-2xl p-6 space-y-4">
            <Label>JSON array of products</Label>
            <Textarea
              data-testid="import-json-input"
              value={json}
              onChange={(e)=>setJson(e.target.value)}
              rows={14}
              className="font-mono text-xs"
            />
            <Button data-testid="import-json-submit" onClick={submitJson} disabled={busy} className="rounded-full">
              {busy ? "Importing…" : "Import JSON"}
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {lastResult && (
        <div className="mt-6 bg-card border border-border rounded-2xl p-6" data-testid="import-last-result">
          <div className="flex items-center gap-2 mb-3">
            {lastResult.status === "success" && <CheckCircle2 size={16} className="text-emerald-500" />}
            {lastResult.status === "partial" && <AlertTriangle size={16} className="text-amber-500" />}
            {lastResult.status === "failed" && <XCircle size={16} className="text-destructive" />}
            <p className="font-medium uppercase text-xs tracking-wider">{lastResult.status}</p>
          </div>
          <p className="text-sm text-muted-foreground">{lastResult.message}</p>
          <p className="text-xs font-mono text-muted-foreground mt-2">
            imported={lastResult.imported} · saved={lastResult.saved} · errors={lastResult.errors}
          </p>
          {lastResult.products_preview?.length > 0 && (
            <div className="mt-4 grid grid-cols-2 sm:grid-cols-5 gap-2">
              {lastResult.products_preview.map((p, i) => (
                <div key={i} className="rounded-lg overflow-hidden border border-border bg-muted">
                  {p.image_url && <img src={p.image_url} alt="" className="w-full aspect-square object-cover" />}
                  <p className="text-[10px] p-2 truncate">{p.name}</p>
                </div>
              ))}
            </div>
          )}
          {lastResult.error_samples?.length > 0 && (
            <div className="mt-3 text-xs text-destructive font-mono space-y-1">
              {lastResult.error_samples.slice(0,5).map((e,i) => <p key={i}>{e}</p>)}
            </div>
          )}
        </div>
      )}

      <div className="mt-8">
        <h3 className="font-serif text-xl mb-3">Recent import jobs</h3>
        <div className="bg-card border border-border rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-3">Time</th>
                <th className="text-left px-4 py-3">Source</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-right px-4 py-3">Imported/Saved/Errors</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">No import jobs yet.</td></tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs">{new Date(j.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-2">{j.source}</td>
                  <td className="px-4 py-2">
                    <span className={`uppercase text-xs tracking-wider ${
                      j.status === "success" ? "text-emerald-600" :
                      j.status === "partial" ? "text-amber-600" : "text-destructive"
                    }`}>{j.status}</span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs">
                    {j.imported ?? 0} / {j.saved ?? 0} / {j.errors ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
