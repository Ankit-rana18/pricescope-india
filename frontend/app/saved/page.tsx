import type { Metadata } from "next";

import { SavedView } from "@/components/account/account-views";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Saved products", ...PRIVATE_PAGE };

export default function Page() {
  return (
    <PageShell title="Saved products">
      <SavedView />
    </PageShell>
  );
}
