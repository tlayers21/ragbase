"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { v4 as uuid } from "uuid";
import { streamQuery, streamDirectQuery, generateChatTitle, shouldResetSessions, compactMessages } from "@/lib/api";
import { getUserId } from "@/lib/api";
import type { ChatSession, CitedChunk, Message, QueryMode } from "@/types";

const TOKEN_LIMIT = 40960;
const COMPACT_THRESHOLD = 0.9;
const RAG_TOKENS_PER_EXCHANGE = 1500;

function estimateTokens(messages: Message[]): number {
  const textChars = messages.reduce((sum, m) => sum + m.role.length + m.content.length, 0);
  const exchangeCount = Math.ceil(messages.length / 2);
  return Math.floor(textChars / 4) + exchangeCount * RAG_TOKENS_PER_EXCHANGE;
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
      isDirect: boolean = false
    ) => {
      if (isLoadingRef.current) {
        abortRef.current?.abort();
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
            toCompact.map((m) => ({ role: m.role, content: m.content })),
            getUserId()
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

      const userMessage: Message = {
        id: uuid(),
        role: "user",
        content,
        timestamp: Date.now(),
      };

      const historySession = currentSessions.find((s) => s.id === sessionId);
      const isFirstMessage = (historySession?.messages ?? []).length === 0;
      const history = (historySession?.messages ?? []).map((m) => ({
        role: m.role,
        content: m.content,
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
        onDone: () => {
          const latencyMs =
            firstTokenTime !== null ? Date.now() - firstTokenTime : undefined;
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
        if (isDirect) {
          await streamDirectQuery(content, history, handlers, controller.signal);
        } else {
          await streamQuery(content, history, sourceFilter, handlers, controller.signal);
        }
      } catch (err) {
        // Abort is intentional — keep whatever content was streamed
        if ((err as { name?: string }).name === "AbortError") {
          handlers.onDone();
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
