"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/client-api";
import { useAuthSuccess } from "@/lib/hooks";
import type { User } from "@/lib/types";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const params = useSearchParams();
  const next = params.get("next")?.startsWith("/") ? params.get("next")! : "/";
  const onSuccess = useAuthSuccess();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const form = new FormData(e.currentTarget);
    try {
      const user = await api<User>(mode === "login" ? "/auth/login" : "/auth/register", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      onSuccess(user, next);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.code === "validation_error"
            ? "Check your details: a valid email and a password of at least 8 characters."
            : err.message
          : "Something went wrong. Please try again.",
      );
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {mode === "register" && <Input label="Full name" name="full_name" autoComplete="name" required maxLength={120} />}
      <Input label="Email" name="email" type="email" autoComplete="email" required />
      <Input
        label="Password"
        name="password"
        type="password"
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        minLength={8}
        required
      />
      {error && (
        <p role="alert" className="border border-sale/30 bg-sale/5 px-4 py-3 text-sm text-sale">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" size="lg" disabled={pending}>
        {pending ? "One moment…" : mode === "login" ? "Sign in" : "Create account"}
      </Button>
      <p className="text-center text-sm text-muted">
        {mode === "login" ? (
          <>New here? <Link href={`/signup?next=${encodeURIComponent(next)}`} className="text-ink underline underline-offset-4">Create an account</Link></>
        ) : (
          <>Already have an account? <Link href={`/login?next=${encodeURIComponent(next)}`} className="text-ink underline underline-offset-4">Sign in</Link></>
        )}
      </p>
    </form>
  );
}
