import type { NextConfig } from "next";

// Where the Next server reaches FastAPI. The browser never calls it directly: /api and
// /media are proxied so auth cookies stay first-party.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  output: "standalone",
  // Product images are pre-sized WebP renders; no need for the optimiser.
  images: { unoptimized: true },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_INTERNAL_URL}/api/:path*` },
      { source: "/media/:path*", destination: `${API_INTERNAL_URL}/media/:path*` },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
