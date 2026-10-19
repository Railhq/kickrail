import type { NextConfig } from "next";

// The blog is its own app (Railhq/kickrail-content) on the content droplet, built
// with basePath /blog. Read at build time, so changing it needs a rebuild.
const BLOG_ORIGIN = process.env.BLOG_ORIGIN ?? "http://159.203.71.192:3002";

const nextConfig: NextConfig = {
  // Self-contained server for the Docker image.
  output: "standalone",
  async rewrites() {
    return [
      { source: "/blog", destination: `${BLOG_ORIGIN}/blog` },
      { source: "/blog/:path*", destination: `${BLOG_ORIGIN}/blog/:path*` },
    ];
  },
};

export default nextConfig;
