import type { MetadataRoute } from "next";
import { SITE } from "./docs/nav";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: SITE, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE}/signup`, changeFrequency: "monthly" },
    { url: `${SITE}/terms`, changeFrequency: "yearly" },
    { url: `${SITE}/privacy`, changeFrequency: "yearly" },
    // The other docs pages live in railhq-content and are listed in /blog/sitemap.xml.
    { url: `${SITE}/docs/plans`, changeFrequency: "monthly" },
  ];
}
