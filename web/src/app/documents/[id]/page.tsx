import { notFound } from "next/navigation";
import { apiGet } from "@/lib/api";
import type { Doc } from "@/lib/types";
import TypeBadge from "@/components/TypeBadge";
import { day, docSubtitle } from "@/lib/format";

export const revalidate = 600;

type Entity = { entity_text: string; entity_type: string; count: number };

export default async function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[a-f0-9]{24}$/.test(id)) notFound();
  const doc = await apiGet<Doc & { entities?: Entity[] }>(`/documents/${id}`);
  if (!doc) notFound();
  const skip = new Set(["_id", "title", "url", "type", "entities", "description", "content_hash", "doc_key", "embedding_hash", "entities_hash", "funding_hash", "funding_extraction_version", "embedding_generated_at", "entities_extracted_at", "inserted_at", "updated_at", "scraped_at", "title_key"]);
  const fields = Object.entries(doc).filter(([k, v]) => !skip.has(k) && v != null && v !== "" && !(Array.isArray(v) && v.length === 0));
  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <TypeBadge type={doc.type} />
          {doc.event_at && <span>{day(doc.event_at)}</span>}
          <span>· {docSubtitle(doc)}</span>
        </div>
        <h1 className="mt-1 text-2xl font-semibold">{doc.title}</h1>
        {doc.url && <a href={doc.url} target="_blank" rel="noreferrer" className="text-sm underline">{doc.url}</a>}
        {typeof doc.description === "string" && doc.description && <p className="mt-3 max-w-2xl">{doc.description}</p>}
      </div>
      {doc.entities && doc.entities.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Entities</h2>
          <ul className="mt-2 flex flex-wrap gap-1">
            {doc.entities.map((e) => (
              <li key={`${e.entity_type}-${e.entity_text}`} className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                {e.entity_text} <span className="text-zinc-500">{e.entity_type}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h2 className="text-lg font-semibold">Fields</h2>
        <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
          {fields.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-zinc-500">{k}</dt>
              <dd className="break-words font-mono text-xs">{Array.isArray(v) ? v.map(String).join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
