# Web — dashboard

Next.js 14 + shadcn/ui + Tremor + Recharts. Dark by default. Matches the
"calm, intentional, not a Bloomberg terminal" design directive in
[`../DESIGN.md`](../DESIGN.md).

## Local dev

```bash
cd web
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

The app proxies `/api/backend/*` → the FastAPI service at `BACKEND_URL`.

## Pages

Phase 0 includes only `app/page.tsx` (Overview placeholder). Phase 3 builds out:

- `app/sleeves/page.tsx` — list + detail for each sleeve
- `app/matrix/page.tsx` — pivot explorer
- `app/trades/page.tsx` — trade explorer
- `app/failures/page.tsx` — failure analysis
- `app/lab/page.tsx` — Strategy Lab (replay)

## Theming

Tokens are in `app/globals.css`. The root layout sets `className="dark"` on
`<html>`. P&L colors use semantic tokens (`--profit`, `--loss`) so they can
be tuned without changing components.
