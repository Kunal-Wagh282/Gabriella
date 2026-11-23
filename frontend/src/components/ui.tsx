import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";

import { cn, discountPercent, formatINR } from "@/lib/format";

type ButtonVariant = "primary" | "secondary" | "ghost";

const buttonStyles: Record<ButtonVariant, string> = {
  primary: "bg-ink text-ivory hover:bg-ink/85 disabled:bg-ink/40",
  secondary: "border border-ink text-ink hover:bg-ink hover:text-ivory disabled:border-ink/30 disabled:text-ink/40 disabled:hover:bg-transparent",
  ghost: "text-ink hover:bg-sand",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" | "lg" }
>(function Button({ className, variant = "primary", size = "md", ...props }, ref) {
  return (
    <button
      ref={ref}
      className={cn(
        "focus-ring inline-flex items-center justify-center gap-2 font-medium tracking-wide transition-colors disabled:cursor-not-allowed",
        size === "sm" && "h-9 px-4 text-xs",
        size === "md" && "h-11 px-6 text-sm",
        size === "lg" && "h-13 px-8 text-sm",
        buttonStyles[variant],
        className,
      )}
      {...props}
    />
  );
});

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }>(
  function Input({ label, error, className, id, ...props }, ref) {
    const inputId = id ?? props.name;
    return (
      <label htmlFor={inputId} className="block">
        <span className="eyebrow">{label}</span>
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "focus-ring mt-2 block h-12 w-full border border-line bg-white px-4 text-sm placeholder:text-muted/60",
            error && "border-sale",
            className,
          )}
          aria-invalid={error ? true : undefined}
          {...props}
        />
        {error && <span className="mt-1 block text-xs text-sale">{error}</span>}
      </label>
    );
  },
);

export function Price({ price, mrp, className }: { price: number; mrp: number; className?: string }) {
  const off = discountPercent(price, mrp);
  return (
    <span className={cn("inline-flex flex-wrap items-baseline gap-x-2", className)}>
      <span className={cn("font-semibold tabular-nums", off && "text-sale")}>{formatINR(price)}</span>
      {off > 0 && (
        <>
          <s className="text-xs tabular-nums text-muted">{formatINR(mrp)}</s>
          <span className="text-xs font-medium text-sale">{off}% off</span>
        </>
      )}
    </span>
  );
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "sale" | "ok" | "warn" | "dark"; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]",
        tone === "neutral" && "bg-ivory/90 text-ink",
        tone === "sale" && "bg-sale text-white",
        tone === "ok" && "bg-ok/10 text-ok",
        tone === "warn" && "bg-warn/10 text-warn",
        tone === "dark" && "bg-ink text-ivory",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse bg-stone/70", className)} />;
}
