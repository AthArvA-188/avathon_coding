"use client";

// Per-page usage guide: what to click (DO) and the details that carry the
// story (WATCH FOR). Companion to the Provenance strip — that one says where
// the numbers come from; this one says how to drive the page.
export default function HowTo({
  dos,
  watch,
}: {
  dos: React.ReactNode[];
  watch: React.ReactNode[];
}) {
  return (
    <details className="mb-6 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-sm open:pb-3">
      <summary className="cursor-pointer select-none px-4 py-2.5 font-medium text-zinc-700 dark:text-zinc-300">
        How to use this page
      </summary>
      <div className="px-4 pt-1 grid gap-3 md:grid-cols-2 text-[13px] leading-6">
        <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400 mb-1">
            Do
          </div>
          <ul className="list-disc pl-4 text-zinc-700 dark:text-zinc-300">
            {dos.map((d, i) => (
              <li key={i} className="mb-1">{d}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-md bg-amber-50 dark:bg-amber-950/40 p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-500 mb-1">
            Watch for
          </div>
          <ul className="list-disc pl-4 text-zinc-700 dark:text-zinc-300">
            {watch.map((w, i) => (
              <li key={i} className="mb-1">{w}</li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  );
}
