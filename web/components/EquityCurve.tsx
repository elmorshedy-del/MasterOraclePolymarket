"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatUsd } from "@/lib/utils";

type Point = { ts: string; capital_remaining: number; realized_pnl_usd?: number };

export function EquityCurve({ points, height = 240 }: { points: Point[]; height?: number }) {
  if (!points || points.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-lg border border-dashed border-border/60 text-sm text-muted-foreground"
      >
        No P&L data yet.
      </div>
    );
  }
  const data = points.map((p) => ({
    ts: new Date(p.ts).toLocaleString(),
    capital: Number(p.capital_remaining),
  }));
  const last = data[data.length - 1];
  const first = data[0];
  const trendUp = (last?.capital ?? 0) >= (first?.capital ?? 0);

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ left: 0, right: 0, top: 4, bottom: 0 }}>
          <defs>
            <linearGradient id="eqGradUp" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--profit))" stopOpacity={0.4} />
              <stop offset="100%" stopColor="hsl(var(--profit))" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="eqGradDown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--loss))" stopOpacity={0.4} />
              <stop offset="100%" stopColor="hsl(var(--loss))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="ts" hide />
          <YAxis
            tickFormatter={(v) => formatUsd(v, { cents: false, compact: true })}
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            stroke="transparent"
            width={50}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: "hsl(var(--muted-foreground))" }}
            formatter={(value: number) => [formatUsd(Number(value)), "Capital"]}
          />
          <Area
            type="monotone"
            dataKey="capital"
            stroke={trendUp ? "hsl(var(--profit))" : "hsl(var(--loss))"}
            strokeWidth={1.5}
            fill={trendUp ? "url(#eqGradUp)" : "url(#eqGradDown)"}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
