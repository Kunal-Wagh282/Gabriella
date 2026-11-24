"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { use } from "react";

import { Skeleton } from "@/components/ui";
import { api } from "@/lib/client-api";
import type { Order } from "@/lib/commerce";
import { formatINR } from "@/lib/format";

export function OrderView({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = use(params);
  const placed = use(searchParams).placed === "1";
  const { data: order, isLoading, isError } = useQuery({ queryKey: ["order", id], queryFn: () => api<Order>(`/orders/${id}`) });

  if (isLoading) return <div className="mx-auto max-w-3xl px-4 py-16"><Skeleton className="h-60 w-full" /></div>;
  if (isError || !order) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="font-display text-4xl">Order not found</h1>
        <Link href="/orders" className="mt-6 inline-block text-sm underline">Your orders</Link>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      {placed && (
        <div className="mb-8 flex items-start gap-3 border border-ok/30 bg-ok/5 p-4 text-sm">
          <CheckCircle2 className="size-5 shrink-0 text-ok" />
          <div>
            <p className="font-semibold">Order placed</p>
            <p className="text-muted">Stock has been updated. Next time, Gabriella will take this purchase into account.</p>
          </div>
        </div>
      )}
      <p className="font-mono text-xs text-muted">{order.number}</p>
      <h1 className="mt-1 font-display text-5xl">Your order</h1>
      <ul className="mt-8 divide-y divide-line border-y border-line">
        {order.items.map((i, n) => (
          <li key={n} className="flex gap-4 py-4">
            <div className="w-20 shrink-0 bg-sand">
              {i.image_url && <Image src={i.image_url} alt="" width={160} height={200} className="h-full w-full object-cover" />}
            </div>
            <div className="flex-1 text-sm">
              {i.product_slug ? <Link href={`/product/${i.product_slug}`} className="hover:underline">{i.product_name}</Link> : i.product_name}
              <p className="mt-1 text-xs text-muted">{i.colour} · Size {i.size} · {i.store_city} · Qty {i.quantity}</p>
            </div>
            <span className="text-sm tabular-nums">{formatINR(i.unit_price * i.quantity)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-right text-base font-semibold tabular-nums">Total {formatINR(order.subtotal)}</p>
      <div className="mt-10 flex gap-3">
        <Link href="/chat" className="inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">Ask Gabriella what goes with it</Link>
        <Link href="/orders" className="inline-flex h-11 items-center border border-ink px-6 text-sm">All orders</Link>
      </div>
    </div>
  );
}
