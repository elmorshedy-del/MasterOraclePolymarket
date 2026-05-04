import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type FormatUsdOptions = {
  sign?: boolean;
  cents?: boolean;
  compact?: boolean;
};

export function formatUsd(value: number | null | undefined, opts: FormatUsdOptions = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: opts.cents === false ? 0 : 2,
    maximumFractionDigits: opts.cents === false ? 0 : 2,
    notation: opts.compact ? "compact" : "standard",
  }).format(Math.abs(value));
  if (opts.sign) {
    return `${value >= 0 ? "+" : "−"}${formatted}`;
  }
  return value < 0 ? `−${formatted}` : formatted;
}

export function formatPct(value: number, decimals = 2) {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Shared SWR-style fetcher. Throws on non-2xx so SWR's error state actually
 * fires instead of pages silently rendering empty results from a 500 body.
 */
export const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`fetch ${url} → HTTP ${res.status}`);
  }
  return res.json();
};
