"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { Button, Skeleton } from "@/components/ui";
import { api } from "@/lib/client-api";
import { cn } from "@/lib/format";
import { useLogout, useMe, useSelectStore, useStores } from "@/lib/hooks";
import type { Preferences } from "@/lib/types";

export default function AccountPage() {
  const { data: me, isLoading } = useMe();
  const { data: stores } = useStores();
  const selectStore = useSelectStore();
  const logout = useLogout();
  const qc = useQueryClient();
  const togglePersonalization = useMutation({
    mutationFn: (enabled: boolean) =>
      api<Preferences>("/me/preferences", {
        method: "PATCH",
        body: JSON.stringify({ personalization_enabled: enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });

  if (isLoading) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 px-4 py-16">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (!me) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="font-display text-4xl">Your account</h1>
        <p className="mt-3 text-sm text-muted">Sign in to manage your store and personalisation settings.</p>
        <Link href="/login?next=/account" className="mt-8 inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">
          Sign in
        </Link>
      </div>
    );
  }

  const personalised = me.preferences.personalization_enabled;
  return (
    <div className="mx-auto max-w-2xl px-4 py-16">
      <p className="eyebrow">Account</p>
      <h1 className="mt-2 font-display text-5xl">Hello, {me.full_name.split(" ")[0]}</h1>
      <p className="mt-2 text-sm text-muted">{me.email}</p>

      <section className="mt-12 border-t border-line pt-8">
        <h2 className="text-base font-semibold">Your store</h2>
        <p className="mt-1 text-sm text-muted">Gabriella checks stock here first and suggests online stock when your size is out.</p>
        <select
          className="focus-ring mt-4 h-12 w-full border border-line bg-white px-3 text-sm"
          value={me.preferences.preferred_store_id ?? ""}
          onChange={(e) => selectStore.mutate(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">No preference (all stores)</option>
          {stores?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.city} — {s.name}
            </option>
          ))}
        </select>
      </section>

      <section className="mt-10 border-t border-line pt-8">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h2 className="text-base font-semibold">Personalised recommendations</h2>
            <p className="mt-1 max-w-md text-sm text-muted">
              When on, Gabriella uses a compact summary of your purchases — favourite colours, usual sizes, price
              range — never your full order history. You can also say “start fresh” in any chat.
            </p>
          </div>
          <button
            role="switch"
            aria-checked={personalised}
            onClick={() => togglePersonalization.mutate(!personalised)}
            disabled={togglePersonalization.isPending}
            className={cn("focus-ring relative h-7 w-12 shrink-0 rounded-full transition-colors", personalised ? "bg-ink" : "bg-stone")}
          >
            <span className={cn("absolute top-1 size-5 rounded-full bg-white shadow transition-all", personalised ? "left-6" : "left-1")} />
            <span className="sr-only">Personalised recommendations</span>
          </button>
        </div>
      </section>

      <div className="mt-12 border-t border-line pt-8">
        <Button variant="secondary" onClick={() => logout.mutate()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
