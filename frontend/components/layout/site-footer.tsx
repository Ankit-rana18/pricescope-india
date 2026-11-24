import type { ReadinessResponse } from "@/lib/api";
import { ApiStatus } from "@/components/layout/api-status";

export function SiteFooter({ readiness }: { readiness: ReadinessResponse | null }) {
  return (
    <footer className="border-t">
      <div className="text-muted-foreground mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p>
          © {new Date().getFullYear()} PriceScope India. Prices are shown only where verified data
          is available.
        </p>
        <ApiStatus readiness={readiness} />
      </div>
    </footer>
  );
}
