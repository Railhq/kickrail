import type { NextConfig } from "next";

// The blog and most of the docs live in Railhq/railhq-content, one container on
// the content droplet that serves every Railhq app under /<app>/... Its scripts
// and styles are reached through /_railhq-content so they never collide with
// this app's own /_next files. Read at build time, so changing it needs a rebuild.
const CONTENT_ORIGIN = process.env.CONTENT_ORIGIN ?? "http://159.203.71.192:3004";

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
  // These run after this app's own pages, so a docs page that still lives here
  // (docs/plans, rendered from the billing code) wins over the proxy.
  async rewrites() {
    return [
      // The Tina editor for every Railhq app's content.
      { source: "/blog/admin", destination: `${CONTENT_ORIGIN}/admin/index.html` },
      { source: "/blog/admin/:path*", destination: `${CONTENT_ORIGIN}/admin/:path*` },
      { source: "/blog", destination: `${CONTENT_ORIGIN}/kickrail/blog` },
      { source: "/blog/:path*", destination: `${CONTENT_ORIGIN}/kickrail/blog/:path*` },
      { source: "/docs", destination: `${CONTENT_ORIGIN}/kickrail/docs` },
      { source: "/docs/:path*", destination: `${CONTENT_ORIGIN}/kickrail/docs/:path*` },
      { source: "/_railhq-content/:path*", destination: `${CONTENT_ORIGIN}/:path*` },
    ];
  },
};

export default nextConfig;
