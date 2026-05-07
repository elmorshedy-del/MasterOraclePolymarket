"use client";

import Link from "next/link";
import useSWR from "swr";

import { cn, fetcher, formatUsd } from "@/lib/utils";

type Sleeve = {
  sleeve_id: string;
  strategy_name: string;
  config_id: string;
  edge_class: string | null;
  starting_capital_usd: number;
  mode: string;
  enabled: boolean;
  realized_pnl_usd: number;
  unrealized_pnl_usd: number;
  capital_remaining: number;
  open_positions: number;
};

const MODE_COLOR: Record<string, string> = {
  live_full: "bg-profit/20 text-profit",
  live_signal: "bg-sky-500/20 text-sky-400",
  live_log: "bg-amber-500/20 text-amber-400",
  replay_only: "bg-muted text-muted-foreground",
};

export function SleevesTable() {
  const { data, error, isLoading } = useSWR<{ sleeves: Sleeve[] }>(
    "/api/backend/system/sleeves",
    fetcher,
    { refreshInterval: 10_000 },
  );

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading sleeves…</div>;
  if (error) return <div className="text-sm text-loss">Could not load sleeves.</div>;
  const sleeves = data?.sleeves ?? [];
  if (sleeves.length === 0) {
    return (
      <div className="flex flex-col items-center rounded-xl border border-dashed border-border/50 bg-card/40 px-6 py-14 text-center">
        <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full border border-border/60 bg-muted">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" className="text-muted-foreground" aria-hidden="true">
            <rect x="1" y="1" width="6" height="6" rx="1.25" />
            <rect x="11" y="1" width="6" height="6" rx="1.25" />
            <rect x="1" y="11" width="6" height="6" rx="1.25" />
            <rect x="11" y="11" width="6" height="6" rx="1.25" />
          </svg>
        </div>
        <p className="text-sm font-semibold text-foreground">No sleeves configured</p>
        <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-muted-foreground">
          Drop a YAML in{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">src/configs/sleeves/</code>
          {" "}to start running a strategy.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border/60">
      <table className="w-full text-sm">
        <thead className="border-b border-border/60 bg-muted/30 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">
          <tr>
            <th className="px-4 py-3 text-left">Sleeve</th>
            <th className="px-4 py-3 text-left">Strategy / Config</th>
            <th className="px-4 py-3 text-left">Mode</th>
            <th className="px-4 py-3 text-right">Starting</th>
            <th className="px-4 py-3 text-right">Realized</th>
            <th className="px-4 py-3 text-right">Capital</th>
            <th className="px-4 py-3 text-right">Open</th>
          </tr>
        </thead>
        <tbody>
          {sleeves.map((s) => {
            const pnl = Number(s.realized_pnl_usd ?? 0);
            const pnlClass = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-foreground";
            return (
              <tr key={s.sleeve_id} className="border-t border-border/40 transition-colors hover:bg-muted/20">
                <td className="px-4 py-3 font-mono text-[13px]">
                  <Link href={`/sleeves/${encodeURIComponent(s.sleeve_id)}`} className="cursor-pointer hover:text-highlight hover:underline transition-colors">
                    {s.sleeve_id}
                  </Link>
                </td>
                <td className="px-4 py-3">
                  <div className="text-sm">{s.strategy_name}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground/70">{s.config_id}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                    MODE_COLOR[s.mode] ?? "bg-muted text-muted-foreground",
                  )}>
                    {s.mode}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-sm">
                  {formatUsd(Number(s.starting_capital_usd), { cents: false })}
                </td>
                <td className={cn("px-4 py-3 text-right font-mono text-sm", pnlClass)}>
                  {formatUsd(pnl, { sign: true })}
                </td>
                <td className="px-4 py-3 text-right font-mono text-sm">
                  {formatUsd(Number(s.capital_remaining), { cents: false })}
                </td>
                <td className="px-4 py-3 text-right font-mono text-sm">{s.open_positions}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
