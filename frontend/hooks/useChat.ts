"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { v4 as uuid } from "uuid";
import {
  streamQuery,
  streamDirectQuery,
  streamAttachmentQuery,
  streamExplainSource,
  generateChatTitle,
  fetchResetToken,
  compactMessages,
  type AttachmentPayload,
} from "@/lib/api";
import { COMPACT_THRESHOLD, HEALTH_POLL_INTERVAL_MS, HISTORY_TOKEN_BUDGET } from "@/lib/config";
import type { ChatSession, CitedChunk, Message, MessageAttachment, PendingAttachment, QueryMode } from "@/types";

// Conversation history only - retrieved context is not accumulated across turns
function estimateTokens(messages: Message[]): number {
  const textChars = messages.reduce((sum, m) => sum + m.role.length + m.content.length, 0);
  return Math.floor(textChars / 4);
}

// Below this a summary did not summarize, and replacing history on it is data loss
const MIN_SUMMARY_CHARS = 200;
// Capped, because a summary is meant to be far smaller than its input: 100k chars
const MIN_SUMMARY_RATIO = 0.005;
const MAX_REQUIRED_SUMMARY_CHARS = 1000;

function isUsableSummary(summary: string, replaced: Message[]): boolean {
  const text = summary.trim();
  const replacedChars = replaced.reduce((sum, m) => sum + m.content.length, 0);
  const required = Math.max(
    MIN_SUMMARY_CHARS,
    Math.min(replacedChars * MIN_SUMMARY_RATIO, MAX_REQUIRED_SUMMARY_CHARS)
  );
  return text.length >= required;
}

// Folds attachment descriptions into history text - the files are never re-sent
function historyContent(m: Message): string {
  if (!m.attachments || m.attachments.length === 0) return m.content;
  const blocks = m.attachments
    .map((a) => `[Attached ${a.type} '${a.name}': ${a.description}]`)
    .join("\n");
  return `${blocks}\n\n${m.content}`;
}

function toAttachmentPayloads(attachments: PendingAttachment[]): AttachmentPayload[] {
  return attachments.map((a) => ({ type: a.type, name: a.name, file: a.file, text: a.text }));
}

const STORAGE_KEY = "ragbase_sessions";
// Kept out of STORAGE_KEY so clearing history doesn't forget that it was cleared
const RESET_TOKEN_KEY = "ragbase_last_reset_at";

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveSessions(sessions: ChatSession[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isLoadingRef = useRef(false);
  const generationRef = useRef(0);

  // Show stored history at once, then reconcile against reset_all.sh's marker
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const stored = loadSessions();
    setSessions(stored);
    if (stored.length > 0) {
      setActiveSessionId(stored[stored.length - 1].id);
    }

    const checkReset = async () => {
      let resetAt: number | null;
      try {
        resetAt = await fetchResetToken();
      } catch {
        // Retry on useReadiness' cadence rather than deferring to a future page load
        if (!cancelled) timer = setTimeout(checkReset, HEALTH_POLL_INTERVAL_MS);
        return;
      }
      if (cancelled) return;
      // Comparing tokens, not consuming a flag, is what reaches a second tab
      const seen = Number(localStorage.getItem(RESET_TOKEN_KEY) ?? 0);
      if (resetAt !== null && resetAt > seen) {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.setItem(RESET_TOKEN_KEY, String(resetAt));
        // Storage alone isn't enough - a later saveSessions() would rewrite the stale list
        setSessions([]);
        setActiveSessionId(null);
      }
    };

    checkReset();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  const estimatedTokens = useMemo(
    () => (activeSession ? estimateTokens(activeSession.messages) : 0),
    [activeSession]
  );

  const newSession = useCallback(() => {
    const session: ChatSession = {
      id: uuid(),
      title: "New chat",
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setSessions((prev) => {
      const next = [...prev, session];
      saveSessions(next);
      return next;
    });
    setActiveSessionId(session.id);
    return session.id;
  }, []);

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setError(null);
  }, []);

  const renameSession = useCallback((id: string, title: string) => {
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, title } : s));
      saveSessions(next);
      return next;
    });
  }, []);

  const pinSession = useCallback((id: string, pinned: boolean) => {
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, pinned } : s));
      saveSessions(next);
      return next;
    });
  }, []);

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const sendMessage = useCallback(
    async (
      content: string,
      sourceFilter: string[] | null = null,
      isDirect: boolean = false,
      attachments: PendingAttachment[] = [],
      // Set by explainSource() - the request then carries only this name
      explainSourceName?: string
    ) => {
      if (isLoadingRef.current) {
        // Let the aborted fetch tear down, or the reader throws "Error in input stream"
        abortRef.current?.abort();
        await new Promise((resolve) => setTimeout(resolve, 100));
        isLoadingRef.current = false;
      }
      const gen = ++generationRef.current;
      let sessionId = activeSessionId;
      let currentSessions = sessions;

      if (!sessionId) {
        const session: ChatSession = {
          id: uuid(),
          title: content.slice(0, 40) || "New chat",
          messages: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        currentSessions = [...sessions, session];
        setSessions(currentSessions);
        saveSessions(currentSessions);
        setActiveSessionId(session.id);
        sessionId = session.id;
      }

      // Auto-compact if the session is approaching the context limit
      const sessionForCompact = currentSessions.find((s) => s.id === sessionId);
      if (
        sessionForCompact &&
        sessionForCompact.messages.length > 10 &&
        estimateTokens(sessionForCompact.messages) >= HISTORY_TOKEN_BUDGET * COMPACT_THRESHOLD
      ) {
        const toCompact = sessionForCompact.messages.slice(0, -10);
        const kept = sessionForCompact.messages.slice(-10);
        try {
          const summaryText = await compactMessages(
            toCompact.map((m) => ({ role: m.role, content: historyContent(m) }))
          );
          if (!isUsableSummary(summaryText, toCompact)) {
            // saveSessions writes localStorage, so the originals exist nowhere else
            console.warn(
              `Compaction returned an unusable summary (${summaryText.trim().length} chars) - keeping history`
            );
            setToast("Could not compact the conversation - history kept");
            setTimeout(() => setToast(null), 4000);
          } else {
            const summaryMsg: Message = {
              id: uuid(),
              role: "system",
              content: summaryText,
              type: "summary",
              timestamp: Date.now(),
              isComplete: true,
            };
            const compacted = [summaryMsg, ...kept];
            currentSessions = currentSessions.map((s) =>
              s.id === sessionId ? { ...s, messages: compacted } : s
            );
            setSessions(currentSessions);
            saveSessions(currentSessions);
            setToast("Conversation compacted to save context space");
            setTimeout(() => setToast(null), 4000);
          }
        } catch (err) {
          console.warn("Compaction failed - keeping history", err);
        }
      }

      // Optimistic so chips render now - `description` arrives with [ATTACHMENTS]
      const optimisticAttachments: MessageAttachment[] | undefined =
        attachments.length > 0
          ? attachments.map((a) => ({
              type: a.type,
              name: a.name,
              description: "",
              previewUrl: a.previewUrl,
            }))
          : undefined;

      const userMessage: Message = {
        id: uuid(),
        role: "user",
        content,
        timestamp: Date.now(),
        attachments: optimisticAttachments,
      };

      const historySession = currentSessions.find((s) => s.id === sessionId);
      const isFirstMessage = (historySession?.messages ?? []).length === 0;
      const history = (historySession?.messages ?? []).map((m) => ({
        role: m.role,
        content: historyContent(m),
      }));

      const assistantId = uuid();
      const mode: QueryMode = isDirect ? "direct" : "rag";

      setSessions((prev) => {
        const next = prev.map((s) => {
          if (s.id !== sessionId) return s;
          return {
            ...s,
            messages: [
              ...s.messages,
              userMessage,
              { id: assistantId, role: "assistant" as const, content: "", timestamp: Date.now(), mode },
            ],
            title:
              s.messages.length === 0 ? content.slice(0, 40) || s.title : s.title,
            updatedAt: Date.now(),
          };
        });
        saveSessions(next);
        return next;
      });

      // Fire-and-forget: replace truncated title with an LLM-generated one
      if (isFirstMessage) {
        const sid = sessionId;
        generateChatTitle(content)
          .then((title) => {
            if (!title) return;
            setSessions((prev) => {
              const next = prev.map((s) => (s.id === sid ? { ...s, title } : s));
              saveSessions(next);
              return next;
            });
          })
          // The truncated first message stays as the title - log why the real one is missing
          .catch((err) => console.warn("Chat title generation failed", err));
      }

      setIsLoading(true);
      isLoadingRef.current = true;
      setIsStreaming(false);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      let assistantContent = "";
      let assistantSources: string[] = [];
      let assistantScores: number[] = [];
      let assistantChunks: CitedChunk[] = [];
      let sawFirstToken = false;
      // Two deltas on two clocks, added, never subtracted from each other
      let serverMs: number | null = null;

      const handlers = {
        onStage: (stage: string) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== sessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantId ? { ...m, stage } : m
                ),
              };
            })
          );
        },
        onToken: (token: string) => {
          if (!sawFirstToken) {
            sawFirstToken = true;
            setIsStreaming(true);
          }
          assistantContent += token;
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== sessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: assistantContent }
                    : m
                ),
              };
            })
          );
        },
        onSources: (sources: string[], scores: number[], chunks: CitedChunk[]) => {
          assistantSources = sources;
          assistantScores = scores;
          assistantChunks = chunks;
        },
        onAttachments: (results: { type: string; name: string; description: string }[]) => {
          // Onto the user message, and relies on the backend keeping the sent order
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== sessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === userMessage.id
                    ? {
                        ...m,
                        attachments: m.attachments?.map((a, i) => ({
                          ...a,
                          description: results[i]?.description ?? a.description,
                        })),
                      }
                    : m
                ),
              };
            })
          );
        },
        onTiming: (ms: number) => {
          serverMs = ms;
        },
        onDone: () => {
          const doneAt = performance.now();
          setSessions((prev) => {
            const next = prev.map((s) => {
              if (s.id !== sessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantId
                    ? {
                        ...m,
                        content: assistantContent,
                        sources: assistantSources,
                        scores: assistantScores,
                        chunks: assistantChunks,
                        mode,
                        stage: undefined,
                        isComplete: true,
                      }
                    : m
                ),
                updatedAt: Date.now(),
              };
            });
            saveSessions(next);
            return next;
          });

          // Two nested rAFs - the first fires before the paint, the second after it
          if (serverMs === null) return;
          const settledServerMs = serverMs;
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              const latencyMs = Math.round(
                settledServerMs + (performance.now() - doneAt)
              );
              setSessions((prev) => {
                const next = prev.map((s) => {
                  if (s.id !== sessionId) return s;
                  return {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === assistantId ? { ...m, latencyMs } : m
                    ),
                  };
                });
                saveSessions(next);
                return next;
              });
            });
          });
        },
      };

      try {
        if (explainSourceName) {
          await streamExplainSource(explainSourceName, handlers, controller.signal);
        } else if (attachments.length > 0) {
          await streamAttachmentQuery(
            content,
            history,
            sourceFilter,
            isDirect,
            toAttachmentPayloads(attachments),
            handlers,
            controller.signal
          );
        } else if (isDirect) {
          await streamDirectQuery(content, history, handlers, controller.signal);
        } else {
          await streamQuery(content, history, sourceFilter, handlers, controller.signal);
        }
      } catch (err) {
        // Abort is intentional - keep whatever content was streamed
        if ((err as { name?: string }).name === "AbortError") {
          handlers.onDone();
          // Stays on the message permanently - this response was cut short
          setSessions((prev) => {
            const next = prev.map((s) => {
              if (s.id !== sessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantId ? { ...m, stage: "stopped" } : m
                ),
              };
            });
            saveSessions(next);
            return next;
          });
          return;
        }
        setError(err instanceof Error ? err.message : "Request failed");
        setSessions((prev) => {
          const next = prev.map((s) => {
            if (s.id !== sessionId) return s;
            return {
              ...s,
              messages: s.messages.filter((m) => m.id !== assistantId || m.content),
            };
          });
          saveSessions(next);
          return next;
        });
      } finally {
        if (generationRef.current === gen) {
          setIsLoading(false);
          isLoadingRef.current = false;
          setIsStreaming(false);
          abortRef.current = null;
        }
      }
    },
    [activeSessionId, sessions]
  );

  /**
   * Ask for a whole-source explanation, as though the user had typed it.
   *
   * Goes through sendMessage because only the endpoint differs; the displayed
   * text and the `[source]` filter are never sent.
   */
  const explainSource = useCallback(
    (source: string) => sendMessage(`Explain "${source}" in depth`, [source], false, [], source),
    [sendMessage]
  );

  const deleteSession = useCallback((id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      saveSessions(next);
      return next;
    });
    setActiveSessionId((current) => {
      if (current !== id) return current;
      const remaining = sessions.filter((s) => s.id !== id);
      return remaining.length > 0 ? remaining[remaining.length - 1].id : null;
    });
  }, [sessions]);

  return {
    sessions,
    activeSession,
    activeSessionId,
    isLoading,
    isStreaming,
    error,
    toast,
    estimatedTokens,
    newSession,
    selectSession,
    sendMessage,
    explainSource,
    stopGeneration,
    renameSession,
    pinSession,
    deleteSession,
  };
}
