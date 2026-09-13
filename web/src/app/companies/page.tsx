import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { Company, Paged } from "@/lib/types";
import { money } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function CompaniesPage({ searchParams }: { searchParams: Promise<{ q?: string; sort?: string }> }) {
  const { q, sort } = await searchParams;
  const order = sort === "documents" || sort === "name" ? sort : "funding";
  const query = q ? `&q=${encodeURIComponent(q.slice(0, 100))}` : "";
  const data = await apiGet<Paged<Company>>(`/companies?limit=60&sort=${order}${query}`);
  if (!data) return <p className="text-sm text-zinc-500">Nothing here yet.</p>;
  return (
    <div>
      <h1 className="text-2xl font-semibold">Companies</h1>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        One record per company, resolved across sources by YC slug, then website domain, then an unambiguous name. {data.total.toLocaleString()} companies.
      </p>
      <form className="mt-4 flex gap-2">
        <input name="q" defaultValue={q ?? ""} placeholder="Search by name" className="rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900" />
        <select name="sort" defaultValue={order} className="rounded-lg border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-700 dark:bg-zinc-900">
          <option value="funding">most funding</option>
          <option value="documents">most documents</option>
          <option value="name">name</option>
        </select>
        <button className="rounded-lg bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-zinc-900">Go</button>
      </form>
      <ul className="mt-6 divide-y divide-zinc-200 dark:divide-zinc-800">
        {data.items.map((c) => (
          <li key={c._id} className="flex items-start justify-between gap-4 py-3">
            <div>
              <Link href={`/companies/${c._id}`} className="font-medium hover:underline">{c.name}</Link>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{c.description?.slice(0, 140)}</p>
              <p className="text-xs text-zinc-500">
                {[c.yc_batch && c.yc_batch !== "Unknown" ? `YC ${c.yc_batch}` : "", c.location && c.location !== "Unknown" ? c.location : "", c.domain].filter(Boolean).join(" · ")}
              </p>
            </div>
            <div className="shrink-0 text-right text-sm">
              {c.funding_total_usd > 0 && <div className="font-semibold">{money(c.funding_total_usd)}</div>}
              <div className="text-xs text-zinc-500">{c.document_count} docs</div>
            </div>
          </li>
        ))}
        {data.items.length === 0 && <li className="py-3 text-sm text-zinc-500">No companies match.</li>}
      </ul>
    </div>
  );
}
