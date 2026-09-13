import Link from "next/link";
import type { Doc } from "@/lib/types";
import { day, docSubtitle } from "@/lib/format";
import TypeBadge from "./TypeBadge";

export default function DocCard({ doc }: { doc: Doc }) {
  const subtitle = docSubtitle(doc);
  const text = ((doc.description ?? doc.summary ?? doc.abstract) as string | undefined) ?? "";
  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <TypeBadge type={doc.type} />
        {doc.event_at && <span>{day(doc.event_at)}</span>}
        {subtitle && <span>· {subtitle}</span>}
      </div>
      <h3 className="mt-1 font-semibold leading-snug">
        {doc.url ? (
          <a href={doc.url} target="_blank" rel="noreferrer" className="hover:underline">{doc.title}</a>
        ) : (
          doc.title
        )}
      </h3>
      {text && <p className="mt-1 line-clamp-3 text-sm text-zinc-600 dark:text-zinc-400">{text}</p>}
      <div className="mt-2 text-xs">
        <Link href={`/documents/${doc._id}`} className="text-zinc-500 hover:underline">details</Link>
      </div>
    </article>
  );
}
