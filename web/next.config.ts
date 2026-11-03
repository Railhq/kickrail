import type { NextConfig } from "next";

// The blog is its own app (Railhq/kickrail-content) on the content droplet, built
// with basePath /blog. Read at build time, so changing it needs a rebuild.
const BLOG_ORIGIN = process.env.BLOG_ORIGIN ?? "http://159.203.71.192:3002";

const nextConfig: NextConfig = {
  // Self-contained server for the Docker image.
  output: "standalone",
  // Baseline security headers for every page (no framing; kr.js is a script, not an iframe).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=31536000" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Content-Security-Policy", value: "base-uri 'self'; object-src 'none'; frame-ancestors 'self'" },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      { source: "/blog", destination: `${BLOG_ORIGIN}/blog` },
      { source: "/blog/:path*", destination: `${BLOG_ORIGIN}/blog/:path*` },
    ];
  },
};

export default nextConfig;
