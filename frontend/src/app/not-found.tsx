import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md px-4 py-28 text-center">
      <p className="eyebrow">404</p>
      <h1 className="mt-2 font-display text-5xl">Not on our shelves</h1>
      <p className="mt-3 text-sm text-muted">This page or product doesn&apos;t exist, or it&apos;s been discontinued.</p>
      <Link href="/shop" className="mt-8 inline-flex h-11 items-center bg-ink px-6 text-sm text-ivory">
        Browse the collection
      </Link>
    </div>
  );
}
