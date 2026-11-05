"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Database, MessageSquarePlus, Send, Trash2, User, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { EmptyState, ErrorState } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge, Textarea } from "@/components/ui/primitives";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { ChatMessage } from "@/types/api";

const SUGGESTIONS = [
  "What is happening in the market?",
  "Explain the current BTC trend",
  "Analyze ETH's technical indicators",
  "Compare BTC vs SOL",
  "Why was the latest BTC signal generated?",
  "Summarize recent SOL movements",
  "How is my portfolio doing?",
];

const TOOL_LABELS: Record<string, string> = {
  get_market_overview: "Market overview",
  get_asset_analysis: "Technical analysis",
  compare_assets: "Asset comparison",
  get_latest_signal: "Latest signal",
  get_recent_movements: "Price movements",
  get_portfolio: "Paper portfolio",
  list_backtests: "Backtests",
};

function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-chat text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h3: (p) => <h3 className="mt-3 mb-1.5 text-sm font-semibold first:mt-0" {...p} />,
          p: (p) => <p className="my-1.5" {...p} />,
          ul: (p) => <ul className="my-1.5 list-disc space-y-1 pl-5" {...p} />,
          ol: (p) => <ol className="my-1.5 list-decimal space-y-1 pl-5" {...p} />,
          hr: () => <hr className="my-3 border-border" />,
          a: ({ href, ...p }) => <a href={href} className="text-primary underline" target="_blank" rel="noreferrer noopener" {...p} />,
          table: (p) => (
            <div className="my-2 overflow-x-auto rounded-md border border-border scrollbar-thin">
              <table className="w-full text-xs tabular" {...p} />
            </div>
          ),
          th: (p) => <th className="border-b border-border bg-muted/50 px-2.5 py-1.5 text-left font-medium" {...p} />,
          td: (p) => <td className="border-b border-border/50 px-2.5 py-1.5" {...p} />,
          code: (p) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

function MessageBubble({ m }: { m: Pick<ChatMessage, "role" | "content" | "meta"> & { pending?: boolean } }) {
  const isUser = m.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", isUser ? "bg-secondary" : "bg-primary/15 text-primary")}>
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </span>
      <div className={cn("max-w-[85%] min-w-0 rounded-xl px-4 py-3", isUser ? "bg-secondary" : "border border-border bg-card")}>
        {m.pending ? (
          <span className="flex gap-1 py-1">
            {[0, 1, 2].map((i) => <span key={i} className="size-1.5 animate-bounce rounded-full bg-muted-foreground" style={{ animationDelay: `${i * 120}ms` }} />)}
          </span>
        ) : isUser ? (
          <p className="text-sm whitespace-pre-wrap">{m.content}</p>
        ) : (
          <Markdown>{m.content}</Markdown>
        )}
        {!isUser && !m.pending && (m.meta.tools?.length || m.meta.sources?.length) ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
            <Badge variant="outline">{m.meta.engine?.startsWith("openai") ? m.meta.engine.replace("openai:", "AI · ") : "Rule-based engine"}</Badge>
            {[...new Set(m.meta.tools ?? [])].map((t) => (
              <Badge key={t} variant="secondary"><Wrench /> {TOOL_LABELS[t] ?? t}</Badge>
            ))}
            {m.meta.sources?.map((s) => (
              <span key={s} className="flex items-center gap-1 text-[10px] text-muted-foreground"><Database className="size-3" /> {s}</span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function AssistantView() {
  const qc = useQueryClient();
  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.assistant.conversations });
  const conversation = useQuery({ queryKey: ["conversation", activeId], queryFn: () => api.assistant.conversation(activeId!), enabled: !!activeId });

  const send = useMutation({
    mutationFn: (message: string) => api.assistant.chat(message, activeId),
    onMutate: (message) => setPendingQuestion(message),
    onSuccess: (res) => {
      setActiveId(res.conversation_id);
      qc.invalidateQueries({ queryKey: ["conversation", res.conversation_id] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e: Error, message) => {
      toast.error(e.message);
      setInput(message);
    },
    onSettled: () => setPendingQuestion(null),
  });
  const remove = useMutation({
    mutationFn: api.assistant.remove,
    onSuccess: (_, id) => {
      if (id === activeId) setActiveId(null);
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const messages = activeId ? (conversation.data?.messages ?? []) : [];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, pendingQuestion]);

  const submit = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || send.isPending) return;
    setInput("");
    send.mutate(msg);
  };

  return (
    <>
      <PageHeader title="AI Research Assistant" description="Ask about markets, signals, your paper portfolio or backtests. Answers are grounded in live platform data." />
      <div className="grid h-[calc(100dvh-13rem)] min-h-[520px] gap-4 lg:grid-cols-[260px_1fr]">
        <Card className="hidden flex-col overflow-hidden lg:flex">
          <div className="border-b border-border p-3">
            <Button variant="outline" size="sm" className="w-full" onClick={() => setActiveId(null)}>
              <MessageSquarePlus /> New conversation
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 scrollbar-thin">
            {conversations.data?.length ? (
              conversations.data.map((c) => (
                <div key={c.id} className={cn("group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm", c.id === activeId ? "bg-accent" : "hover:bg-accent/60")}>
                  <button className="min-w-0 flex-1 text-left" onClick={() => setActiveId(c.id)}>
                    <p className="truncate">{c.title}</p>
                    <p className="text-[10px] text-muted-foreground">{timeAgo(c.updated_at)}</p>
                  </button>
                  <button aria-label="Delete conversation" className="opacity-0 transition-opacity group-hover:opacity-100" onClick={() => remove.mutate(c.id)}>
                    <Trash2 className="size-3.5 text-muted-foreground hover:text-loss" />
                  </button>
                </div>
              ))
            ) : (
              <p className="px-2 py-4 text-xs text-muted-foreground">No conversations yet.</p>
            )}
          </div>
        </Card>

        <Card className="flex min-h-0 flex-col overflow-hidden">
          <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto p-4 scrollbar-thin sm:p-6">
            {activeId && conversation.error ? (
              <ErrorState error={conversation.error} onRetry={() => conversation.refetch()} />
            ) : messages.length === 0 && !pendingQuestion ? (
              <EmptyState
                icon={Bot}
                title="How can I help with your research?"
                description="I use real application data — live prices, computed indicators, stored signals and your simulated portfolio — and will tell you when something is unavailable."
                action={
                  <div className="mt-2 flex max-w-xl flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} onClick={() => submit(s)} className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground">
                        {s}
                      </button>
                    ))}
                  </div>
                }
                className="h-full"
              />
            ) : (
              <>
                {messages.map((m) => <MessageBubble key={m.id} m={m} />)}
                {pendingQuestion && (
                  <>
                    <MessageBubble m={{ role: "user", content: pendingQuestion, meta: {} }} />
                    <MessageBubble m={{ role: "assistant", content: "", meta: {}, pending: true }} />
                  </>
                )}
              </>
            )}
          </div>
          <div className="border-t border-border p-3">
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                rows={1}
                maxLength={4000}
                placeholder="Ask about an asset, a signal, or your portfolio…"
                className="max-h-40 min-h-10 resize-none"
                aria-label="Message"
              />
              <Button type="submit" size="icon" disabled={!input.trim()} loading={send.isPending} aria-label="Send">
                {!send.isPending && <Send />}
              </Button>
            </form>
            <p className="mt-1.5 text-[10px] text-muted-foreground">Research assistant — outputs are estimates and not financial advice.</p>
          </div>
        </Card>
      </div>
    </>
  );
}
