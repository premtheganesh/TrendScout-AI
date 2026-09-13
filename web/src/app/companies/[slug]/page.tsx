import { notFound } from "next/navigation";
import { apiGet } from "@/lib/api";
import type { Company, FundingRound } from "@/lib/types";
import DocCard from "@/components/DocCard";
import { day, money } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function CompanyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const c = await apiGet<Company>(`/companies/${encodeURIComponent(slug)}`);
  if (!c) notFound();
  const rounds = (c.rounds as FundingRound[]).filter((r) => typeof r === "object");
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {[c.yc_batch && c.yc_batch !== "Unknown" ? `YC ${c.yc_batch}` : "", c.location && c.location !== "Unknown" ? c.location : "", c.launched_at ? `launched ${day(c.launched_at)}` : ""].filter(Boolean).join(" · ")}
          {c.website && (
            <>
              {" · "}
              <a href={c.website} target="_blank" rel="noreferrer" className="underline">{c.domain || c.website}</a>
            </>
          )}
        </p>
        {c.description && <p className="mt-3 max-w-2xl">{c.description}</p>}
        {c.tags?.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1">
            {c.tags.map((t) => <li key={t} className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">{t}</li>)}
          </ul>
        )}
      </div>

      {rounds.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Funding · {money(c.funding_total_usd)} total</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {rounds.map((r) => (
              <li key={r._id}>
                <span className="font-medium">{money(r.amount_usd)}</span>
                {r.round && <span> {r.round}</span>}
                {r.lead_investors.length > 0 && <span> led by {r.lead_investors.join(", ")}</span>}
                {r.announced_at && <span className="text-zinc-500"> · {day(r.announced_at)}</span>}
                <span className="ml-2 text-xs text-zinc-500">{r.confidence}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.documents && c.documents.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Documents ({c.documents.length})</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {c.documents.map((d) => <DocCard key={d._id} doc={d} />)}
          </div>
        </section>
      )}
    </div>
  );
}
