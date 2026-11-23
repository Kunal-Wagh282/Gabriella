"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SORTS } from "@/lib/search-params";

export function SortSelect() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      Sort
      <select
        className="focus-ring h-9 border border-line bg-white px-2 text-xs text-ink"
        value={params.get("sort") ?? (params.get("q") ? "relevance" : "featured")}
        onChange={(e) => {
          const next = new URLSearchParams(params);
          next.set("sort", e.target.value);
          next.delete("page");
          router.push(`${pathname}?${next.toString()}`, { scroll: false });
        }}
      >
        {SORTS.filter((s) => s.value !== "relevance" || params.get("q")).map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}
