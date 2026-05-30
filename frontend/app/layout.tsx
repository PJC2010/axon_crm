import type { Metadata } from "next";
import { Roboto_Slab, Geist, Geist_Mono } from "next/font/google";
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
  title: "Smart CRM",
  description: "Local service business lead scoring dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`h-full ${robotoSlab.variable} ${geist.variable} ${geistMono.variable}`}>
      <body className="h-full">{children}</body>
    </html>
  );
}
