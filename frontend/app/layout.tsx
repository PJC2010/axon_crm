import type { Metadata } from "next";
import { Roboto_Slab, Geist, Geist_Mono } from "next/font/google";
import "./blueprint-app.css";
import "./globals.css";

const robotoSlab = Roboto_Slab({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-display",
});

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Axon",
  description: "Built on data, focused on people.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${robotoSlab.variable} ${geist.variable} ${geistMono.variable}`}>
      <body><div className="bp6-dark">{children}</div></body>
    </html>
  );
}
