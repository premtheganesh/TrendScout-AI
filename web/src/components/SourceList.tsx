import type { DigestSource } from "@/lib/types";
import TypeBadge from "./TypeBadge";
import { day } from "@/lib/format";

export default function SourceList({ sources, title = "Sources" }: { sources: DigestSource[]; title?: string }) {
  if (!sources.length) return null;
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-zinc-500">{title} ({sources.length})</summary>
      <ol className="mt-2 space-y-1">
        {sources.map((s) => (
          <li key={s.n} id={`src-${s.n}`} className="flex items-start gap-2 scroll-mt-24">
            <span className="w-7 shrink-0 font-mono text-xs text-zinc-500">[{s.n}]</span>
            <TypeBadge type={s.type} />
            <span>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" className="hover:underline">{s.title}</a>
              ) : (
                s.title
              )}
              {s.event_at && <span className="ml-2 text-xs text-zinc-500">{day(s.event_at)}</span>}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}
