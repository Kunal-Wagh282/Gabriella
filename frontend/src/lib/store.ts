import { useSyncExternalStore } from "react";

import { STORE_COOKIE } from "@/lib/constants";

export { STORE_COOKIE };

const listeners = new Set<() => void>();

export function readStoreCookie(): number | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${STORE_COOKIE}=(\\d+)`));
  return match ? Number(match[1]) : null;
}

export function writeStoreCookie(storeId: number | null): void {
  const maxAge = storeId === null ? 0 : 60 * 60 * 24 * 365;
  document.cookie = `${STORE_COOKIE}=${storeId ?? ""}; path=/; max-age=${maxAge}; samesite=lax`;
  listeners.forEach((notify) => notify());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The selected store ID, kept in sync across components that read or change it. */
export function useStoreId(): number | null {
  return useSyncExternalStore(subscribe, readStoreCookie, () => null);
}
