import type { Metadata } from "next";

import { AuthCallback } from "@/components/account/auth-callback";
import { PRIVATE_PAGE } from "@/components/account/require-sign-in";

export const metadata: Metadata = { title: "Signing in", ...PRIVATE_PAGE };

export default function CallbackPage() {
  return <AuthCallback />;
}
