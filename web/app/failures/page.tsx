"use client";

import { useState } from "react";
import useSWR from "swr";

import { cn, fetcher, formatUsd } from "@/lib/utils";

type Bucket = {
  bucket: string;
  trade_count: number;
  total_pnl: number;
  avg_pnl: number;
};

const BUCKET_DESC: Record<string, string> = {
  implausible:   "Fill price was outside actual trading range during the fill window — sim bug or data gap.",
  picked_off:    "Maker fill followed by ≥2¢ adverse price move within 60s — taker on the other side was sharp.",
  thin_market:   "Spread > 3¢ at entry; expect higher slippage when going to real money.",
  moved_market:  "Order size > 10% of resting depth at price; the fill assumes infinite liquidity.",
  missed_fill:   "Maker order never filled — book walked past us without a print at our price.",
  regular_loss:  "Clean fill that simply went the wrong way; the strategy was wrong about direction.",
};

const BUCKET_ICON: Record<string, React.ReactNode> = {
  implausible:  <path d="M8 2L2 14h12L8 2zm0 4v4m0 2.5h.01" strokeLinecap="round" strokeLinejoin="round" />,
  picked_off:   <path d="M2 8 8 2l6 6-6 6L2 8z" strokeLinejoin="round" />,
  thin_market:  <path d="M2 12h12M8 2v10M4 6h8" strokeLinecap="round" />,
  moved_market: <path d="M3 8h10m-5-5v10" strokeLinecap="round" />,
  missed_fill:  <path d="M2 8h12M8 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />,
  regular_loss: <path d="M2 4l4 8 3-5 3 5 4-8" strokeLinecap="round" strokeLinejoin="round" />,
};

const WINDOWS = [24, 72, 168, 720] as const;

export default function FailuresPage() {
  const [hours, setHours] = useState(168);
  const { data } = useSWR<{ buckets: Bucket[] }>(
    `/api/backend/analytics/failure_modes?hours=${hours}`,
    fetcher,
    { refreshInterval: 60_000 },
  );

  const buckets = data?.buckets ?? [];
  const total = buckets.reduce((s, b) => s + b.trade_count, 0);
  const worstPnl = buckets.length > 0 ? Math.min(...buckets.map((b) => b.total_pnl)) : 0;

  return (
    <div className="space-y-8">

      {/* Hero */}
      <section>
        <h1 className="text-[2rem] font-bold tracking-tight">Failure Analysis</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Losing trades grouped by failure mode. The categories tell you exactly what to fix.
        </p>
      </section>

      {/* Time window selector */}
      <section className="flex flex-wrap items-end gap-3">
        <div>
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">Window</div>
          <div className="flex rounded-xl border border-border/60 bg-card p-1">
            {WINDOWS.map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setHours(h)}
                className={cn(
                  "cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                  hours === h
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {h}h
              </button>
            ))}
          </div>
        </div>

        {/* Summary stat */}
        {buckets.length > 0 && (
          <div className="rounded-xl border border-loss/25 bg-loss/5 px-4 py-2">
            <div className="text-[10px] font-bold uppercase tracking-widest text-loss/70">Total losses</div>
            <div className="mt-0.5 font-mono text-sm font-bold text-loss">
              {total} trades · {formatUsd(buckets.reduce((s, b) => s + b.total_pnl, 0), { sign: true })}
            </div>
          </div>
        )}
      </section>

      {/* Bucket cards */}
      {buckets.length === 0 ? (
        <div className="flex flex-col items-center rounded-xl border border-dashed border-border/50 bg-card/40 px-6 py-14 text-center">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-profit/30 bg-profit/10">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" className="text-profit" aria-hidden="true">
              <path d="M3 8l3.5 3.5L13 4" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-foreground">No losing trades in this window</p>
          <p className="mt-1 text-xs text-muted-foreground/60">Clean execution over the last {hours}h</p>
        </div>
      ) : (
        <div className="space-y-3">
          {buckets.map((b) => {
            const share = total > 0 ? b.trade_count / total : 0;
            const severity = worstPnl !== 0 ? Math.min(1, b.total_pnl / worstPnl) : 0;
            return (
              <div
                key={b.bucket}
                className="relative overflow-hidden rounded-xl border border-border/60 bg-card p-5 transition-colors hover:bg-muted/10"
              >
                {/* Left severity stripe */}
                <div
                  className="absolute inset-y-0 left-0 w-0.5 rounded-l-xl"
                  style={{ backgroundColor: `hsl(var(--loss) / ${0.3 + severity * 0.7})` }}
                />

                <div className="flex items-start justify-between gap-4 pl-3">
                  {/* Icon + label */}
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-loss/20 bg-loss/10">
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="hsl(var(--loss))" strokeWidth="1.5" aria-hidden="true">
                        {BUCKET_ICON[b.bucket] ?? <circle cx="8" cy="8" r="5" />}
                      </svg>
                    </div>
                    <div>
                      <div className="font-semibold capitalize tracking-tight">{b.bucket.replace(/_/g, " ")}</div>
                      <div className="mt-0.5 max-w-xl text-xs leading-relaxed text-muted-foreground">
                        {BUCKET_DESC[b.bucket] ?? ""}
                      </div>
                    </div>
                  </div>

                  {/* Numbers */}
                  <div className="shrink-0 text-right">
                    <div className="font-mono text-sm font-bold text-loss">
                      {formatUsd(Number(b.total_pnl))}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {b.trade_count} trades · avg {formatUsd(Number(b.avg_pnl))}
                    </div>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="mt-4 pl-3">
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground/60 mb-1.5">
                    <span className="font-bold uppercase tracking-widest">Share of failures</span>
                    <span className="font-mono font-semibold">{(share * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${share * 100}%`,
                        backgroundColor: "hsl(var(--loss) / " + (0.5 + severity * 0.4) + ")",
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
