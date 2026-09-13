import { apiGet } from "@/lib/api";
import type { FundingRound, Paged } from "@/lib/types";
import { day, money } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function FundingPage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
  const { days } = await searchParams;
  const window = [7, 30, 90, 365].includes(Number(days)) ? Number(days) : 90;
  const data = await apiGet<Paged<FundingRound>>(`/funding?since_days=${window}&limit=100`);
  if (!data) return <p className="text-sm text-zinc-500">Nothing here yet.</p>;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Funding rounds</h1>
        <nav className="flex gap-2 text-sm">
          {[7, 30, 90, 365].map((d) => (
            <a key={d} href={`/funding?days=${d}`} className={`rounded px-2 py-1 ${d === window ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"}`}>
              {d}d
            </a>
          ))}
        </nav>
      </div>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        Extracted from funding news, largest first. Confidence is rule-derived: <em>high</em> means the company and the amount both appear verbatim in the article.
      </p>
      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="py-2 pr-3">Company</th>
              <th className="py-2 pr-3">Amount</th>
              <th className="py-2 pr-3">Round</th>
              <th className="py-2 pr-3">Lead</th>
              <th className="py-2 pr-3">Date</th>
              <th className="py-2 pr-3">Conf.</th>
              <th className="py-2">Sources</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {data.items.map((r) => (
              <tr key={r._id}>
                <td className="py-2 pr-3 font-medium">{r.company}</td>
                <td className="py-2 pr-3 whitespace-nowrap">
                  {money(r.amount_usd)}
                  {r.currency && r.currency !== "USD" && r.amount != null && (
                    <span className="ml-1 text-xs text-zinc-500">({r.amount.toLocaleString()} {r.currency})</span>
                  )}
                </td>
                <td className="py-2 pr-3">{r.round ?? ""}</td>
                <td className="py-2 pr-3">{r.lead_investors.slice(0, 2).join(", ")}</td>
                <td className="py-2 pr-3 whitespace-nowrap">{day(r.announced_at)}</td>
                <td className="py-2 pr-3">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${r.confidence === "high" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200" : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"}`}>
                    {r.confidence}
                  </span>
                </td>
                <td className="py-2 text-xs text-zinc-500">{r.publishers.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.items.length === 0 && <p className="py-4 text-sm text-zinc-500">No rounds in this window.</p>}
      </div>
    </div>
  );
}
