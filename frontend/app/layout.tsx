import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { brand } from "@/lib/brand";
import { publicPageBrand } from "@/lib/public-page/metadata";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";
import { Providers } from "@/lib/providers";
import { SentryInit } from "@/components/observability/sentry-init";

// Self-hosted (latin subset of the Google Fonts variable files): next/font/google
// fetched and parsed Google's CSS at build time, and an unparseable response
// broke the 2026-10-29 production deploy and an E2E run.
const manrope = localFont({
  src: "./fonts/manrope-latin.woff2",
  weight: "200 800",
  display: "swap",
  variable: "--font-manrope",
});

const outfit = localFont({
  src: "./fonts/outfit-latin.woff2",
  weight: "100 900",
  display: "swap",
  variable: "--font-outfit",
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin.woff2",
  weight: "500 700",
  display: "swap",
  variable: "--font-jetbrains-mono",
});

/**
 * Row 15: the tab title and apple-web-app title read the academy's name on
 * an academy host, `brand.productName` on the platform host. Every other
 * route (admin, parent, coach…) inherits this root metadata, so a per-host
 * title needs no per-route work.
 *
 * The dynamic manifest route is deferred (row 15 rest); `/manifest.webmanifest`
 * stays the static, platform-branded file.
 */
export async function generateMetadata(): Promise<Metadata> {
  const { result } = await loadPublicAcademyPage();
  const academy = publicPageBrand(result);
  const title = academy?.name || brand.productName;
  return {
    title,
    description: `${brand.productName} is a production operations platform for coaches, parents, and admins.`,
    manifest: "/manifest.webmanifest",
    appleWebApp: {
      capable: true,
      statusBarStyle: "black-translucent",
      title,
    },
  };
}

export const viewport: Viewport = {
  themeColor: "#0f172a",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${manrope.variable} ${outfit.variable} ${jetbrainsMono.variable} min-h-screen bg-white font-body text-neutral-900 antialiased dark:bg-neutral-950 dark:text-neutral-100`}
      >
        <SentryInit />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
