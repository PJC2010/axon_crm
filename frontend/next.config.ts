import type { NextConfig } from "next";

// A Vercel production build without NEXT_PUBLIC_API_URL would compile green
// and ship every API call pointed at http://127.0.0.1:8000 (the local-dev
// fallback in lib/api.ts) — a fully broken deploy that passed CI. Fail the
// build instead. Scoped to Vercel production so local `npm run build` and
// preview builds keep working without the var.
if (process.env.VERCEL_ENV === "production" && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set. Production builds would fall back to " +
    "http://127.0.0.1:8000 and every API call would fail. Set it in the " +
    "Vercel project's environment variables (e.g. https://axon-crm-api.onrender.com)."
  );
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
