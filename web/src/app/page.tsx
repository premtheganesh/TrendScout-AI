import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { Digest, DocumentsResponse, Meta, Trends } from "@/lib/types";
import Markdown from "@/components/Markdown";
import SourceList from "@/components/SourceList";
import { day, num } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function Home() {
  const [digest, meta, trends, recent] = await Promise.all([
    apiGet<Digest>("/digests/latest"),
    apiGet<Meta>("/meta"),
    apiGet<Trends>("/trends?limit=8"),
    apiGet<DocumentsResponse>("/documents?since_days=7&limit=1"),
  ]);


  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-3xl font-semibold tracking-tight">This week in AI startups</h1>
        <p className="mt-2 max-w-2xl text-zinc-600 dark:text-zinc-400">
          Launches, funding and open source from {meta ? num(meta.documents.total) : "…"} documents across{" "}
          {meta ? meta.sources.length : "…"} sources. Every bullet is cited against the document it came from.
        </p>
        {meta && (
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Stat label="New in the last 7 days" value={recent ? num(recent.total) : "…"} />
            <Stat label="Newest event" value={day(meta.newest_event_at)} />
            <Stat label="Index built" value={meta.index.built_at.slice(0, 16).replace("T", " ")} />
            <Stat label="Entities" value={num(meta.entities)} />
          </dl>
        )}
      </section>

      {digest ? (
        <section className="space-y-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-xl font-semibold">Digest · {digest.week}</h2>
            <span className="text-xs text-zinc-500">
              {day(digest.week_start)} → {day(digest.week_end)} · generated {digest.generated_at.slice(0, 16).replace("T", " ")}
            </span>
          </div>
          {digest.sections.map((s) => (
            <div key={s.key} className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
              <h3 className="mb-3 text-lg font-semibold">{s.title}</h3>
              {s.markdown ? <Markdown text={s.markdown} /> : <p className="text-sm text-zinc-500">Nothing this week.</p>}
              <SourceList sources={s.sources} />
            </div>
          ))}
          <p className="text-sm">
            <Link href="/digests" className="underline">All weeks →</Link>
          </p>
        </section>
      ) : (
        <p className="text-sm text-zinc-500">No digest has been generated yet.</p>
      )}

      {trends && trends.rising.length > 0 && (
        <section>
          <h2 className="text-xl font-semibold">Rising topics</h2>
          {trends.insufficient_history && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
              Only {trends.history_weeks} of 4 prior weeks have data — indicative, not yet a trend.
            </p>
          )}
          <ul className="mt-3 flex flex-wrap gap-2">
            {trends.rising.map((t) => (
              <li key={t.topic} className="rounded-full border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700">
                {t.topic} <span className="text-zinc-500">{t.count} · +{t.score.toFixed(1)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-sm"><Link href="/trends" className="underline">Trends →</Link></p>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-1 font-semibold">{value || "—"}</dd>
    </div>
  );
}
