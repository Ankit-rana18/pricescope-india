import type { Metadata } from "next";

import { AlertsView } from "@/components/account/account-views";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Price alerts", ...PRIVATE_PAGE };

export default function Page() {
  return (
    <PageShell title="Price alerts">
      <AlertsView />
    </PageShell>
  );
}
