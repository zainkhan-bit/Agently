import type { NextConfig } from "next";

// The browser only talks to the frontend origin; /api/* is proxied to the backend so
// session cookies stay first-party (ADR-0003). BACKEND_URL is server-side only.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
