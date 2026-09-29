import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Manrope, Outfit } from "next/font/google";
import "./globals.css";
import { brand } from "@/lib/brand";
import { publicPageBrand } from "@/lib/public-page/metadata";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";
import { Providers } from "@/lib/providers";
import { SentryInit } from "@/components/observability/sentry-init";

const manrope = Manrope({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-manrope",
});

const outfit = Outfit({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-outfit",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
  weight: ["500", "600", "700"],
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
