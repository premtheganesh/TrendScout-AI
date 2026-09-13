import Chat from "./Chat";

export default function AskPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Ask TrendScout</h1>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        Answers come only from the indexed corpus, with a [n] citation per claim. &ldquo;This week&rdquo; and &ldquo;last month&rdquo; are understood.
      </p>
      <Chat />
    </div>
  );
}
