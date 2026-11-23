"use client";

import { Check, ChevronDown, MapPin, Search, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { cn } from "@/lib/format";
import { useLogout, useMe, useSelectStore, useStores } from "@/lib/hooks";
import { useStoreId } from "@/lib/store";

const NAV = [
  { label: "Ask Gabriella", href: "/chat" },
  { label: "New in", href: "/shop?sort=newest" },
  { label: "Men", href: "/shop?gender=men&gender=unisex" },
  { label: "Women", href: "/shop?gender=women&gender=unisex" },
  { label: "Ethnic", href: "/shop?category=ethnic" },
  { label: "Footwear", href: "/shop?category=footwear" },
  { label: "Sale", href: "/shop?on_sale=true" },
];

function useClickOutside<T extends HTMLElement>(onOutside: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onOutside]);
  return ref;
}

function StorePicker() {
  const { data: stores } = useStores();
  const select = useSelectStore();
  const [open, setOpen] = useState(false);
  const current = useStoreId();
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));

  const store = stores?.find((s) => s.id === current);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="focus-ring flex items-center gap-1.5 text-xs text-muted hover:text-ink"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <MapPin className="size-3.5" />
        <span className="max-w-32 truncate">{store ? store.city : "Choose store"}</span>
        <ChevronDown className="size-3" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-3 w-72 border border-line bg-white p-2 shadow-xl" role="listbox">
          <p className="eyebrow px-3 pb-2 pt-1">Shop stock from</p>
          {[{ id: null, name: "All stores", city: "Show everything", is_online: false }, ...(stores ?? [])].map((s) => (
            <button
              key={s.id ?? "all"}
              role="option"
              aria-selected={current === s.id}
              onClick={() => {
                select.mutate(s.id);
                setOpen(false);
              }}
              className="focus-ring flex w-full items-center justify-between px-3 py-2 text-left hover:bg-sand"
            >
              <span>
                <span className="block text-sm">{s.id === null ? s.name : s.city}</span>
                <span className="block text-xs text-muted">{s.id === null ? s.city : s.name}</span>
              </span>
              {current === s.id && <Check className="size-4" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AccountMenu() {
  const { data: me, isLoading } = useMe();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));

  if (isLoading) return <span className="size-5" />;
  if (!me) {
    return (
      <Link href="/login" className="focus-ring flex items-center gap-1.5 text-xs font-medium hover:underline">
        <UserIcon className="size-4" /> Sign in
      </Link>
    );
  }
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} className="focus-ring flex items-center gap-1.5 text-xs font-medium">
        <span className="grid size-7 place-items-center rounded-full bg-ink text-[11px] text-ivory">
          {me.full_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden sm:inline">{me.full_name.split(" ")[0]}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-3 w-52 border border-line bg-white py-2 text-sm shadow-xl">
          <Link href="/account" onClick={() => setOpen(false)} className="block px-4 py-2 hover:bg-sand">
            Account & preferences
          </Link>
          <button onClick={() => logout.mutate()} className="block w-full px-4 py-2 text-left hover:bg-sand">
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function SearchBox({ className }: { className?: string }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    router.push(q.trim() ? `/shop?q=${encodeURIComponent(q.trim())}` : "/shop");
  };
  return (
    <form onSubmit={submit} className={cn("relative", className)} role="search">
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search linen shirts, beige chinos…"
        aria-label="Search the catalogue"
        className="focus-ring h-9 w-full rounded-full border border-line bg-white/70 pl-9 pr-4 text-xs placeholder:text-muted/70"
      />
    </form>
  );
}

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ivory/90 backdrop-blur">
      <div className="bg-ink px-4 py-2 text-center text-[11px] tracking-wide text-ivory/90">
        Simulated retailer for a portfolio demo · stock and prices are generated data
      </div>
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="focus-ring font-display text-3xl font-medium tracking-tight">
          Gabriella
        </Link>
        <nav className="hidden items-center gap-5 text-[13px] lg:flex" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.label} href={n.href} className={cn("focus-ring whitespace-nowrap hover:underline hover:underline-offset-4", n.label === "Sale" && "text-sale", n.label === "Ask Gabriella" && "font-semibold text-cognac")}>
              {n.label}
            </Link>
          ))}
        </nav>
        <SearchBox className="ml-auto hidden w-64 md:block" />
        <div className="ml-auto flex items-center gap-5 md:ml-0">
          <StorePicker />
          <AccountMenu />
        </div>
      </div>
      <div className="flex gap-4 overflow-x-auto px-4 pb-3 text-[13px] lg:hidden">
        {NAV.map((n) => (
          <Link key={n.label} href={n.href} className="shrink-0">
            {n.label}
          </Link>
        ))}
      </div>
      <div className="px-4 pb-3 md:hidden">
        <SearchBox />
      </div>
    </header>
  );
}
