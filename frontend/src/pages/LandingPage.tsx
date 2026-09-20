import { ArrowRight, CloudSun, DatabaseZap, Hexagon, Map, Route, ShieldCheck, Sprout } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Turnstile, turnstileConfigured } from "../components/Turnstile";
import { preferredPilotSlug } from "../pilot/PilotContext";

export function LandingPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [captchaToken, setCaptchaToken] = useState<string>();
  const [error, setError] = useState("");
  const enterGuest = async () => {
    setError("");
    try {
      await auth.exploreAsGuest(captchaToken);
      navigate(`/app/${preferredPilotSlug()}/dashboard`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Guest access is temporarily unavailable.");
    }
  };
  return (
    <div className="marketing-shell">
      <header className="marketing-nav">
        <Link to="/" className="brand"><span className="brand-mark"><Hexagon size={25} /><i /></span><span><strong>SolarShepherd</strong><small>Evidence-led field intelligence</small></span></Link>
        <nav><a href="#method">How it works</a><a href="#science">Science</a><Link to="/login">Log in</Link><Link className="button primary" to="/signup">Create account</Link></nav>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-copy">
            <span className="kicker">THREE KENYA PILOTS · 10 KM EACH</span>
            <h1>Move livestock with evidence, not guesswork.</h1>
            <p>SolarShepherd combines real station telemetry, Earth observation, terrain and field samples into transparent routes and mission evidence.</p>
            <div className="hero-actions"><Link className="button primary" to="/signup">Start field work <ArrowRight size={16} /></Link><button className="button secondary" disabled={turnstileConfigured && !captchaToken} onClick={enterGuest}>Explore as guest</button></div>
            <Turnstile onToken={setCaptchaToken} />
            {error && <p className="form-error">{error}</p>}
          </div>
          <div className="hero-console panel">
            <div className="console-top"><span>FIELD CONSOLE // LIVE</span><span className="signal-dot" /></div>
            <div className="console-grid"><article><CloudSun /><span>Observed weather</span><strong>Traceable</strong></article><article><Map /><span>Landscape cells</span><strong>H3 · R9</strong></article><article><Route /><span>Route evidence</span><strong>A* + Tobler</strong></article><article><Sprout /><span>Biomass</span><strong>Locked</strong></article></div>
            <p>Every output carries its source, timestamp, quality flags and model version.</p>
          </div>
        </section>

        <section className="landing-band"><strong>REAL TELEMETRY</strong><strong>SENTINEL-2</strong><strong>COPERNICUS DEM</strong><strong>OPENSTREETMAP</strong><strong>OPEN-METEO</strong></section>

        <section id="method" className="landing-section">
          <span className="kicker">FIELD WORKFLOW</span><h2>From observation to a defensible mission.</h2>
          <div className="feature-grid"><article className="panel"><span>01</span><DatabaseZap /><h3>Observe</h3><p>Separate measured station data from forecast guidance and show freshness clearly.</p></article><article className="panel"><span>02</span><Map /><h3>Understand</h3><p>Inspect vegetation moisture, terrain, water proximity and scene-to-scene change.</p></article><article className="panel"><span>03</span><Route /><h3>Plan</h3><p>Create a mission route with positive, bounded and explainable travel costs.</p></article><article className="panel"><span>04</span><ShieldCheck /><h3>Prove</h3><p>Submit field samples and export a versioned PDF and JSON evidence receipt.</p></article></div>
        </section>

        <section id="science" className="science-promise panel"><ShieldCheck size={42} /><div><span className="panel-kicker">SCIENTIFIC GUARDRAIL</span><h2>No fabricated biomass. No hidden thresholds.</h2><p>Carrying capacity remains unavailable until local dry-matter samples support a reviewed and validated model. Forecasts never masquerade as observations.</p></div></section>

        <section className="landing-section faq-section"><span className="kicker">QUESTIONS</span><h2>Built for operators and institutions.</h2><details><summary>Can I try it without an account?</summary><p>Yes. Guest mode provides restricted, read-only access to JKUAT, Garissa and Lodwar.</p></details><details><summary>Can a member change scientific records?</summary><p>No. Submitted samples require system-owner review before entering the calibration registry.</p></details><details><summary>Does SolarShepherd predict carrying capacity?</summary><p>Not until an interpretable model has been trained and validated with real local samples.</p></details></section>
      </main>

      <footer className="marketing-footer"><div className="brand"><span className="brand-mark"><Hexagon size={22} /></span><strong>SolarShepherd</strong></div><p>Scientific field intelligence across three Kenya pilots.</p><nav><Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link><Link to="/login">Log in</Link></nav></footer>
    </div>
  );
}
