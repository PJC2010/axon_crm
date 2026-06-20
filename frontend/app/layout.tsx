import type { Metadata, Viewport } from "next";
import { Roboto_Slab, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

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

export const metadata: Metadata = {
  title: "Axon",
  description: "Built on data, focused on people.",
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
    </html>
  );
}
