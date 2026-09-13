import { TYPE_COLOR, TYPE_LABEL } from "@/lib/format";

export default function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide ${TYPE_COLOR[type] ?? "bg-zinc-100 text-zinc-700"}`}>
      {TYPE_LABEL[type] ?? type}
    </span>
  );
}
