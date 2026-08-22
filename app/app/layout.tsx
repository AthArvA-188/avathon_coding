import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Program Z Planner",
  description:
    "Demand forecast, MPS + pack-out plan, and enclosure-shortage scenario",
};

const nav = [
  { href: "/forecast", label: "Forecast" },
  { href: "/plan", label: "MPS & Pack-out" },
  { href: "/scenario", label: "Shortage Scenario" },
  { href: "/signals", label: "Signals & Agents" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <div className="mx-auto max-w-6xl px-6 py-3 flex items-center gap-8">
            <a href="/" className="font-semibold tracking-tight">
              Program Z Planner
            </a>
            <nav className="flex gap-5 text-sm">
              {nav.map((n) => (
                <a
                  key={n.href}
                  href={n.href}
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                >
                  {n.label}
                </a>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl px-6 py-8 flex-1">
          {children}
        </main>
      </body>
    </html>
  );
}
