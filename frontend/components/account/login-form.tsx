"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";

export function LoginForm() {
  const { mode, signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    setState("busy");
    try {
      const result = await signIn(email.trim());
      if (result === "link_sent") setState("sent");
      else router.push("/history");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      setState("idle");
    }
  }

  if (state === "sent") {
    return (
      <div role="status" className="bg-card flex gap-3 rounded-2xl border p-5 text-sm">
        <Mail className="text-primary mt-0.5 size-4 shrink-0" aria-hidden />
        <p>
          Check <span className="font-medium">{email}</span> for a sign-in link. You can close this
          tab.
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      className="bg-card flex flex-col gap-4 rounded-2xl border p-5"
    >
      {mode === "dev" && (
        <div className="bg-warning-soft flex gap-2 rounded-lg p-3 text-xs">
          <FlaskConical className="text-warning size-4 shrink-0" aria-hidden />
          <p>
            <span className="font-semibold">Development sign-in.</span> No password: any email signs
            in. The server refuses this mode in production; connect Supabase for real accounts.
          </p>
        </div>
      )}
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "email-error" : undefined}
        />
        {error && (
          <p id="email-error" role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
      </div>
      <Button type="submit" disabled={state === "busy"}>
        {mode === "supabase" ? "Email me a sign-in link" : "Sign in"}
      </Button>
    </form>
  );
}
