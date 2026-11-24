import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Loader2,
  PlugZap,
  SearchX,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { LocationVerification, MatchClass, ResultState } from "@/lib/comparison";

export function MatchBadge({ match }: { match: MatchClass | null }) {
  if (!match) return null;
  const config = {
    EXACT: { tone: "success", icon: CheckCircle2, label: "Exact match" },
    PROBABLE: { tone: "info", icon: CircleHelp, label: "Probable match" },
    UNVERIFIED: { tone: "neutral", icon: CircleDashed, label: "Unverified match" },
    MISMATCH: { tone: "danger", icon: XCircle, label: "Different variant" },
  } as const;
  const { tone, icon: Icon, label } = config[match];
  return (
    <Badge tone={tone}>
      <Icon aria-hidden /> {label}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: ResultState }) {
  const config = {
    PENDING: { tone: "neutral", icon: Loader2, label: "Checking…", spin: true },
    OK: null,
    NOT_FOUND: { tone: "neutral", icon: SearchX, label: "Not sold here", spin: false },
    FAILED: { tone: "danger", icon: AlertTriangle, label: "Check failed", spin: false },
    UNSUPPORTED: { tone: "neutral", icon: Ban, label: "No data access", spin: false },
    NOT_CONFIGURED: { tone: "warning", icon: PlugZap, label: "Not connected", spin: false },
  } as const;
  const c = config[status];
  if (!c) return null;
  const Icon = c.icon;
  return (
    <Badge tone={c.tone}>
      <Icon className={c.spin ? "animate-spin" : undefined} aria-hidden /> {c.label}
    </Badge>
  );
}

export const LOCATION_TEXT: Record<LocationVerification, string> = {
  VERIFIED: "Delivers to your PIN code",
  UNVERIFIABLE: "Delivery to your PIN can't be verified",
  UNAVAILABLE: "Doesn't deliver to your PIN code",
  NEEDS_PRECISE_LOCATION: "Needs a precise address to check delivery",
};
