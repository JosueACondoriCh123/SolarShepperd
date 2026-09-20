import { useEffect, useRef } from "react";

// eslint-disable-next-line react-refresh/only-export-components -- deployment capability flag
export const turnstileConfigured = Boolean(import.meta.env.VITE_TURNSTILE_SITE_KEY);

declare global {
  interface Window {
    turnstile?: {
      render: (target: HTMLElement, options: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
    };
  }
}

export function Turnstile({ onToken }: { onToken: (token: string | undefined) => void }) {
  const target = useRef<HTMLDivElement>(null);
  const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined;

  useEffect(() => {
    if (!siteKey || !target.current) return;
    let widgetId: string | undefined;
    const render = () => {
      if (!target.current || !window.turnstile || widgetId) return;
      widgetId = window.turnstile.render(target.current, {
        sitekey: siteKey,
        theme: "light",
        callback: (token: string) => onToken(token),
        "expired-callback": () => onToken(undefined),
      });
    };
    const existing = document.querySelector<HTMLScriptElement>("script[data-solarshepherd-turnstile]");
    if (existing) render();
    else {
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.dataset.solarshepherdTurnstile = "true";
      script.addEventListener("load", render);
      document.head.appendChild(script);
    }
    return () => {
      if (widgetId && window.turnstile) window.turnstile.remove(widgetId);
    };
  }, [onToken, siteKey]);

  if (!siteKey) return <p className="captcha-note">Bot protection activates in the deployed environment.</p>;
  return <div ref={target} className="turnstile-slot" />;
}
