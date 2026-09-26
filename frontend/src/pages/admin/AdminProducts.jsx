import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Pencil, Trash2, Plus, AlertTriangle, CheckCircle2, ExternalLink } from "lucide-react";

// Canonical categories that the backend expects.
const CATEGORIES = [
  "tops",
  "bottoms",
  "one-pieces",
  "outerwear",
  "shoes",
  "bags",
  "jewelry",
  "hats",
  "accessories",
];

const GENDERS = ["women", "men", "unisex"];
const PLATFORMS = ["Lazada", "Shopee", "Zalora PH", "Tik Tok Shop", "Bench", "Kultura", "Penshoppe", "Other"];

const EMPTY = {
  name: "",
  description: "",
  brand: "",
  category: "tops",
  subcategory: "",
  gender: "unisex",
  style: [],
  color: "",
  price: 0,
  currency: "PHP",
  image_url: "",
  source_platform: "Lazada",
  product_url: "",
  tags: [],
  active: true,
};

function urlStatusOf(p) {
  if (p.url_status) return p.url_status;
  const url = p.product_url || p.source_url;
  return url ? "ok" : "missing";
}

export default function AdminProducts() {
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [filter, setFilter] = useState("all"); // all | missing

  const load = async () => {
    const { data } = await api.get("/admin/products");
    setProducts(data);
  };

  useEffect(() => { load(); }, []);

  const startCreate = () => { setEditing(null); setForm(EMPTY); setOpen(true); };
  const startEdit = (p) => {
    setEditing(p.id);
    setForm({
      ...EMPTY,
      ...p,
      product_url: p.product_url || p.source_url || "",
      style: p.style || [],
      tags: p.tags || [],
    });
    setOpen(true);
  };

  const submit = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    if (!form.image_url.trim()) { toast.error("Image URL is required"); return; }
    const purl = (form.product_url || "").trim();
    if (purl && !/^https?:\/\//i.test(purl)) {
      toast.error("Product URL must start with http(s)://");
      return;
    }
    const payload = {
      ...form,
      product_url: purl || null,
      price: Number(form.price) || 0,
      style: Array.isArray(form.style) ? form.style : String(form.style).split(",").map(s=>s.trim()).filter(Boolean),
      tags: Array.isArray(form.tags) ? form.tags : String(form.tags).split(",").map(s=>s.trim()).filter(Boolean),
    };
    try {
      if (editing) await api.put(`/admin/products/${editing}`, payload);
      else await api.post("/admin/products", payload);
      setOpen(false);
      toast.success(editing ? "Product updated" : "Product created");
      load();
    } catch (e) { toast.error("Save failed"); }
  };

  const del = async (id) => {
    if (!confirm("Delete this product?")) return;
    await api.delete(`/admin/products/${id}`);
    toast.success("Deleted");
    load();
  };

  const filtered = products.filter((p) =>
    filter === "missing" ? urlStatusOf(p) !== "ok" : true
  );
  const missingCount = products.filter((p) => urlStatusOf(p) !== "ok").length;

  return (
    <div data-testid="admin-products">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <p className="overline-label text-muted-foreground">Catalog</p>
          <h1 className="font-serif text-3xl mt-2">Product management</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Every product must have an <strong>exact</strong> product URL — never a platform homepage.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-full border border-border p-1 flex text-xs">
            <button
              data-testid="filter-all"
              onClick={() => setFilter("all")}
              className={`px-3 py-1 rounded-full ${filter === "all" ? "bg-foreground text-background" : ""}`}
            >
              All ({products.length})
            </button>
            <button
              data-testid="filter-missing"
              onClick={() => setFilter("missing")}
              className={`px-3 py-1 rounded-full ${filter === "missing" ? "bg-foreground text-background" : ""}`}
            >
              Missing URL ({missingCount})
            </button>
          </div>
          <Button onClick={startCreate} className="rounded-full gap-2" data-testid="admin-add-product">
            <Plus size={14} /> Add product
          </Button>
        </div>
      </div>

      {missingCount > 0 && (
        <div className="mb-4 rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4 flex items-start gap-3" data-testid="missing-url-banner">
          <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium">{missingCount} product{missingCount === 1 ? "" : "s"} missing an exact URL</p>
            <p className="text-xs text-muted-foreground mt-1">
              Customers will see “Link unavailable” instead of a Shop button until you paste the exact Lazada/Shopee/Zalora/TikTok Shop product page URL.
            </p>
          </div>
        </div>
      )}

      <div className="bg-card border border-border rounded-2xl overflow-hidden">
        <table className="w-full text-sm" data-testid="admin-products-table">
          <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="text-left px-4 py-3">Image</th>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Gender</th>
              <th className="text-left px-4 py-3">Category</th>
              <th className="text-left px-4 py-3">Platform</th>
              <th className="text-left px-4 py-3">URL</th>
              <th className="text-right px-4 py-3">Price</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground text-sm">No products.</td></tr>
            )}
            {filtered.map((p) => {
              const status = urlStatusOf(p);
              const url = p.product_url || p.source_url;
              return (
                <tr key={p.id} className="border-t border-border hover:bg-muted/30">
                  <td className="px-4 py-2"><img src={p.image_url} alt="" className="w-12 h-14 rounded object-cover" /></td>
                  <td className="px-4 py-2">
                    <p className="font-medium">{p.name}</p>
                    <p className="text-xs text-muted-foreground">{p.brand || "—"}</p>
                  </td>
                  <td className="px-4 py-2 capitalize text-xs">{p.gender || "unisex"}</td>
                  <td className="px-4 py-2 capitalize text-xs">{p.category}</td>
                  <td className="px-4 py-2 text-xs">{p.source_platform || "—"}</td>
                  <td className="px-4 py-2">
                    {status === "ok" ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-emerald-600 text-xs"
                        data-testid={`url-ok-${p.id}`}
                      >
                        <CheckCircle2 size={12} /> exact <ExternalLink size={10} />
                      </a>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-amber-600 text-xs" data-testid={`url-missing-${p.id}`}>
                        <AlertTriangle size={12} /> missing
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">₱{Number(p.price || 0).toLocaleString()}</td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    <Button size="icon" variant="ghost" onClick={() => startEdit(p)} data-testid={`admin-edit-${p.id}`}><Pencil size={14} /></Button>
                    <Button size="icon" variant="ghost" onClick={() => del(p.id)} data-testid={`admin-delete-${p.id}`}><Trash2 size={14} /></Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="admin-product-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit product" : "New product"}</DialogTitle>
          </DialogHeader>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Name" required>
              <Input data-testid="admin-form-name" value={form.name} onChange={(e)=>setForm({...form, name: e.target.value})} />
            </Field>
            <Field label="Brand">
              <Input value={form.brand} onChange={(e)=>setForm({...form, brand: e.target.value})} />
            </Field>

            <Field label="Gender">
              <select
                data-testid="admin-form-gender"
                value={form.gender}
                onChange={(e)=>setForm({...form, gender: e.target.value})}
                className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
              >
                {GENDERS.map((g)=><option key={g} value={g}>{g}</option>)}
              </select>
            </Field>

            <Field label="Category">
              <select
                data-testid="admin-form-category"
                value={form.category}
                onChange={(e)=>setForm({...form, category: e.target.value})}
                className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
              >
                {CATEGORIES.map((c)=><option key={c} value={c}>{c}</option>)}
              </select>
            </Field>

            <Field label="Subcategory">
              <Input value={form.subcategory || ""} onChange={(e)=>setForm({...form, subcategory: e.target.value})} />
            </Field>
            <Field label="Price (PHP)">
              <Input data-testid="admin-form-price" type="number" value={form.price} onChange={(e)=>setForm({...form, price: e.target.value})} />
            </Field>

            <Field label="Color">
              <Input value={form.color || ""} onChange={(e)=>setForm({...form, color: e.target.value})} />
            </Field>
            <Field label="Styles (comma sep)">
              <Input value={Array.isArray(form.style) ? form.style.join(", ") : form.style} onChange={(e)=>setForm({...form, style: e.target.value})} />
            </Field>

            <Field label="Image URL" required className="sm:col-span-2">
              <Input data-testid="admin-form-image" value={form.image_url} onChange={(e)=>setForm({...form, image_url: e.target.value})} placeholder="https://..." />
            </Field>

            <Field label="Platform / Store">
              <select
                data-testid="admin-form-platform"
                value={form.source_platform}
                onChange={(e)=>setForm({...form, source_platform: e.target.value})}
                className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
              >
                {PLATFORMS.map((p)=><option key={p} value={p}>{p}</option>)}
              </select>
            </Field>

            <Field label="Tags (comma sep)">
              <Input value={Array.isArray(form.tags) ? form.tags.join(", ") : form.tags} onChange={(e)=>setForm({...form, tags: e.target.value})} />
            </Field>

            <Field label="Exact Product URL" className="sm:col-span-2" hint="Paste the EXACT product page URL (not the store homepage).">
              <Input
                data-testid="admin-form-product-url"
                value={form.product_url || ""}
                onChange={(e)=>setForm({...form, product_url: e.target.value})}
                placeholder="https://shopee.ph/product-i.123.456"
              />
              {form.product_url && !/^https?:\/\//i.test(form.product_url) && (
                <p className="text-xs text-destructive mt-1">Must start with http:// or https://</p>
              )}
              {!form.product_url && (
                <p className="text-xs text-amber-600 mt-1 inline-flex items-center gap-1">
                  <AlertTriangle size={12} /> Without this, the product will be marked “missing URL”.
                </p>
              )}
            </Field>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={()=>setOpen(false)}>Cancel</Button>
            <Button onClick={submit} data-testid="admin-form-submit">{editing ? "Save" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Field({ label, children, className = "", required = false, hint = "" }) {
  return (
    <div className={className}>
      <Label className="text-xs uppercase tracking-wider text-muted-foreground">
        {label}{required && <span className="text-destructive"> *</span>}
      </Label>
      {hint && <p className="text-[10px] text-muted-foreground mt-0.5">{hint}</p>}
      <div className="mt-1.5">{children}</div>
    </div>
  );
}
