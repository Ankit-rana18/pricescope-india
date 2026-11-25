import type { Metadata } from "next";

import { LoginForm } from "@/components/account/login-form";
import { PageShell, PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Sign in", ...PRIVATE_PAGE };

export default function LoginPage() {
  return (
    <PageShell title="Sign in">
      <div className="max-w-md">
        <LoginForm />
      </div>
    </PageShell>
  );
}
