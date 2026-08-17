import type { Metadata, Viewport } from "next";
import { Roboto_Slab, Geist, Geist_Mono } from "next/font/google";
import { GoogleAnalytics } from "@next/third-parties/google";
import "./globals.css";

// Google Analytics 4 measurement ID (G-XXXXXXX). Optional — analytics is off
// entirely when unset, matching the repo-wide "missing key = feature skipped"
// convention. Page views (including client-side route changes) are tracked
// automatically by the GoogleAnalytics component; custom events go through
// lib/analytics.ts.
const GA_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;

// Brand fonts. Distinct variable names (not --font-display/-sans/-mono) so they
// don't collide with the semantic font tokens defined in globals.css; those
// tokens reference these variables with a system-font fallback chain.
const robotoSlab = Roboto_Slab({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-roboto-slab",
  display: "swap",
});

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

// Canonical origin for absolute URLs (canonicals, OG images, sitemap).
// NEXT_PUBLIC_SITE_URL (set in Vercel) overrides; the fallback is the
// production domain so absolute URLs are right even without the env var.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://axonhtx.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  applicationName: "Axon",
  title: {
    default: "Axon — Territory intelligence for Harris County contractors",
    template: "%s — Axon",
  },
  description:
    "Axon ranks every property in your Harris County service area from appraisal, permit, equity, and storm data — and shows the signals behind every score, plus quotes, invoicing, and pipeline to work the list.",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "Axon",
    locale: "en_US",
    url: "/",
    title: "Axon — Territory intelligence for Harris County contractors",
    description:
      "Know which properties are worth calling first. Ranked from Harris County appraisal, permit, equity, and storm data. Every score explained. No shared leads. No contracts.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Axon — Territory intelligence for Harris County contractors",
    description:
      "Know which properties are worth calling first — ranked from local records, with every score explained.",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

// Mobile-first viewport: lock the layout viewport to the device width at 1×
// scale so the full page fits on a phone without horizontal zoom-out. Pinch
// zoom stays available (up to 5×) for accessibility.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  minimumScale: 1,
  maximumScale: 5,
  userScalable: true,
  viewportFit: "cover",
  themeColor: "#252a31",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${robotoSlab.variable} ${geist.variable} ${geistMono.variable}`}>
      <body>{children}</body>
      {GA_ID && <GoogleAnalytics gaId={GA_ID} />}
    </html>
  );
}
