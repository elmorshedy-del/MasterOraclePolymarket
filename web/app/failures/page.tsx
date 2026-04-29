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
  implausible: "Fill price was outside actual trading range during the fill window — sim bug or data gap.",
  picked_off: "Maker fill followed by ≥2¢ adverse price move within 60s — taker on the other side was sharp.",
  thin_market: "Spread > 3¢ at entry; expect higher slippage when going to real money.",
  moved_market: "Order size > 10% of resting depth at price; the fill assumes infinite liquidity.",
  missed_fill: "Maker order never filled — book walked past us without a print at our price.",
  regular_loss: "Clean fill that simply went the wrong way; the strategy was wrong about direction.",
};

export default function FailuresPage() {
  const [hours, setHours] = useState(168);
  const { data } = useSWR<{ buckets: Bucket[] }>(
    `/api/backend/analytics/failure_modes?hours=${hours}`,
    fetcher,
    { refreshInterval: 60_000 },
  );

  const buckets = data?.buckets ?? [];
  const total = buckets.reduce((s, b) => s + b.trade_count, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Failure Analysis</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Losing trades grouped by failure mode. The categories tell you what to fix.
        </p>
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        Window:
        {[24, 72, 168, 720].map((h) => (
          <button
            key={h}
            onClick={() => setHours(h)}
            className={cn(
              "rounded-md px-3 py-1",
              hours === h ? "bg-accent text-accent-foreground" : "hover:bg-accent/40",
            )}
          >
            {h}h
          </button>
        ))}
      </div>

      {buckets.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
          No losing trades in this window.
        </div>
      ) : (
        <div className="space-y-3">
          {buckets.map((b) => {
            const share = total > 0 ? b.trade_count / total : 0;
            return (
              <div key={b.bucket} className="rounded-lg border border-border/60 bg-card p-5">
                <div className="flex items-baseline justify-between gap-4">
                  <div>
                    <div className="text-sm font-medium">{b.bucket}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{BUCKET_DESC[b.bucket] ?? ""}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-sm text-loss">{formatUsd(Number(b.total_pnl))}</div>
                    <div className="text-xs text-muted-foreground">
                      {b.trade_count} trades · avg {formatUsd(Number(b.avg_pnl))}
                    </div>
                  </div>
                </div>
                <div className="mt-3 h-1.5 rounded-full bg-muted">
                  <div className="h-full rounded-full bg-loss/70" style={{ width: `${share * 100}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
