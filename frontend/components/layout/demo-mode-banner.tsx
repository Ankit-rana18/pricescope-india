import { FlaskConical } from "lucide-react";

/** Persistent notice whenever the backend runs on mock adapters. */
export function DemoModeBanner() {
  return (
    <div role="status" className="border-warning/20 bg-warning-soft border-b text-sm">
      <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 sm:px-6">
        <FlaskConical className="text-warning size-4 shrink-0" aria-hidden />
        <p>
          <span className="font-semibold">Demo mode.</span>{" "}
          <span className="text-muted-foreground">
            Prices, stock and delivery shown here are sample data, not real marketplace prices.
          </span>
        </p>
      </div>
    </div>
  );
}
