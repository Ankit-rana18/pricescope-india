import type { Metadata } from "next";

import { AccountView } from "@/components/account/account-views";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Account & cards", ...PRIVATE_PAGE };

export default function Page() {
  return (
    <PageShell title="Account & cards">
      <AccountView />
    </PageShell>
  );
}
