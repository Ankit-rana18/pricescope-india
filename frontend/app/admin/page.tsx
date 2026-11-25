import type { Metadata } from "next";

import { AdminDashboard } from "@/components/account/admin-dashboard";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Admin dashboard", ...PRIVATE_PAGE };

export default function Page() {
  return (
    <PageShell title="Admin dashboard">
      <AdminDashboard />
    </PageShell>
  );
}
