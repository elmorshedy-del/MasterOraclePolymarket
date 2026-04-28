"use client";

import useSWR from "swr";

import { cn, formatUsd } from "@/lib/utils";

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

const fetcher = (url: string) => fetch(url).then((r) => r.json());

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

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Loading sleeves…</div>;
  }
  if (error) {
    return <div className="text-sm text-loss">Could not load sleeves.</div>;
  }
  const sleeves = data?.sleeves ?? [];
  if (sleeves.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
        No sleeves configured yet. Drop a YAML in{" "}
        <code className="rounded bg-muted px-1.5 py-0.5 text-[12px]">
          src/configs/sleeves/
        </code>
        .
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-2 text-left">Sleeve</th>
            <th className="px-4 py-2 text-left">Strategy / Config</th>
            <th className="px-4 py-2 text-left">Mode</th>
            <th className="px-4 py-2 text-right">Starting</th>
            <th className="px-4 py-2 text-right">Realized</th>
            <th className="px-4 py-2 text-right">Capital</th>
            <th className="px-4 py-2 text-right">Open</th>
          </tr>
        </thead>
        <tbody>
          {sleeves.map((s) => {
            const pnl = Number(s.realized_pnl_usd ?? 0);
            const pnlClass = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-foreground";
            return (
              <tr
                key={s.sleeve_id}
                className="border-t border-border/40 hover:bg-muted/20"
              >
                <td className="px-4 py-3 font-mono text-[13px]">{s.sleeve_id}</td>
                <td className="px-4 py-3">
                  <div>{s.strategy_name}</div>
                  <div className="text-xs text-muted-foreground">{s.config_id}</div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "rounded px-2 py-0.5 text-[11px] font-medium",
                      MODE_COLOR[s.mode] ?? "bg-muted text-muted-foreground",
                    )}
                  >
                    {s.mode}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  {formatUsd(Number(s.starting_capital_usd), { cents: false })}
                </td>
                <td className={cn("px-4 py-3 text-right font-mono", pnlClass)}>
                  {formatUsd(pnl, { sign: true })}
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  {formatUsd(Number(s.capital_remaining), { cents: false })}
                </td>
                <td className="px-4 py-3 text-right font-mono">{s.open_positions}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
