import { CircleAlert, CircleCheck, CircleSlash } from "lucide-react";

import type { ReadinessResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

/** Live backend readiness, as reported by GET /api/v1/health/ready. */
export function ApiStatus({ readiness }: { readiness: ReadinessResponse | null }) {
  if (!readiness) {
    return (
      <Badge tone="danger">
        <CircleSlash aria-hidden /> API unreachable
      </Badge>
    );
  }
  if (readiness.checks.storage === "not_configured") {
    return (
      <Badge tone="warning">
        <CircleAlert aria-hidden /> Storage not configured
      </Badge>
    );
  }
  if (readiness.status !== "ok") {
    return (
      <Badge tone="warning">
        <CircleAlert aria-hidden /> API degraded
      </Badge>
    );
  }
  return (
    <Badge tone="success">
      <CircleCheck aria-hidden /> API online
    </Badge>
  );
}
