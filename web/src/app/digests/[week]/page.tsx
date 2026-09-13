import { notFound } from "next/navigation";
import { apiGet } from "@/lib/api";
import type { Digest } from "@/lib/types";
import Markdown from "@/components/Markdown";
import SourceList from "@/components/SourceList";
import { day } from "@/lib/format";

// Rendered per request; every apiGet() call is cached for REVALIDATE_SECONDS
// in the data cache, which keeps serving stale data if a refresh fails.
export const dynamic = "force-dynamic";

export default async function DigestPage({ params }: { params: Promise<{ week: string }> }) {
  const { week } = await params;
  if (!/^\d{4}-W\d{2}$/.test(week)) notFound();
  const digest = await apiGet<Digest>(`/digests/${week}`);
  if (!digest) notFound();
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Digest · {digest.week}</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {day(digest.week_start)} → {day(digest.week_end)} · {digest.model} · generated {digest.generated_at.slice(0, 16).replace("T", " ")}
        </p>
      </div>
      {digest.sections.map((s) => (
        <section key={s.key} className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-3 text-lg font-semibold">{s.title}</h2>
          {s.markdown ? <Markdown text={s.markdown} /> : <p className="text-sm text-zinc-500">Nothing this week.</p>}
          <SourceList sources={s.sources} />
        </section>
      ))}
    </div>
  );
}
