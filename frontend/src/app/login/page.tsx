import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md px-4 py-16 sm:py-24">
      <p className="eyebrow">Welcome back</p>
      <h1 className="mt-2 font-display text-5xl">Sign in</h1>
      <p className="mt-3 text-sm text-muted">
        Signing in lets Gabriella remember your store, sizes and — if you allow it — your past purchases.
      </p>
      <div className="mt-10">
        <Suspense>
          <AuthForm mode="login" />
        </Suspense>
      </div>
      <p className="mt-10 border-t border-line pt-6 text-xs text-muted">
        Exploring the demo? Use the seeded account from the README (<span className="font-mono">demo@gabriella.example</span>).
      </p>
    </div>
  );
}
