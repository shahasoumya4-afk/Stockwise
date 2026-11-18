import { createFileRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Bot, MessageCircle, Plus, Send, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/irm/PageHeader";
import { endpoints, pick } from "@/lib/api";

export const Route = createFileRoute("/_app/assistant")({
  head: () => ({ meta: [{ title: "Inventory assistant — Stockwise" }] }),
  component: Assistant,
});

type Message = { role: "user" | "assistant"; text: string; sources?: string[] };
const SUGGESTION_GROUPS = [
  { title: "Projects", questions: ["Which projects are ongoing?", "What is the status of project PRJ-104?", "Which projects are due to finish this month?"] },
  { title: "Inventory", questions: ["How much allocated material is left for project PRJ-104?", "How much ELE-001 is available?", "Which warehouse has the most available cable?"] },
  { title: "Shortages & restocking", questions: ["Which project has the most urgent shortage?", "Can the supplier order arrive before the need date?", "Can another project spare this material?", "What is the fastest way to cover PRJ-104's shortage?"] },
  { title: "Access", questions: ["Who can view inventory for project PRJ-104?", "Who can approve this project's material estimate?", "Why can't I see this project's inventory?"] },
];

function Assistant() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const chat = useMutation({
    mutationFn: ({ prompt, conversation }: { prompt: string; conversation?: string | undefined }) => endpoints.inventoryChat(prompt, conversation),
    onSuccess: (data) => {
      const id = pick(data, "conversation_id", "conversationId");
      if (id) setConversationId(String(id));
      setMessages((current) => [...current,
        { role: "assistant", text: String(pick(data, "answer", "response", "message") ?? "I couldn't form an answer from the available inventory data."), sources: pick(data, "sources", "data_sources") },
      ]);
    },
  });

  const send = (event?: FormEvent, value = question) => {
    event?.preventDefault();
    const prompt = value.trim();
    if (!prompt || chat.isPending) return;
    setMessages((current) => [...current, { role: "user", text: prompt }]);
    chat.mutate({ prompt, conversation: conversationId });
    setQuestion("");
  };

  return (
    <>
      <PageHeader title="Inventory assistant" description="Ask questions in plain language. Answers should be grounded in current project and stock records." />
      <div className="mx-auto flex min-h-[65vh] max-w-4xl flex-col overflow-hidden rounded-xl border bg-card">
        <div className="flex items-center gap-3 border-b p-4">
          <div className="rounded-lg bg-primary/10 p-2 text-primary"><Bot className="h-5 w-5" /></div>
          <div><p className="font-medium">Stockwise assistant</p><p className="text-xs text-muted-foreground">Inventory and project material Q&amp;A</p></div>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => { setMessages([]); setConversationId(undefined); chat.reset(); }}><Plus className="mr-1 h-4 w-4" />New chat</Button>
        </div>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4" aria-live="polite">
          {messages.length === 0 && (
            <div className="m-auto max-w-lg py-8 text-center">
              <MessageCircle className="mx-auto mb-3 h-8 w-8 text-primary" />
              <h2 className="mb-2 text-lg font-semibold">What would you like to know?</h2>
              <p className="mb-5 text-sm text-muted-foreground">Ask about project status, remaining allocation, stock, shortage response, or access. Replace PRJ-104 and ELE-001 with real IDs from your data.</p>
              <div className="space-y-5 text-left">
                {SUGGESTION_GROUPS.map((group) => <section key={group.title}><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group.title}</h3><div className="flex flex-wrap gap-2">{group.questions.map((s) => <Button key={s} type="button" variant="outline" size="sm" className="h-auto whitespace-normal py-2 text-left" onClick={() => send(undefined, s)}>{s}</Button>)}</div></section>)}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === "user" ? "ml-auto max-w-[85%] flex-row-reverse" : "max-w-[90%]"}`}>
              <div className="mt-0.5 shrink-0 rounded-full bg-muted p-2">{m.role === "user" ? <UserRound className="h-4 w-4" /> : <Bot className="h-4 w-4" />}</div>
              <div className={`rounded-xl px-4 py-3 text-sm ${m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
                <p className="whitespace-pre-wrap">{m.text}</p>
                {Array.isArray(m.sources) && m.sources.length > 0 && <p className="mt-2 border-t border-border/60 pt-2 text-xs opacity-75">Sources: {m.sources.map((s: any) => typeof s === "string" ? s : pick(s, "label", "name", "table")).filter(Boolean).join(" · ")}</p>}
              </div>
            </div>
          ))}
          {chat.isPending && <p role="status" className="text-sm text-muted-foreground">Checking project and inventory records…</p>}
          {chat.isError && <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{chat.error.message} Check that the assistant API is configured and available.</p>}
        </div>
        <form onSubmit={send} className="flex items-end gap-2 border-t p-3">
          <Textarea value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Ask about inventory or project materials…" rows={2} className="min-h-0 resize-none" aria-label="Your question" />
          <Button type="submit" size="icon" aria-label="Send message" disabled={!question.trim() || chat.isPending}><Send className="h-4 w-4" /></Button>
        </form>
        <p className="px-4 pb-3 text-xs text-muted-foreground">Answers use application records. Verify quantities before purchasing or allocating materials.</p>
      </div>
    </>
  );
}
