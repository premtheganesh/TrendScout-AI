// The digest and chat answers are plain markdown bullets with [n]
// citations. A small renderer is enough: bullets, bold, links, and [n]
// turned into anchors that jump to the numbered source.

import React from "react";

function inline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\[(\d+)\]|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith("**")) {
      out.push(<strong key={`${keyPrefix}-b${i++}`}>{token.slice(2, -2)}</strong>);
    } else if (m[2]) {
      out.push(
        <a key={`${keyPrefix}-c${i++}`} href={`#src-${m[2]}`} className="ml-0.5 rounded bg-zinc-200 px-1 text-xs font-mono text-zinc-700 no-underline hover:bg-zinc-300 dark:bg-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-600">
          {m[2]}
        </a>,
      );
    } else if (m[3] && m[4]) {
      out.push(
        <a key={`${keyPrefix}-l${i++}`} href={m[4]} target="_blank" rel="noreferrer" className="underline">
          {m[3]}
        </a>,
      );
    }
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.split("\n").map((l) => l.trimEnd()).filter((l) => l.trim() !== "");
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (k: number) => {
    if (bullets.length) {
      blocks.push(
        <ul key={`ul-${k}`} className="space-y-2 pl-5 list-disc marker:text-zinc-400">
          {bullets.map((b, j) => (
            <li key={j} className="leading-relaxed">{inline(b, `${k}-${j}`)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  lines.forEach((line, k) => {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
    } else {
      flush(k);
      blocks.push(<p key={`p-${k}`} className="leading-relaxed">{inline(line, `p${k}`)}</p>);
    }
  });
  flush(lines.length);
  return <div className="space-y-3">{blocks}</div>;
}
