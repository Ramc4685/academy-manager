import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Manrope, Outfit } from "next/font/google";
import "./globals.css";
import { brand } from "@/lib/brand";
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

export const metadata: Metadata = {
  title: brand.productName,
  description: `${brand.productName} is a production operations platform for coaches, parents, and admins.`,
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: brand.productName,
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
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
