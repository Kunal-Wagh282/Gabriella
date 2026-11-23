import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Create an account" };

export default function SignupPage() {
  return (
    <div className="mx-auto max-w-md px-4 py-16 sm:py-24">
      <p className="eyebrow">Join Gabriella</p>
      <h1 className="mt-2 font-display text-5xl">Create an account</h1>
      <p className="mt-3 text-sm text-muted">
        Personalised suggestions are optional. You can switch them off at any time from your account.
      </p>
      <div className="mt-10">
        <Suspense>
          <AuthForm mode="register" />
        </Suspense>
      </div>
    </div>
  );
}
