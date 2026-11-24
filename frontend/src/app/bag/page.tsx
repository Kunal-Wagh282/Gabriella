"use client";

import { Loader2, Minus, Plus, ShieldCheck, Trash2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button, Skeleton } from "@/components/ui";
import { errorMessage, useCart, useCheckout, useUpdateLine } from "@/lib/commerce";
import { cn, formatINR } from "@/lib/format";
import { useMe } from "@/lib/hooks";

export default function BagPage() {
  const router = useRouter();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: cart, isLoading } = useCart();
  const update = useUpdateLine();
  const checkout = useCheckout();

  if (meLoading || (me && isLoading)) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-16">
        <Skeleton className="h-12 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (!me) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="font-display text-4xl">Your bag</h1>
        <p className="mt-3 text-sm text-muted">Sign in to see your bag and check out.</p>
        <Link href="/login?next=/bag" className="mt-8 inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">Sign in</Link>
      </div>
    );
  }
  if (!cart?.items.length) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="font-display text-4xl">Your bag is empty</h1>
        <p className="mt-3 text-sm text-muted">Ask Gabriella for a look, or browse the collection.</p>
        <div className="mt-8 flex justify-center gap-3">
          <Link href="/chat" className="inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">Chat with Gabriella</Link>
          <Link href="/shop" className="inline-flex h-11 items-center border border-ink px-6 text-sm">Shop</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <p className="eyebrow">{cart.item_count} {cart.item_count === 1 ? "piece" : "pieces"}</p>
      <h1 className="mt-1 font-display text-5xl">Your bag</h1>
      <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_320px]">
        <ul className="divide-y divide-line border-y border-line">
          {cart.items.map((line) => (
            <li key={line.id} className="flex gap-4 py-5">
              <Link href={`/product/${line.product.slug}`} className="w-24 shrink-0 bg-sand">
                {line.product.image && (
                  <Image src={line.product.image.url} alt={line.product.image.alt} width={192} height={240} className="h-full w-full object-cover" />
                )}
              </Link>
              <div className="flex min-w-0 flex-1 flex-col">
                <p className="eyebrow">{line.product.brand}</p>
                <Link href={`/product/${line.product.slug}`} className="text-sm hover:underline">{line.product.name}</Link>
                <p className="mt-1 text-xs text-muted">
                  {line.product.colour} · Size {line.size} · from {line.store_city}
                </p>
                {line.issue && <p className="mt-1 text-xs font-medium text-sale">{line.issue}</p>}
                <div className="mt-auto flex items-center justify-between pt-3">
                  <div className="flex items-center border border-line">
                    <button
                      aria-label="One fewer"
                      disabled={update.isPending}
                      onClick={() => update.mutate({ id: line.id, quantity: line.quantity > 1 ? line.quantity - 1 : null })}
                      className="focus-ring grid size-8 place-items-center hover:bg-sand"
                    >
                      {line.quantity > 1 ? <Minus className="size-3" /> : <Trash2 className="size-3" />}
                    </button>
                    <span className="w-8 text-center text-sm tabular-nums">{line.quantity}</span>
                    <button
                      aria-label="One more"
                      disabled={update.isPending || line.quantity >= Math.min(10, line.available)}
                      onClick={() => update.mutate({ id: line.id, quantity: line.quantity + 1 })}
                      className="focus-ring grid size-8 place-items-center hover:bg-sand disabled:opacity-30"
                    >
                      <Plus className="size-3" />
                    </button>
                  </div>
                  <span className="text-sm font-semibold tabular-nums">{formatINR(line.line_total)}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>

        <aside className="h-fit border border-line bg-white p-6 lg:sticky lg:top-28">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-muted">Subtotal</dt><dd className="tabular-nums">{formatINR(cart.subtotal)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">Delivery / pickup</dt><dd>Free</dd></div>
            <div className="flex justify-between border-t border-line pt-3 text-base font-semibold"><dt>Total</dt><dd className="tabular-nums">{formatINR(cart.subtotal)}</dd></div>
          </dl>
          <Button
            size="lg"
            className="mt-6 w-full"
            disabled={!cart.can_checkout || checkout.isPending}
            onClick={() => checkout.mutate(undefined, { onSuccess: (order) => router.push(`/orders/${order.id}?placed=1`) })}
          >
            {checkout.isPending && <Loader2 className="size-4 animate-spin" />}
            Place order (simulated)
          </Button>
          {checkout.isError && <p role="alert" className="mt-3 text-xs text-sale">{errorMessage(checkout.error)}</p>}
          {!cart.can_checkout && <p className="mt-3 text-xs text-sale">Remove or adjust items that are no longer available.</p>}
          <p className={cn("mt-4 flex gap-2 text-[11px] leading-relaxed text-muted")}>
            <ShieldCheck className="size-4 shrink-0" />
            Demo checkout: no payment is taken. Stock is re-checked and decremented exactly once at checkout, even if two shoppers buy the last piece at the same moment.
          </p>
        </aside>
      </div>
    </div>
  );
}
