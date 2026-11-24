"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";

import { api, ApiError } from "@/lib/client-api";
import { useMe } from "@/lib/hooks";
import type { ProductSummary } from "@/lib/types";

export interface CartLine {
  id: number;
  product: ProductSummary;
  variant_id: number;
  size: string;
  store_id: number;
  store_city: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  available: number;
  issue: string | null;
}

export interface Cart {
  items: CartLine[];
  item_count: number;
  subtotal: number;
  can_checkout: boolean;
}

export interface OrderLine {
  product_id: number;
  product_slug: string | null;
  image_url: string | null;
  product_name: string;
  size: string;
  colour: string;
  store_city: string;
  quantity: number;
  unit_price: number;
}

export interface Order {
  id: string;
  number: string;
  status: string;
  subtotal: number;
  item_count: number;
  created_at: string;
  items: OrderLine[];
}

export interface AddItem {
  variant_id: number;
  store_id?: number | null;
  quantity?: number;
  source?: "product" | "chat";
}

export function useCart() {
  const { data: me } = useMe();
  return useQuery({ queryKey: ["cart"], queryFn: () => api<Cart>("/cart"), enabled: Boolean(me) });
}

/** Adds items to the bag; sends signed-out shoppers to sign in and back. */
export function useAddToCart() {
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me } = useMe();
  return useMutation({
    mutationFn: async (items: AddItem[]) => {
      if (!me) {
        router.push(`/login?next=${encodeURIComponent(pathname)}`);
        throw new ApiError(401, "unauthorized", "Please sign in to use your bag");
      }
      return items.length === 1
        ? api<Cart>("/cart/items", { method: "POST", body: JSON.stringify(items[0]) })
        : api<Cart>("/cart/items/bulk", { method: "POST", body: JSON.stringify({ items }) });
    },
    onSuccess: (cart) => qc.setQueryData(["cart"], cart),
  });
}

export function useUpdateLine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, quantity }: { id: number; quantity: number | null }) =>
      quantity === null
        ? api<Cart>(`/cart/items/${id}`, { method: "DELETE" })
        : api<Cart>(`/cart/items/${id}`, { method: "PATCH", body: JSON.stringify({ quantity }) }),
    onSuccess: (cart) => qc.setQueryData(["cart"], cart),
  });
}

export function useCheckout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Order>("/checkout", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cart"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
    },
  });
}

export function useOrders() {
  const { data: me } = useMe();
  return useQuery({ queryKey: ["orders"], queryFn: () => api<Order[]>("/orders"), enabled: Boolean(me) });
}

export function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
}
