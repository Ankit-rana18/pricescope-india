import Link from "next/link";
import { ScanSearch } from "lucide-react";

import { UserMenu } from "@/components/layout/user-menu";

export function SiteHeader() {
  return (
    <header className="bg-background/85 supports-[backdrop-filter]:bg-background/70 sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link
          href="/"
          className="focus-visible:ring-ring/40 flex items-center gap-2 rounded-md font-semibold tracking-tight outline-none focus-visible:ring-[3px]"
        >
          <span className="bg-primary text-primary-foreground grid size-8 place-items-center rounded-lg">
            <ScanSearch className="size-4" aria-hidden />
          </span>
          <span>
            PriceScope <span className="text-muted-foreground font-medium">India</span>
          </span>
        </Link>
        <UserMenu />
      </div>
    </header>
  );
}
