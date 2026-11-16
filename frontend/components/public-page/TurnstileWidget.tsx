"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";

interface TurnstileApi {
  render: (
    element: HTMLElement,
    options: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/**
 * Cloudflare Turnstile for the trial booking (L9). Rendered only while a date
 * is being booked; `onToken("")` when the token expires or the check errors,
 * so the form never sends a stale token. The server verifies it and fails
 * closed. CSP: challenges.cloudflare.com in script-src and frame-src.
 */
export function TurnstileWidget({
  siteKey,
  onToken,
}: {
  siteKey: string;
  onToken: (token: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const latest = useRef(onToken);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    latest.current = onToken;
  }, [onToken]);

  useEffect(() => {
    const api = window.turnstile;
    if (!ready || !api || !box.current) return;
    const widgetId = api.render(box.current, {
      sitekey: siteKey,
      callback: (token) => latest.current(token),
      "expired-callback": () => latest.current(""),
      "error-callback": () => latest.current(""),
    });
    return () => api.remove(widgetId);
  }, [ready, siteKey]);

  return (
    <>
      <Script src={SCRIPT_SRC} strategy="afterInteractive" onReady={() => setReady(true)} />
      <div ref={box} data-testid="trial-turnstile" />
    </>
  );
}
