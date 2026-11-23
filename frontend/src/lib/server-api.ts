import { cookies } from "next/headers";
import { connection } from "next/server";

import { STORE_COOKIE } from "@/lib/constants";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8010";

export type Query = Record<string, string | string[] | number | boolean | null | undefined>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** GET from FastAPI during a request. Never runs at build time. */
export async function apiGet<T>(path: string, query: Query = {}): Promise<T> {
  await connection();
  const url = new URL(`/api${path}`, API_INTERNAL_URL);
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    for (const v of Array.isArray(value) ? value : [value]) url.searchParams.append(key, String(v));
  }
  const res = await fetch(url, { cache: "no-store", headers: { accept: "application/json" } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.error?.message ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

/** The shopper's selected store, from the cookie set by the store picker. */
export async function selectedStoreId(): Promise<number | undefined> {
  const raw = (await cookies()).get(STORE_COOKIE)?.value;
  const id = raw ? Number(raw) : NaN;
  return Number.isInteger(id) && id > 0 ? id : undefined;
}
