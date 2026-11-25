import type { MetadataRoute } from "next";

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");

export default function robots(): MetadataRoute.Robots {
  return {
    // Comparisons are personal, PIN-specific results; they are also marked noindex.
    rules: [{ userAgent: "*", allow: "/", disallow: ["/compare/"] }],
    sitemap: `${SITE}/sitemap.xml`,
  };
}
