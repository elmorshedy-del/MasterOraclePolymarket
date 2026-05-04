"use client";

import useSWR from "swr";

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function useApi<T>(path: string | null, refreshMs?: number) {
  return useSWR<T>(path ? `/api/backend${path}` : null, fetcher, {
    refreshInterval: refreshMs,
  });
}

export async function postApi<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} ${res.status}`);
  return res.json() as Promise<T>;
}
