"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, Brain, FileText, Loader, RotateCcw, Send, Square, Upload } from "lucide-react";
import styles from "./chat.module.css";

interface Source {
  index: number;
  documentId: string;
  title: string;
  excerpt: string;
  score: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: string;
  pending?: boolean;
  context?: ContextInfo;
  timing?: { firstWordMs?: number; totalMs?: number };
}

interface ContextInfo {
  documentsSearched: number | null;
  passagesSearched: number | null;
  passagesUsed: number;
  documentsUsed: number;
  retrievalMs: number | null;
  contextMs: number;
  weakMatch?: boolean;
}

function seconds(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** "Searched 72 documents (512 passages) → used 8 passages from 5 documents · …" */
function ContextLine({ context, timing }: { context: ContextInfo; timing?: Message["timing"] }) {
  const parts: string[] = [];
  if (context.retrievalMs !== null) parts.push(`search ${seconds(context.retrievalMs)}`);
  if (timing?.firstWordMs !== undefined) parts.push(`first word ${seconds(timing.firstWordMs)}`);
  if (timing?.totalMs !== undefined) parts.push(`full answer ${seconds(timing.totalMs)}`);
  return (
    <div className={styles.contextLine}>
      {context.documentsSearched !== null && (
        <span>
          Searched <strong>{context.documentsSearched}</strong> documents
          {context.passagesSearched !== null && <> ({context.passagesSearched} passages)</>} →{" "}
        </span>
      )}
      <span>
        used <strong>{context.passagesUsed}</strong> passage{context.passagesUsed === 1 ? "" : "s"} from{" "}
        <strong>{context.documentsUsed}</strong> document{context.documentsUsed === 1 ? "" : "s"}
      </span>
      {context.weakMatch && <span className={styles.contextWeak}> · no close match, nearest passages used</span>}
      {parts.length > 0 && <span className={styles.contextTiming}> · {parts.join(" · ")}</span>}
    </div>
  );
}

const SUGGESTIONS = [
  "What topics do our documents cover?",
  "Summarize the key points of our latest report",
  "Which documents mention deadlines or due dates?",
];

const STORAGE_PREFIX = "veda-chat:";

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Turn [1] / [2][3] citations into links the markdown renderer can style. */
function linkCitations(text: string, messageId: string, maxIndex: number): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, (match, n) => {
    const index = Number(n);
    return index >= 1 && index <= maxIndex ? `[${index}](#cite-${messageId}-${index})` : match;
  });
}

function AssistantMessage({
  message,
  onCite,
  highlighted,
}: {
  message: Message;
  onCite: (messageId: string, index: number) => void;
  highlighted: string | null;
}) {
  const sources = message.sources ?? [];
  const text = linkCitations(message.content, message.id, sources.length);

  return (
    <div className={styles.assistantRow}>
      <div className={styles.avatar} aria-hidden="true">
        <Brain size={15} />
      </div>
      <div className={styles.assistantBody}>
        {message.pending && !message.content ? (
          <span className={styles.thinking}>
            <Loader size={14} className="animate-spin" /> Searching your company&apos;s data…
          </span>
        ) : (
          <div className={styles.answer}>
            <ReactMarkdown
              components={{
                a: ({ href, children }) => {
                  const match = href?.match(/^#cite-(.+)-(\d+)$/);
                  if (!match) {
                    return (
                      <a href={href} target="_blank" rel="noreferrer">
                        {children}
                      </a>
                    );
                  }
                  const index = Number(match[2]);
                  return (
                    <button
                      type="button"
                      className={styles.citation}
                      onClick={() => onCite(message.id, index)}
                      title={sources[index - 1]?.title}
                    >
                      {index}
                    </button>
                  );
                },
              }}
            >
              {text}
            </ReactMarkdown>
            {message.pending && <span className={styles.cursor} aria-hidden="true" />}
          </div>
        )}

        {message.error && <div className={styles.errorText}>{message.error}</div>}

        {message.context && !message.pending && (
          <ContextLine context={message.context} timing={message.timing} />
        )}

        {sources.length > 0 && !message.pending && (
          <div className={styles.sources}>
            <span className={styles.sourcesLabel}>Sources ({sources.length})</span>
            {sources.map((source) => {
              const key = `${message.id}-${source.index}`;
              return (
                <details
                  key={key}
                  id={`source-${key}`}
                  className={`${styles.source} ${highlighted === key ? styles.highlight : ""}`}
                >
                  <summary>
                    <span className={styles.sourceIndex}>{source.index}</span>
                    <FileText size={12} />
                    <span className={styles.sourceTitle}>{source.title}</span>
                  </summary>
                  <p className={styles.excerpt}>{source.excerpt}</p>
                </details>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const router = useRouter();
  const [company, setCompany] = useState<{ slug: string; tenantId: string } | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const storageKey = company ? `${STORAGE_PREFIX}${company.tenantId}` : null;

  useEffect(() => {
    fetch("/api/auth/session")
      .then((res) => res.json())
      .then((data) => {
        if (!data.authenticated) router.push("/login");
        else setCompany({ slug: data.session.tenantSlug, tenantId: data.session.tenantId });
      })
      .catch(() => router.push("/login"));
  }, [router]);

  // Restore this company's conversation for the browser tab
  useEffect(() => {
    if (!storageKey) return;
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved) setMessages(JSON.parse(saved));
    } catch {
      // storage unavailable — start fresh
    }
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || streaming) return;
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {
      // storage unavailable — not critical
    }
  }, [messages, storageKey, streaming]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const updateMessage = (id: string, patch: (m: Message) => Partial<Message>) =>
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)));

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || streaming) return;

      const history = messages
        .filter((m) => !m.error && !m.pending && m.content)
        .map((m) => ({ role: m.role, content: m.content }));
      const userMessage: Message = { id: newId(), role: "user", content: question };
      const assistantId = newId();
      setMessages((all) => [
        ...all,
        userMessage,
        { id: assistantId, role: "assistant", content: "", pending: true },
      ]);
      setInput("");
      setStreaming(true);

      const controller = new AbortController();
      const askedAt = performance.now();
      let firstWordMs: number | undefined;
      abortRef.current = controller;

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: question, history }),
          signal: controller.signal,
        });

        if (res.status === 401) {
          router.push("/login");
          return;
        }
        if (!res.ok || !res.body) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || `Request failed (${res.status})`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "context") {
              const { type: _type, ...context } = event;
              updateMessage(assistantId, () => ({ context }));
            } else if (event.type === "sources") {
              updateMessage(assistantId, () => ({ sources: event.sources }));
            } else if (event.type === "token") {
              if (firstWordMs === undefined) firstWordMs = performance.now() - askedAt;
              updateMessage(assistantId, (m) => ({ content: m.content + event.text }));
            } else if (event.type === "error") {
              updateMessage(assistantId, () => ({ error: event.message }));
            }
          }
        }
      } catch (error) {
        if (controller.signal.aborted) {
          updateMessage(assistantId, (m) => ({ content: m.content || "_Stopped._" }));
        } else {
          updateMessage(assistantId, () => ({
            error: error instanceof Error ? error.message : "Something went wrong",
          }));
        }
      } finally {
        const totalMs = performance.now() - askedAt;
        updateMessage(assistantId, () => ({ pending: false, timing: { firstWordMs, totalMs } }));
        setStreaming(false);
        abortRef.current = null;
        textareaRef.current?.focus();
      }
    },
    [messages, router, streaming]
  );

  const handleCite = (messageId: string, index: number) => {
    const key = `${messageId}-${index}`;
    const element = document.getElementById(`source-${key}`) as HTMLDetailsElement | null;
    if (element) {
      element.open = true;
      element.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    setHighlighted(key);
    setTimeout(() => setHighlighted((current) => (current === key ? null : current)), 2000);
  };

  const clearChat = () => {
    abortRef.current?.abort();
    setMessages([]);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Link href="/dashboard" className={styles.navLink}>
            <ArrowLeft size={16} /> Dashboard
          </Link>
          <Link href="/upload" className={styles.navLink}>
            <Upload size={14} /> Data Uploads
          </Link>
          {messages.length > 0 && (
            <button type="button" className={styles.navLink} onClick={clearChat}>
              <RotateCcw size={14} /> New chat
            </button>
          )}
        </div>
        {company && (
          <span className={styles.company}>
            Company: <strong>{company.slug}</strong>
          </span>
        )}
      </header>

      <div className={styles.scroll}>
        <div className={styles.thread}>
          {messages.length === 0 ? (
            <div className={styles.empty}>
              <div className={styles.emptyIcon}>
                <Brain size={24} />
              </div>
              <h1>Ask your company&apos;s data</h1>
              <p>
                Answers come only from documents and data your company uploaded, with the sources
                cited so you can check them.
              </p>
              <div className={styles.suggestions}>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={styles.suggestion}
                    onClick={() => send(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) =>
              message.role === "user" ? (
                <div key={message.id} className={styles.userRow}>
                  <div className={styles.userBubble}>{message.content}</div>
                </div>
              ) : (
                <AssistantMessage
                  key={message.id}
                  message={message}
                  onCite={handleCite}
                  highlighted={highlighted}
                />
              )
            )
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className={styles.composerWrap}>
        <form
          className={styles.composer}
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <div className={styles.inputRow}>
            <textarea
              ref={textareaRef}
              className={styles.textarea}
              rows={1}
              placeholder="Ask a question about your company's documents…"
              value={input}
              maxLength={4000}
              aria-label="Your question"
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${e.target.scrollHeight}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
            />
            {streaming ? (
              <button
                type="button"
                className={`${styles.sendButton} ${styles.stopButton}`}
                onClick={() => abortRef.current?.abort()}
              >
                <Square size={12} /> Stop
              </button>
            ) : (
              <button type="submit" className={styles.sendButton} disabled={!input.trim()}>
                <Send size={14} /> Send
              </button>
            )}
          </div>
          <div className={styles.hint}>
            Enter to send · Shift+Enter for a new line · Answers can be wrong — check the sources
          </div>
        </form>
      </div>
    </div>
  );
}
