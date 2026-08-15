"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Sidebar, SidebarToggle } from "@/components/layout/Sidebar";
import { ChatArea } from "@/components/chat/ChatArea";
import { SourcesPanel, SourcesPanelToggle } from "@/components/layout/SourcesPanel";
import { SourcesModal } from "@/components/sources/SourcesModal";
import { WarmupGate } from "@/components/layout/WarmupGate";
import { useChat } from "@/hooks/useChat";
import { useReadiness } from "@/hooks/useReadiness";
import { useSources } from "@/hooks/useSources";
import { useIngestion } from "@/hooks/useIngestion";
import type { PendingAttachment } from "@/types";

export default function HomePage() {
  // useChat needs to know whether ingestion is running, but useIngestion is
  // declared below it (and depends on useSources). A ref threaded through as a
  // getter breaks that cycle without reordering the hooks — see useChat.
  const ingestionBusyRef = useRef(false);
  const isIngestionBusy = useCallback(() => ingestionBusyRef.current, []);

  const chat = useChat(isIngestionBusy);
  const { sources, refresh: refreshSources } = useSources();
  const readiness = useReadiness();

  const { toast: chatToast, estimatedTokens } = chat;

  const {
    jobs,
    ingestingJobs,
    activeJobCount,
    clearableJobCount,
    fadingJobIds,
    hiddenJobIds,
    isUploading,
    uploadFile,
    ingestText,
    ingestUrl,
    cancelJob,
    clearCompleted,
  } = useIngestion(refreshSources);

  const isIngesting = ingestingJobs.length > 0;
  useEffect(() => {
    ingestionBusyRef.current = isIngesting;
  }, [isIngesting]);

  // Sources whose knowledge graph is still being built
  const buildingGraphSources = useMemo(
    () =>
      new Set(
        jobs
          .filter((j) => j.status === "ingested" || j.status === "building_graph")
          .map((j) => j.source)
      ),
    [jobs]
  );

  // Map source name -> job id for sources actively building their graph
  const buildingGraphJobBySrc = useMemo(
    () =>
      Object.fromEntries(
        jobs
          .filter((j) => j.status === "building_graph")
          .map((j) => [j.source, j.id])
      ),
    [jobs]
  );

  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isSourcesModalOpen, setIsSourcesModalOpen] = useState(false);
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());

  // All sources are selected by default. New sources auto-join the selection;
  // deleted sources are dropped from it. Existing user deselections persist.
  // The ref mutation must happen outside the setSelectedSources updater to
  // avoid issues with React Strict Mode's double-invocation of updaters.
  const knownSourceNamesRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const currentNames = new Set(sources.map((s) => s.source));
    const added = [...currentNames].filter((n) => !knownSourceNamesRef.current.has(n));
    const removed = [...knownSourceNamesRef.current].filter((n) => !currentNames.has(n));
    knownSourceNamesRef.current = currentNames;

    if (added.length === 0 && removed.length === 0) return;

    setSelectedSources((prev) => {
      const next = new Set(prev);
      for (const name of added) next.add(name);
      for (const name of removed) next.delete(name);
      return next;
    });
  }, [sources]);

  const toggleSource = useCallback((source: string) => {
    setSelectedSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) {
        next.delete(source);
      } else {
        next.add(source);
      }
      return next;
    });
  }, []);

  const selectAllSources = useCallback(() => {
    setSelectedSources(new Set(sources.map((s) => s.source)));
  }, [sources]);

  const clearAllSources = useCallback(() => {
    setSelectedSources(new Set());
  }, []);

  // Refresh source list whenever a job transitions to "ingested" or "done"
  // so those sources appear in the SourceFilter immediately.
  const prevJobStatusesRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    let needsRefresh = false;
    for (const job of jobs) {
      const prev = prevJobStatusesRef.current.get(job.id);
      if (prev !== job.status && (job.status === "ingested" || job.status === "building_graph" || job.status === "done")) {
        needsRefresh = true;
      }
      prevJobStatusesRef.current.set(job.id, job.status);
    }
    if (needsRefresh) refreshSources();
  }, [jobs, refreshSources]);

  const isDirectMode = selectedSources.size === 0;

  const handleSend = useCallback(
    (content: string, attachments: PendingAttachment[]) => {
      const filter =
        !isDirectMode && sources.length > 0 && selectedSources.size < sources.length
          ? Array.from(selectedSources)
          : null;
      chat.sendMessage(content, filter, isDirectMode, attachments);
    },
    [chat, selectedSources, sources, isDirectMode]
  );

  const handleDropFiles = useCallback(
    async (files: File[], describeImages = false) => {
      for (const file of files) {
        await uploadFile(file, describeImages);
      }
    },
    [uploadFile]
  );

  // Cover the app until the backend's models are loaded — see WarmupGate.
  const showWarmupGate = readiness.checked && !readiness.ready && !readiness.dismissed;

  return (
    <>
      {showWarmupGate && (
        <WarmupGate
          status={readiness.status}
          error={readiness.error}
          onDismiss={readiness.dismiss}
        />
      )}

      {/* `inert` matters as much as the overlay: the cover blocks clicks, but the
          chat textarea stays tabbable behind it, and Enter would fire a query at a
          backend that is still loading. */}
      <div className="flex h-full w-full overflow-hidden" inert={showWarmupGate}>
        {/* Left sidebar */}
        {isSidebarCollapsed ? (
          <SidebarToggle onClick={() => setIsSidebarCollapsed(false)} />
        ) : (
          <Sidebar
            sessions={chat.sessions}
            activeSessionId={chat.activeSessionId}
            estimatedTokens={estimatedTokens}
            onNewSession={chat.newSession}
            onSelectSession={chat.selectSession}
            onDeleteSession={chat.deleteSession}
            onRenameSession={chat.renameSession}
            onPinSession={chat.pinSession}
            onToggleCollapse={() => setIsSidebarCollapsed(true)}
          />
        )}

        {/* Center — chat */}
        <main className="flex flex-1 flex-col overflow-hidden min-w-0 bg-background">
          <ChatArea
            session={chat.activeSession}
            isLoading={chat.isLoading}
            isStreaming={chat.isStreaming}
            error={chat.error}
            sources={sources}
            selectedSources={selectedSources}
            buildingGraphSources={buildingGraphSources}
            ingestingJobs={ingestingJobs}
            onToggleSource={toggleSource}
            onSelectAllSources={selectAllSources}
            onClearAllSources={clearAllSources}
            onSend={handleSend}
            onStop={chat.stopGeneration}
            onOpenSourcesModal={() => setIsSourcesModalOpen(true)}
          />
        </main>

        {/* Right — sources panel */}
        {isPanelCollapsed ? (
          <SourcesPanelToggle
            onClick={() => setIsPanelCollapsed(false)}
            activeJobCount={activeJobCount}
          />
        ) : (
          <SourcesPanel
            jobs={jobs}
            isUploading={isUploading}
            isCollapsed={isPanelCollapsed}
            clearableJobCount={clearableJobCount}
            fadingJobIds={fadingJobIds}
            hiddenJobIds={hiddenJobIds}
            onToggleCollapse={() => setIsPanelCollapsed(true)}
            onDropFiles={handleDropFiles}
            onCancelJob={cancelJob}
            onClearCompleted={clearCompleted}
            onIngestText={ingestText}
            onIngestUrl={ingestUrl}
          />
        )}

        {/* Toast notification */}
        {chatToast && (
          <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-border bg-surface px-4 py-2.5 shadow-lg">
            <span className="text-sm text-foreground">{chatToast}</span>
          </div>
        )}

        {/* Sources modal — self-contained for deletion; calls refreshSources on change */}
        <SourcesModal
          isOpen={isSourcesModalOpen}
          onClose={() => setIsSourcesModalOpen(false)}
          onSourcesChanged={refreshSources}
          buildingGraphJobBySrc={buildingGraphJobBySrc}
        />
      </div>
    </>
  );
}
