import type { MetadataRoute } from "next";
import { SITE } from "./docs/nav";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/dashboard", "/onboarding", "/home", "/a/", "/api/", "/claim"] },
    // The blog and docs are served by railhq-content, which has its own sitemap.
    sitemap: [`${SITE}/sitemap.xml`, `${SITE}/blog/sitemap.xml`],
  };
}
