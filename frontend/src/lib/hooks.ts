"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { api, ApiError } from "@/lib/client-api";
import { readStoreCookie, writeStoreCookie } from "@/lib/store";
import type { Preferences, Store, User } from "@/lib/types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<User>("/auth/me");
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
  });
}

export function useStores() {
  return useQuery({ queryKey: ["stores"], queryFn: () => api<Store[]>("/stores"), staleTime: Infinity });
}

/** Store choice lives in a cookie (so server pages can filter by it) and, when signed in, in preferences. */
export function useSelectStore() {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();
  return useMutation({
    mutationFn: async (storeId: number | null) => {
      writeStoreCookie(storeId);
      if (me) {
        await api<Preferences>("/me/preferences", {
          method: "PATCH",
          body: JSON.stringify({ preferred_store_id: storeId }),
        });
      }
      return storeId;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      router.refresh();
    },
  });
}

export function useAuthSuccess() {
  const qc = useQueryClient();
  const router = useRouter();
  return (user: User, next = "/") => {
    qc.setQueryData(["me"], user);
    // Adopt the account's saved store if this browser hasn't picked one.
    if (readStoreCookie() === null && user.preferences.preferred_store_id) {
      writeStoreCookie(user.preferences.preferred_store_id);
    }
    router.push(next);
    router.refresh();
  };
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.setQueryData(["me"], null);
      router.push("/");
      router.refresh();
    },
  });
}
