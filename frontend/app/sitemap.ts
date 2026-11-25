import type { MetadataRoute } from "next";

import { getSitemapEntries } from "@/lib/products";

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");

/** Only pages the API marks indexable (never demo data). Falls back to the homepage. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  try {
    const { entries } = await getSitemapEntries();
    return entries.map((e) => ({
      url: `${SITE}${e.path}`,
      lastModified: e.lastmod ? new Date(e.lastmod) : undefined,
    }));
  } catch {
    return [{ url: `${SITE}/` }];
  }
}
