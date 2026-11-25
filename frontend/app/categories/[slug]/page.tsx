import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { getCategoryProducts, type CategoryProductsView } from "@/lib/products";

async function load(slug: string, cursor?: string): Promise<CategoryProductsView> {
  try {
    return await getCategoryProducts(slug, cursor);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const { category } = await load(slug);
  return {
    title: category.name,
    description: `Exact-variant price comparisons for ${category.name} products across Indian marketplaces.`,
    alternates: { canonical: `/categories/${category.slug}` },
    robots: category.indexable ? undefined : { index: false, follow: false },
  };
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ cursor?: string }>;
}) {
  const { slug } = await params;
  const { cursor } = await searchParams;
  const data = await load(slug, cursor && /^\d{1,6}$/.test(cursor) ? cursor : undefined);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      <nav aria-label="Breadcrumb" className="text-muted-foreground text-sm">
        <Link href="/" className="hover:text-foreground">
          Home
        </Link>
        {" / "}
        {data.category.name}
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{data.category.name}</h1>
      <ul className="grid gap-3 sm:grid-cols-2">
        {data.products.map((p) => (
          <li key={p.slug}>
            <Link
              href={`/products/${p.slug}`}
              className="focus-visible:ring-ring/40 block rounded-2xl outline-none focus-visible:ring-[3px]"
            >
              <Card className="hover:bg-muted/40 h-full transition-colors">
                <CardContent className="flex flex-col gap-1">
                  {p.brand && <span className="text-muted-foreground text-xs">{p.brand}</span>}
                  <span className="font-medium">{p.title}</span>
                  {!p.indexable && <span className="text-warning text-xs">Demo data</span>}
                </CardContent>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
      {data.next_cursor && (
        <Link
          href={`/categories/${data.category.slug}?cursor=${data.next_cursor}`}
          className="text-primary w-fit text-sm font-medium hover:underline"
        >
          More products
        </Link>
      )}
    </div>
  );
}
