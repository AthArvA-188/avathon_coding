"use client";

// Every page answers three questions up front: where the values come from
// (tables + upstream stage), what model/parameters produced them, and what
// the reader should take away. Rendered as a collapsible strip.
export default function Provenance({
  sources,
  model,
  params,
  takeaway,
}: {
  sources: string;
  model: string;
  params: string[];
  takeaway: string;
}) {
  return (
    <details className="mb-6 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-sm open:pb-3">
      <summary className="cursor-pointer select-none px-4 py-2.5 font-medium text-zinc-700 dark:text-zinc-300">
        Where these numbers come from
      </summary>
      <div className="px-4 pt-1 grid gap-2 text-[13px] leading-6">
        <div>
          <span className="font-semibold">Data:</span>{" "}
          <span className="text-zinc-600 dark:text-zinc-400">{sources}</span>
        </div>
        <div>
          <span className="font-semibold">Model / method:</span>{" "}
          <span className="text-zinc-600 dark:text-zinc-400">{model}</span>
        </div>
        <div>
          <span className="font-semibold">Key parameters:</span>
          <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
            {params.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
        <div>
          <span className="font-semibold">So what:</span>{" "}
          <span className="text-zinc-600 dark:text-zinc-400">{takeaway}</span>
        </div>
      </div>
    </details>
  );
}
