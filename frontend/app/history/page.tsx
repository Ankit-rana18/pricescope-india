import type { Metadata } from "next";

import { HistoryView } from "@/components/account/account-views";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "History", ...PRIVATE_PAGE };

export default function Page() {
  return (
    <PageShell title="History">
      <HistoryView />
    </PageShell>
  );
}
