"use client";

import Link from "next/link";

import { Skeleton } from "@/components/ui";
import { useOrders } from "@/lib/commerce";
import { formatINR } from "@/lib/format";
import { useMe } from "@/lib/hooks";

export default function OrdersPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const { data: orders, isLoading } = useOrders();

  if (meLoading || (me && isLoading)) {
    return <div className="mx-auto max-w-3xl px-4 py-16"><Skeleton className="h-40 w-full" /></div>;
  }
  if (!me) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="font-display text-4xl">Your orders</h1>
        <Link href="/login?next=/orders" className="mt-8 inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">Sign in</Link>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-5xl">Your orders</h1>
      <p className="mt-2 text-sm text-muted">
        Gabriella learns your sizes, colours and price range from these when personalisation is on.
      </p>
      {!orders?.length ? (
        <p className="mt-10 text-sm text-muted">No orders yet.</p>
      ) : (
        <ul className="mt-10 divide-y divide-line border-y border-line">
          {orders.map((o) => (
            <li key={o.id}>
              <Link href={`/orders/${o.id}`} className="flex items-center justify-between gap-4 py-5 hover:bg-sand/50">
                <div>
                  <p className="font-mono text-xs">{o.number}</p>
                  <p className="mt-1 text-sm">{o.items.map((i) => i.product_name).slice(0, 3).join(", ")}{o.items.length > 3 ? "…" : ""}</p>
                  <p className="mt-1 text-xs text-muted">
                    {new Date(o.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} · {o.status}
                  </p>
                </div>
                <span className="text-sm font-semibold tabular-nums">{formatINR(o.subtotal)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
