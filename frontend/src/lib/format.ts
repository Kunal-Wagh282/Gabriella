import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export function formatINR(amount: number): string {
  return inr.format(amount);
}

export function discountPercent(price: number, mrp: number): number {
  return mrp > price ? Math.round(((mrp - price) / mrp) * 100) : 0;
}

export function titleCase(value: string): string {
  return value.replace(/(^|[\s-])\w/g, (m) => m.toUpperCase());
}

export function stockLabel(onHand: number | null | undefined): {
  label: string;
  tone: "ok" | "low" | "none";
} {
  if (!onHand) return { label: "Sold out", tone: "none" };
  if (onHand <= 3) return { label: `Only ${onHand} left`, tone: "low" };
  return { label: "In stock", tone: "ok" };
}
