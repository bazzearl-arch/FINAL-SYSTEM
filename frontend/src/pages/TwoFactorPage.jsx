import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ShieldCheck, Copy } from "lucide-react";

export default function TwoFactorPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const { twofaSetup, twofaEnable, twofaVerify } = useAuth();
  const st = loc.state || {};
  const mode = st.mode; // 'setup' | 'verify'
  const mfaToken = st.mfa_token;
  const email = st.email;
  const from = st.from;

  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [setupData, setSetupData] = useState(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (!mfaToken || !mode) {
      toast.error("Your sign-in session expired. Please sign in again.");
      nav("/login", { replace: true });
      return;
    }
    if (mode === "setup" && !loadedRef.current) {
      loadedRef.current = true;
      (async () => {
        const r = await twofaSetup(mfaToken);
        if (r.ok) setSetupData(r);
        else { toast.error(r.error); nav("/login", { replace: true }); }
      })();
    }
  }, [mfaToken, mode, nav, twofaSetup]);

  const finish = (user) => {
    toast.success("You're signed in");
    const dest = from || (user?.role === "admin" ? "/admin" : "/catalog");
    nav(dest, { replace: true });
  };

  const submit = async (e) => {
    e.preventDefault();
    const c = code.trim();
    if (!/^\d{6}$/.test(c)) { toast.error("Enter the 6-digit code from your authenticator app"); return; }
    setBusy(true);
    const r = mode === "setup"
      ? await twofaEnable(mfaToken, c)
      : await twofaVerify(mfaToken, c);
    setBusy(false);
    if (r.ok) finish(r.user);
    else toast.error(r.error);
  };

  const copySecret = () => {
    if (setupData?.secret) {
      try { navigator.clipboard?.writeText(setupData.secret); toast.success("Secret key copied"); }
      catch (e) { /* noop */ }
    }
  };

  const isSetup = mode === "setup";

  return (
    <main data-testid="twofa-page" className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-md bg-card border border-border rounded-2xl shadow-sm p-8">
        <div className="flex items-center gap-2 text-primary">
          <ShieldCheck size={20} />
          <p className="overline-label text-muted-foreground">Two-factor authentication</p>
        </div>
        <h1 className="font-serif text-3xl mt-2">
          {isSetup ? "Secure your account" : "Verify it's you"}
        </h1>
        <p className="text-sm text-muted-foreground mt-2">
          {isSetup
            ? "Scan the QR code with an authenticator app (Google Authenticator, Authy, 1Password), then enter the 6-digit code to finish."
            : `Enter the 6-digit code from your authenticator app${email ? ` for ${email}` : ""}.`}
        </p>

        {isSetup && (
          <div className="mt-6 flex flex-col items-center">
            {setupData ? (
              <>
                <div className="bg-white p-3 rounded-xl border border-border">
                  <img data-testid="twofa-qr" src={setupData.qr} alt="2FA QR code" className="w-44 h-44" />
                </div>
                <p className="text-xs text-muted-foreground mt-3">Can't scan? Enter this key manually:</p>
                <button
                  type="button"
                  onClick={copySecret}
                  className="mt-1 flex items-center gap-2 font-mono text-sm bg-muted px-3 py-1.5 rounded-lg hover:bg-muted/70"
                  title="Copy secret key"
                >
                  <span data-testid="twofa-secret">{setupData.secret}</span>
                  <Copy size={14} />
                </button>
              </>
            ) : (
              <div className="w-44 h-44 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
              </div>
            )}
          </div>
        )}

        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <Label htmlFor="otp">6-digit code</Label>
            <Input
              data-testid="twofa-code"
              id="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              className="tracking-[0.5em] text-center text-lg font-mono"
              required
            />
          </div>
          <Button data-testid="twofa-submit" type="submit" className="w-full rounded-full h-11" disabled={busy || (isSetup && !setupData)}>
            {busy ? "Verifying\u2026" : isSetup ? "Enable & continue" : "Verify & continue"}
          </Button>
        </form>

        <p className="mt-6 text-sm text-center text-muted-foreground">
          <Link to="/login" className="underline underline-offset-4">Back to sign in</Link>
        </p>
      </div>
    </main>
  );
}
