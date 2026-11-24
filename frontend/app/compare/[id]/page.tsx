import type { Metadata } from "next";

import { ComparisonView } from "@/components/compare/comparison-view";

export const metadata: Metadata = {
  title: "Comparison",
  // Personal, PIN-specific results: keep them out of search engines.
  robots: { index: false, follow: false },
};

export default async function ComparePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <ComparisonView id={id} />
    </div>
  );
}
