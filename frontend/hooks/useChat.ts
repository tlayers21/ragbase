"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { v4 as uuid } from "uuid";
import {
  streamQuery,
  streamDirectQuery,
  streamAttachmentQuery,
  generateChatTitle,
  shouldResetSessions,
  compactMessages,
  type AttachmentPayload,
} from "@/lib/api";
import type { ChatSession, CitedChunk, Message, MessageAttachment, PendingAttachment, QueryMode } from "@/types";

const TOKEN_LIMIT = 40960;
const COMPACT_THRESHOLD = 0.9;
const RAG_TOKENS_PER_EXCHANGE = 1500;

function estimateTokens(messages: Message[]): number {
  const textChars = messages.reduce((sum, m) => sum + m.role.length + m.content.length, 0);
  const exchangeCount = Math.ceil(messages.length / 2);
  return Math.floor(textChars / 4) + exchangeCount * RAG_TOKENS_PER_EXCHANGE;
}

// Folds a past message's attachment descriptions into its history content so
// follow-up questions retain attachment context — descriptions only exist on
// the frontend's Message objects, never re-sent as files on later turns.
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

/**
 * @param isIngestionBusy Read at send time and again at [DONE] to record whether
 *   the answer was competing with the ingestion queue. A getter rather than a
 *   boolean because `sendMessage` closes over its arguments, and a job that
 *   starts or finishes mid-stream would otherwise be invisible.
 */
export function useChat(isIngestionBusy?: () => boolean) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isLoadingRef = useRef(false);
  const generationRef = useRef(0);
  // Held in a ref so a caller passing an inline getter can't rebuild sendMessage
  // — and with it every handler the chat tree hangs off — on every render.
  const isIngestionBusyRef = useRef(isIngestionBusy);
  useEffect(() => {
    isIngestionBusyRef.current = isIngestionBusy;
  }, [isIngestionBusy]);

  useEffect(() => {
    shouldResetSessions().then((reset) => {
      if (reset) {
        localStorage.removeItem(STORAGE_KEY);
      }
      const stored = loadSessions();
      setSessions(stored);
      if (stored.length > 0) {
        setActiveSessionId(stored[stored.length - 1].id);
      }
    });
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
      attachments: PendingAttachment[] = []
    ) => {
      if (isLoadingRef.current) {
        // A previous stream is still open — abort it and give the fetch a
        // moment to actually tear down before opening a new one, or the
        // in-flight reader can throw "Error in input stream".
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
        estimateTokens(sessionForCompact.messages) >= TOKEN_LIMIT * COMPACT_THRESHOLD
      ) {
        const toCompact = sessionForCompact.messages.slice(0, -10);
        const kept = sessionForCompact.messages.slice(-10);
        try {
          const summaryText = await compactMessages(
            toCompact.map((m) => ({ role: m.role, content: m.content }))
          );
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
        } catch {
          // Non-blocking — continue without compaction if it fails
        }
      }

      // Optimistic attachment metadata so chips render immediately; `description`
      // is filled in once the backend's [ATTACHMENTS] event arrives mid-stream.
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
        generateChatTitle(content).then((title) => {
          if (!title) return;
          setSessions((prev) => {
            const next = prev.map((s) => (s.id === sid ? { ...s, title } : s));
            saveSessions(next);
            return next;
          });
        });
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
      let firstTokenTime: number | null = null;
      // Sampled here and again at [DONE]: a job that starts or drains mid-stream
      // still shared the GPU with this answer, and either end alone would miss it.
      let ingestionActive = isIngestionBusyRef.current?.() ?? false;

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
          if (firstTokenTime === null) {
            firstTokenTime = Date.now();
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
          // Patches descriptions onto the USER message (not the assistant reply) —
          // relies on the backend processing attachments in the same order sent.
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
        onDone: () => {
          const latencyMs =
            firstTokenTime !== null ? Date.now() - firstTokenTime : undefined;
          ingestionActive = ingestionActive || (isIngestionBusyRef.current?.() ?? false);
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
                        latencyMs,
                        ingestionActive,
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
        },
      };

      try {
        if (attachments.length > 0) {
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
        // Abort is intentional — keep whatever content was streamed
        if ((err as { name?: string }).name === "AbortError") {
          handlers.onDone();
          // "Stopped." stays on the message permanently so the user always
          // knows this response was cut short mid-generation.
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
    stopGeneration,
    renameSession,
    pinSession,
    deleteSession,
  };
}
