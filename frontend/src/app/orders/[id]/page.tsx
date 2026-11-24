import { Suspense } from "react";

import { OrderView } from "@/components/order-view";
import { Skeleton } from "@/components/ui";

export default function OrderPage({ params, searchParams }: PageProps<"/orders/[id]">) {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-4 py-16"><Skeleton className="h-60 w-full" /></div>}>
      <OrderView params={params} searchParams={searchParams} />
    </Suspense>
  );
}
