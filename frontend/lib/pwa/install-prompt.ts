"use client";

import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
  prompt(): Promise<void>;
}

const DISMISSED_KEY = "pwa.install.dismissedUntil";
const DISMISS_FOR_MS = 30 * 24 * 60 * 60 * 1000;

/** S19: one dismissal window for every platform, iOS included. */
export function isInstallDismissed(
  storage: Pick<Storage, "getItem"> | null | undefined,
  now: number = Date.now(),
): boolean {
  try {
    return Number(storage?.getItem(DISMISSED_KEY) ?? 0) > now;
  } catch {
    return false;
  }
}

function rememberDismissal() {
  try {
    window.localStorage.setItem(DISMISSED_KEY, String(Date.now() + DISMISS_FOR_MS));
  } catch {
    // Private mode: the card hides for this page view only.
  }
}

/** S19: the install card belongs on the coach's home (Today), not every page. */
export function showInstallCardOn(pathname: string | null | undefined): boolean {
  return pathname === "/coach/today" || pathname === "/coach/today/";
}

export function useInstallPrompt() {
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissed(isInstallDismissed(window.localStorage));
    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      if (isInstallDismissed(window.localStorage)) return;
      setEvent(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setInstalled(true);
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const prompt = async (): Promise<"accepted" | "dismissed" | "unavailable"> => {
    if (!event) return "unavailable";
    await event.prompt();
    const result = await event.userChoice;
    setEvent(null);
    if (result.outcome === "dismissed") rememberDismissal();
    return result.outcome;
  };

  const dismiss = () => {
    rememberDismissal();
    setDismissed(true);
    setEvent(null);
  };

  return { canInstall: event !== null, installed, dismissed, prompt, dismiss };
}

/** Detect iOS Safari (no native install prompt; show instructions instead). */
export function useIsIOSSafari(): boolean {
  const [is, setIs] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const ua = window.navigator.userAgent;
    const isIOS = /iPhone|iPad|iPod/.test(ua) && !("MSStream" in window);
    const isSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as { standalone?: boolean }).standalone === true;
    setIs(isIOS && isSafari && !isStandalone);
  }, []);
  return is;
}
