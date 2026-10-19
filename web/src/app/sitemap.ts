import type { MetadataRoute } from "next";
import { DOCS_NAV, SITE } from "./docs/nav";

export default function sitemap(): MetadataRoute.Sitemap {
  const docs = DOCS_NAV.flatMap((g) => g.items.map(([href]) => href));
  return [
    { url: SITE, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE}/signup`, changeFrequency: "monthly" },
    ...docs.map((href) => ({ url: `${SITE}${href}`, changeFrequency: "monthly" as const })),
  ];
}
