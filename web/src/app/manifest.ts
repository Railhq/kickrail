import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Kickrail",
    short_name: "Kickrail",
    description: "Affiliate tracking for Stripe",
    start_url: "/home",
    display: "standalone",
    background_color: "#14140f",
    theme_color: "#14140f",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
