import { apiGet } from "@/lib/api";
import type { Trends, Velocity } from "@/lib/types";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function TrendsPage() {
  const [trends, repos, models] = await Promise.all([
    apiGet<Trends>("/trends?limit=25"),
    apiGet<Velocity>("/trends/velocity?type=repo&days=7"),
    apiGet<Velocity>("/trends/velocity?type=model&days=7"),
  ]);
  if (!trends) return <p className="text-sm text-zinc-500">No trend data yet.</p>;
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl font-semibold">Trends · {trends.week}</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          A topic is rising when this week&apos;s mentions beat the mean of the four weeks before it: score = (count − baseline) / √(baseline + 1), minimum 3 mentions.
        </p>
        {trends.insufficient_history && (
          <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
            Only {trends.history_weeks} of 4 prior weeks have data, so these scores are indicative rather than established trends.
          </p>
        )}
      </div>

      <div className="grid gap-8 md:grid-cols-2">
        <section>
          <h2 className="text-lg font-semibold">Rising</h2>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-xs uppercase text-zinc-500"><tr><th className="py-1">Topic</th><th className="py-1 text-right">This week</th><th className="py-1 text-right">Baseline</th><th className="py-1 text-right">Score</th></tr></thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {trends.rising.map((t) => (
                <tr key={t.topic}><td className="py-1">{t.topic}</td><td className="py-1 text-right">{t.count}</td><td className="py-1 text-right text-zinc-500">{t.baseline}</td><td className="py-1 text-right font-medium">{t.score.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
        <section>
          <h2 className="text-lg font-semibold">Most mentioned</h2>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-xs uppercase text-zinc-500"><tr><th className="py-1">Topic</th><th className="py-1 text-right">This week</th></tr></thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {trends.top.map((t) => (
                <tr key={t.topic}><td className="py-1">{t.topic}</td><td className="py-1 text-right">{t.count}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <div className="grid gap-8 md:grid-cols-2">
        <VelocityList v={repos} title="Repos gaining stars (7d)" />
        <VelocityList v={models} title="Models gaining likes (7d)" />
      </div>
    </div>
  );
}

function VelocityList({ v, title }: { v: Velocity | null; title: string }) {
  return (
    <section>
      <h2 className="text-lg font-semibold">{title}</h2>
      {!v || v.insufficient_history ? (
        <p className="mt-2 text-sm text-zinc-500">Not enough snapshot history yet — the daily pipeline records counts each day, and velocity needs two days.</p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm">
          {v.items.map((r) => (
            <li key={r.doc_id} className="flex justify-between">
              <span>{r.url ? <a href={r.url} target="_blank" rel="noreferrer" className="hover:underline">{r.title ?? r.doc_id}</a> : r.title ?? r.doc_id}</span>
              <span className="font-medium">+{r.gained.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
