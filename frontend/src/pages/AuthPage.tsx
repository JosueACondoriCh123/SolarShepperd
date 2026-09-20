import { ArrowLeft, Hexagon, LockKeyhole, Mail } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Turnstile, turnstileConfigured } from "../components/Turnstile";
import { preferredPilotSlug } from "../pilot/PilotContext";

export function AuthPage({ mode }: { mode: "login" | "signup" | "forgot" | "reset" | "verify" }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [captchaToken, setCaptchaToken] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const consolePath = `/app/${preferredPilotSlug()}/dashboard`;
  if (auth.authenticated && mode === "login") return <Navigate to={consolePath} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(""); setMessage(""); setBusy(true);
    try {
      if ((mode === "signup" || mode === "reset") && password !== confirm) throw new Error("Passwords do not match.");
      if (mode === "login") {
        await auth.signIn(email, password, captchaToken);
        navigate((location.state as { from?: string } | null)?.from || consolePath);
      } else if (mode === "signup") {
        await auth.signUp(email, password, captchaToken);
        setMessage("Check your email to verify the account, then return to log in.");
      } else if (mode === "forgot") {
        await auth.requestPasswordReset(email, captchaToken);
        setMessage("If that account exists, a recovery message is on its way.");
      } else if (mode === "reset") {
        await auth.updatePassword(password);
        setMessage("Password updated. You can continue to the field console.");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed.");
    } finally { setBusy(false); }
  };

  const title = { login: "Welcome back", signup: "Create your field account", forgot: "Recover access", reset: "Choose a new password", verify: "Verify your email" }[mode];
  if (mode === "verify") return <AuthFrame title={title}><div className="auth-message"><Mail size={30} /><p>Your verification link has been processed. Continue to the console if your session is active, or log in with your verified email.</p><Link className="button primary" to={auth.authenticated ? consolePath : "/login"}>{auth.authenticated ? "Open console" : "Log in"}</Link></div></AuthFrame>;

  return <AuthFrame title={title}>
    <form className="auth-form" onSubmit={submit}>
      {mode !== "reset" && <label><span>Email address</span><input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>}
      {mode !== "forgot" && <label><span>{mode === "reset" ? "New password" : "Password"}</span><input required minLength={8} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} /></label>}
      {(mode === "signup" || mode === "reset") && <label><span>Confirm password</span><input required minLength={8} type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>}
      <Turnstile onToken={setCaptchaToken} />
      {error && <p className="form-error">{error}</p>}{message && <p className="form-success">{message}</p>}
      <button className="button primary wide" disabled={busy || (turnstileConfigured && !captchaToken)}>{busy ? "Working…" : title}</button>
      <div className="auth-links">{mode === "login" && <><Link to="/forgot-password">Forgot password?</Link><Link to="/signup">Create account</Link></>}{mode !== "login" && <Link to="/login">Return to login</Link>}</div>
    </form>
  </AuthFrame>;
}

function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return <main className="auth-shell"><section className="auth-card panel"><Link className="back-link" to="/"><ArrowLeft size={15} /> Back to SolarShepherd</Link><div className="auth-brand"><span className="brand-mark"><Hexagon size={25} /></span><LockKeyhole size={25} /></div><span className="panel-kicker">SECURE FIELD ACCESS</span><h1>{title}</h1><p>Accounts use verified email and every operational action is tied to its owner.</p>{children}</section></main>;
}
