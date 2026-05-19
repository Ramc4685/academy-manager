"use client";

import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
  prompt(): Promise<void>;
}

const DISMISSED_KEY = "pwa.install.dismissedUntil";

export function useInstallPrompt() {
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      // Respect dismissal window (30 days).
      const until = Number(window.localStorage.getItem(DISMISSED_KEY) ?? 0);
      if (until > Date.now()) return;
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
    if (result.outcome === "dismissed") {
      const thirtyDays = 30 * 24 * 60 * 60 * 1000;
      window.localStorage.setItem(DISMISSED_KEY, String(Date.now() + thirtyDays));
    }
    return result.outcome;
  };

  const dismiss = () => {
    const thirtyDays = 30 * 24 * 60 * 60 * 1000;
    window.localStorage.setItem(DISMISSED_KEY, String(Date.now() + thirtyDays));
    setEvent(null);
  };

  return { canInstall: event !== null, installed, prompt, dismiss };
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
