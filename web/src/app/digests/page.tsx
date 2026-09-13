import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { DigestSummary, Paged } from "@/lib/types";
import { day } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function DigestsPage() {
  const data = await apiGet<Paged<DigestSummary>>("/digests?limit=52");
  if (!data) return <p className="text-sm text-zinc-500">Nothing here yet.</p>;
  return (
    <div>
      <h1 className="text-2xl font-semibold">Weekly digests</h1>
      <ul className="mt-6 divide-y divide-zinc-200 dark:divide-zinc-800">
        {data.items.map((d) => (
          <li key={d.week} className="flex items-center justify-between py-3">
            <Link href={`/digests/${d.week}`} className="font-medium hover:underline">{d.week}</Link>
            <span className="text-sm text-zinc-500">
              {day(d.week_start)} → {day(d.week_end)} · {d.bullets} bullets · {d.counts.launches ?? 0} launches, {d.counts.funding ?? 0} funding, {d.counts.open_source ?? 0} open source
            </span>
          </li>
        ))}
        {data.items.length === 0 && <li className="py-3 text-sm text-zinc-500">No digests yet.</li>}
      </ul>
    </div>
  );
}
