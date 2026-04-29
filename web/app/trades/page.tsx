"use client";

import { useState } from "react";

import { useApi } from "@/lib/api";
import { cn, formatUsd } from "@/lib/utils";

type Trade = {
  trade_id: string;
  sleeve_id: string;
  strategy_name: string;
  config_id: string;
  market_id: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  entry_size: number;
  pnl_after_haircut_usd: number | null;
  fill_type: string;
  realism_flag: string;
  market_category: string | null;
  source: string;
};

export default function TradeExplorerPage() {
  const [source, setSource] = useState<string>("");
  const [sleeve, setSleeve] = useState<string>("");
  const params = new URLSearchParams({ limit: "200" });
  if (source) params.set("source", source);
  if (sleeve) params.set("sleeve_id", sleeve);

  const { data } = useApi<{ trades: Trade[] }>(`/system/recent_trades?${params}`, 15_000);
  const trades = data?.trades ?? [];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Trade Explorer</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every paper trade with full context. Filter and drill in.
        </p>
      </section>

      <section className="flex flex-wrap gap-3">
        <Filter label="Source">
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="rounded-md border border-border bg-card px-3 py-2 text-sm"
          >
            <option value="">all</option>
            <option value="live">live</option>
            <option value="replay">replay</option>
          </select>
        </Filter>
        <Filter label="Sleeve">
          <input
            type="text"
            value={sleeve}
            onChange={(e) => setSleeve(e.target.value)}
            placeholder="(any)"
            className="w-64 rounded-md border border-border bg-card px-3 py-2 font-mono text-sm"
          />
        </Filter>
      </section>

      <section className="overflow-auto rounded-lg border border-border/60">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Sleeve</th>
              <th className="px-3 py-2 text-left">Strategy/Config</th>
              <th className="px-3 py-2 text-left">Market</th>
              <th className="px-3 py-2 text-left">Cat</th>
              <th className="px-3 py-2 text-left">Side</th>
              <th className="px-3 py-2 text-right">Size</th>
              <th className="px-3 py-2 text-right">Entry</th>
              <th className="px-3 py-2 text-right">Exit</th>
              <th className="px-3 py-2 text-right">P&L</th>
              <th className="px-3 py-2 text-left">Fill</th>
              <th className="px-3 py-2 text-left">Flag</th>
              <th className="px-3 py-2 text-left">Source</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((tr) => {
              const pnl = Number(tr.pnl_after_haircut_usd ?? 0);
              const cls = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "";
              return (
                <tr key={tr.trade_id} className="border-t border-border/40 hover:bg-muted/20">
                  <td className="px-3 py-2 font-mono text-[12px]">{tr.sleeve_id}</td>
                  <td className="px-3 py-2 text-xs">
                    <div>{tr.strategy_name}</div>
                    <div className="text-muted-foreground">{tr.config_id}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-[12px]">{tr.market_id.slice(0, 18)}…</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{tr.market_category ?? "—"}</td>
                  <td className="px-3 py-2">{tr.side}</td>
                  <td className="px-3 py-2 text-right font-mono">{tr.entry_size.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono">{tr.entry_price.toFixed(3)}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {tr.exit_price === null ? "—" : tr.exit_price.toFixed(3)}
                  </td>
                  <td className={cn("px-3 py-2 text-right font-mono", cls)}>
                    {formatUsd(pnl, { sign: true })}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{tr.fill_type}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{tr.realism_flag}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{tr.source}</td>
                </tr>
              );
            })}
            {trades.length === 0 && (
              <tr>
                <td colSpan={12} className="p-8 text-center text-sm text-muted-foreground">
                  No trades yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      {children}
    </label>
  );
}
