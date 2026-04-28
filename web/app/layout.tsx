import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Paper Trade Lab",
  description: "Research platform for prediction-market strategies",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} dark`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="border-b border-border/60">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
              <div className="flex items-center gap-3">
                <div className="h-7 w-7 rounded-md bg-gradient-to-br from-emerald-400/80 to-sky-500/80" />
                <span className="text-sm font-semibold tracking-tight text-foreground">
                  Paper Trade Lab
                </span>
                <span className="rounded-full border border-border/60 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                  Phase 0
                </span>
              </div>
              <nav className="flex items-center gap-6 text-sm text-muted-foreground">
                <a className="hover:text-foreground transition-colors" href="/">Overview</a>
                <a className="hover:text-foreground transition-colors" href="/sleeves">Sleeves</a>
                <a className="hover:text-foreground transition-colors" href="/matrix">Matrix</a>
                <a className="hover:text-foreground transition-colors" href="/trades">Trades</a>
                <a className="hover:text-foreground transition-colors" href="/failures">Failures</a>
                <a className="hover:text-foreground transition-colors" href="/lab">Strategy Lab</a>
              </nav>
            </div>
          </header>
          <main className="flex-1">
            <div className="mx-auto max-w-7xl px-6 py-8">{children}</div>
          </main>
          <footer className="border-t border-border/60 px-6 py-4 text-xs text-muted-foreground">
            <div className="mx-auto flex max-w-7xl items-center justify-between">
              <span>master-paper-trade-lab</span>
              <span className="font-mono">v0.1.0</span>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
