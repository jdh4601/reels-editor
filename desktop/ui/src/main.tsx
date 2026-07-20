import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  CircleAlert,
  Download,
  FolderOpen,
  Loader2,
  RefreshCcw,
  Scissors,
  Square,
  Subtitles,
  WifiOff,
} from "lucide-react";
import "./styles.css";

type LaneStatus = "queued" | "rendering" | "ready" | "overlaying" | "failed";
type ConnectionState = "connected" | "connecting" | "disconnected";
type ExportState = "idle" | "exporting" | "done" | "failed";

type MediaItem = {
  name: string;
  url: string;
  size?: number;
};

type Storyline = {
  id: string;
  serverId: string;
  index: number;
  label: string;
  hook: string;
  summary: string;
  status: LaneStatus;
  progress: number;
  videoUrl: string | null;
  titleOptions: string[];
  selectedTitle: string;
  selectedTitleIndex: number;
  error?: string;
  revision: number;
};

type Snapshot = {
  jobId: string;
  projectName: string;
  projectPath: string | null;
  sourceLabel: string;
  connection: ConnectionState;
  generatedAt: string;
  storylines: Storyline[];
  selectedStorylineId: string | null;
  subtitlesEnabled: boolean;
  eventSeq: number;
};

type ApiStoryline = {
  id?: string;
  storyline_id?: string;
  index?: number;
  label?: string;
  hook?: string;
  summary?: string;
  status?: LaneStatus;
  progress?: number;
  video_url?: string | null;
  videoUrl?: string | null;
  title_options?: string[];
  titleOptions?: string[];
  selected_title_index?: number;
  selectedTitleIndex?: number;
  selected_title?: string;
  selectedTitle?: string;
  error?: string;
  revision?: number;
};

type ApiSnapshot = {
  job_id?: string;
  jobId?: string;
  project_name?: string;
  projectName?: string;
  project_path?: string | null;
  projectPath?: string | null;
  source_label?: string;
  sourceLabel?: string;
  connection?: ConnectionState;
  generated_at?: string;
  generatedAt?: string;
  storylines?: ApiStoryline[];
  selected_storyline_id?: string | null;
  selectedStorylineId?: string | null;
  subtitles_on?: boolean;
  subtitlesEnabled?: boolean;
  seq?: number;
  event_seq?: number;
};

type EventPayload =
  | ApiSnapshot
  | { snapshot?: ApiSnapshot; seq?: number; event_seq?: number }
  | { event: "heartbeat"; seq?: number; event_seq?: number };

const DEMO_TITLES = [
  ["숫자보다 중요한 대표의 기준", "김현지 대표가 말한 성장의 조건", "팀을 움직인 한 가지 판단"],
  ["대표 인터뷰에서 건진 실행 원칙", "좋은 의사결정은 어디서 시작되나", "현장에서 배운 리더십의 언어"],
  ["짧게 보는 김현지 대표의 관점", "고객을 먼저 본 순간 달라진 것", "선택을 빠르게 만드는 질문"],
];

const DEMO_SUMMARIES = [
  "대표의 판단 기준을 초반 3초에 배치하고, 중반에는 실제 문제 해결 과정을 압축합니다.",
  "인터뷰의 실행 원칙을 질문과 답의 리듬으로 보여주며 업무 현장감을 살립니다.",
  "고객 관점 전환을 중심으로 짧은 전개와 강한 마무리 문장을 구성합니다.",
];

const STATUS_LABEL: Record<LaneStatus, string> = {
  queued: "대기",
  rendering: "렌더 중",
  ready: "준비됨",
  overlaying: "오버레이 반영",
  failed: "실패",
};

const EMPTY_TITLES = ["제목 생성 대기", "추천 제목 준비 중", "렌더 후 선택 가능"];
const EMPTY_SUMMARY = "프로젝트를 선택하면 대표 영상과 추천 제목이 여기에 표시됩니다.";

function isDemoMode(): boolean {
  return new URLSearchParams(window.location.search).has("demo");
}

function sessionToken(): string | null {
  const hashToken = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");
  return hashToken ?? new URLSearchParams(window.location.search).get("token");
}

function apiUrl(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
  });
  return `${url.pathname}${url.search}`;
}

function wsUrl(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const token = sessionToken();
  return `${scheme}://${window.location.host}${apiUrl(path, { ...params, token })}`;
}

function apiFetch(path: string, init?: RequestInit, params?: Record<string, string | number | boolean | null | undefined>) {
  const headers = new Headers(init?.headers);
  const token = sessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(apiUrl(path, params), { ...init, headers });
}

async function apiMutation(path: string, init?: RequestInit, params?: Record<string, string | number | boolean | null | undefined>) {
  const response = await apiFetch(path, init, params);
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response;
}

function mediaUrl(url: string | null): string | null {
  if (!url) return url;
  if (!url.startsWith("/")) return url;
  const token = sessionToken();
  return apiUrl(url, { token });
}

function makePlaceholderStoryline(index: number): Storyline {
  return {
    id: `placeholder-${index + 1}`,
    serverId: `placeholder-${index + 1}`,
    index: index + 1,
    label: `스토리라인 ${index + 1}`,
    hook: "대기 중",
    summary: EMPTY_SUMMARY,
    status: "queued",
    progress: 0,
    videoUrl: null,
    titleOptions: EMPTY_TITLES,
    selectedTitle: EMPTY_TITLES[0],
    selectedTitleIndex: 0,
    revision: 0,
  };
}

function makeEmptySnapshot(connection: ConnectionState = "disconnected"): Snapshot {
  return {
    jobId: "empty",
    projectName: "Reels Editor",
    projectPath: null,
    sourceLabel: "프로젝트 없음",
    connection,
    generatedAt: new Date().toISOString(),
    selectedStorylineId: null,
    subtitlesEnabled: true,
    eventSeq: 0,
    storylines: [0, 1, 2].map(makePlaceholderStoryline),
  };
}

function makeDemoSnapshot(media?: MediaItem[]): Snapshot {
  const items = media?.length ? media : [1, 2, 3].map((number) => ({ name: `sample-${number}.mp4`, url: `/media/sample-${number}.mp4` }));
  return {
    jobId: "demo-job-kim-hyunji",
    projectName: "김현지대표인터뷰",
    projectPath: "/demo/kim-hyunji",
    sourceLabel: "대표 인터뷰 원본",
    connection: "connected",
    generatedAt: "2026-07-20T09:00:00+09:00",
    selectedStorylineId: "storyline-1",
    subtitlesEnabled: true,
    eventSeq: 1,
    storylines: [0, 1, 2].map((index) => ({
      id: `storyline-${index + 1}`,
      serverId: `storyline-${index + 1}`,
      index: index + 1,
      label: `스토리라인 ${index + 1}`,
      hook: ["판단 기준", "실행 원칙", "고객 관점"][index],
      summary: DEMO_SUMMARIES[index],
      status: "ready",
      progress: 100,
      videoUrl: mediaUrl(items[index]?.url ?? `/media/sample-${index + 1}.mp4`),
      titleOptions: DEMO_TITLES[index],
      selectedTitle: DEMO_TITLES[index][0],
      selectedTitleIndex: 0,
      revision: 1,
    })),
  };
}

function normalizeSnapshot(payload: ApiSnapshot): Snapshot {
  const storylines: Storyline[] = (payload.storylines ?? []).slice(0, 3).map((storyline, index) => {
    const titleOptions = (storyline.title_options ?? storyline.titleOptions ?? EMPTY_TITLES).slice(0, 3);
    const selectedTitleIndex = storyline.selected_title_index ?? storyline.selectedTitleIndex ?? 0;
    const serverId = storyline.storyline_id ?? storyline.id ?? `storyline-${index + 1}`;
    return {
      id: serverId,
      serverId,
      index: storyline.index ?? index + 1,
      label: storyline.label ?? `스토리라인 ${index + 1}`,
      hook: storyline.hook ?? titleOptions[0] ?? "대표 영상",
      summary: storyline.summary ?? EMPTY_SUMMARY,
      status: storyline.status ?? "queued",
      progress: storyline.progress ?? 0,
      videoUrl: mediaUrl(storyline.video_url ?? storyline.videoUrl ?? null),
      titleOptions,
      selectedTitle: storyline.selected_title ?? storyline.selectedTitle ?? titleOptions[selectedTitleIndex] ?? titleOptions[0],
      selectedTitleIndex,
      error: storyline.error,
      revision: storyline.revision ?? 1,
    };
  });
  while (storylines.length < 3) {
    storylines.push(makePlaceholderStoryline(storylines.length));
  }

  return {
    jobId: payload.job_id ?? payload.jobId ?? "active-job",
    projectName: payload.project_name ?? payload.projectName ?? "Reels Editor",
    projectPath: payload.project_path ?? payload.projectPath ?? null,
    sourceLabel: payload.source_label ?? payload.sourceLabel ?? "선택된 프로젝트",
    connection: payload.connection ?? "connected",
    generatedAt: payload.generated_at ?? payload.generatedAt ?? new Date().toISOString(),
    storylines,
    selectedStorylineId:
      payload.selected_storyline_id ??
      payload.selectedStorylineId ??
      storylines.find((storyline) => storyline.status === "ready")?.id ??
      null,
    subtitlesEnabled: payload.subtitles_on ?? payload.subtitlesEnabled ?? true,
    eventSeq: payload.event_seq ?? payload.seq ?? 0,
  };
}

function extractSnapshot(payload: ApiSnapshot | { snapshot?: ApiSnapshot }): ApiSnapshot {
  if ("snapshot" in payload && payload.snapshot) return payload.snapshot;
  return payload as ApiSnapshot;
}

function isHeartbeat(payload: EventPayload): payload is { event: "heartbeat"; seq?: number; event_seq?: number } {
  return "event" in payload && payload.event === "heartbeat";
}

async function readSnapshot(): Promise<Snapshot> {
  const demo = isDemoMode();
  if (demo) {
    try {
      const response = await apiFetch("/api/media", undefined, { demo: 1 });
      if (response.ok) {
        const payload = (await response.json()) as { items?: MediaItem[] };
        return makeDemoSnapshot(payload.items);
      }
    } catch {
      return makeDemoSnapshot();
    }
    return makeDemoSnapshot();
  }

  const snapshotResponse = await apiFetch("/api/snapshot");
  if (!snapshotResponse.ok) throw new Error("snapshot unavailable");
  return normalizeSnapshot((await snapshotResponse.json()) as ApiSnapshot);
}

function statusTone(status: LaneStatus): string {
  if (status === "ready") return "ready";
  if (status === "failed") return "failed";
  if (status === "overlaying") return "overlay";
  return "working";
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [exportState, setExportState] = useState<ExportState>("idle");
  const [liveMessage, setLiveMessage] = useState("대시보드 연결 중");
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const eventSeqRef = useRef(0);

  const applySnapshot = useCallback((next: Snapshot) => {
    setSnapshot(next);
    setSelectedId(next.selectedStorylineId ?? next.storylines.find((storyline) => storyline.status === "ready")?.id ?? null);
    setSubtitlesEnabled(next.subtitlesEnabled);
    setConnection(next.connection);
    eventSeqRef.current = Math.max(eventSeqRef.current, next.eventSeq);
    setLiveMessage(`${next.projectName} 작업 상태를 불러왔습니다.`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    readSnapshot()
      .then((payload) => {
        if (!cancelled) applySnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setSnapshot(makeEmptySnapshot("disconnected"));
          setConnection("disconnected");
          setLiveMessage("백엔드 연결이 끊겨 빈 작업 상태를 표시합니다.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applySnapshot]);

  useEffect(() => {
    if (isDemoMode()) return undefined;
    let closedByEffect = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | undefined;
    let events: WebSocket | null = null;

    const connect = () => {
      events = new WebSocket(wsUrl("/api/events", { after: eventSeqRef.current }));
      events.onmessage = (event) => {
        reconnectAttempt = 0;
        try {
          const payload = JSON.parse(event.data) as EventPayload;
          const nextSeq = payload.event_seq ?? payload.seq;
          if (typeof nextSeq === "number") eventSeqRef.current = Math.max(eventSeqRef.current, nextSeq);
          if (isHeartbeat(payload)) {
            setConnection("connected");
            return;
          }
          applySnapshot(normalizeSnapshot(extractSnapshot(payload)));
        } catch {
          setLiveMessage("이벤트 메시지를 해석하지 못했습니다.");
        }
      };
      events.onclose = () => {
        if (closedByEffect) return;
        setConnection("disconnected");
        void readSnapshot()
          .then(applySnapshot)
          .catch(() => {
            setSnapshot((current) => current ?? makeEmptySnapshot("disconnected"));
          });
        if (reconnectAttempt < 5) {
          reconnectAttempt += 1;
          reconnectTimer = window.setTimeout(connect, Math.min(5000, 400 * 2 ** reconnectAttempt));
        }
      };
      events.onerror = () => events?.close();
    };

    connect();
    return () => {
      closedByEffect = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      events?.close();
    };
  }, [applySnapshot]);

  const storylines = snapshot?.storylines ?? [];
  const selectedStoryline = storylines.find((storyline) => storyline.id === selectedId) ?? null;
  const readySelected = selectedStoryline?.status === "ready";
  const jobBusy = storylines.some(
    (storyline) => !storyline.serverId.startsWith("placeholder-") && ["queued", "rendering", "overlaying"].includes(storyline.status),
  );
  const canGenerate = Boolean(snapshot?.projectPath) && !jobBusy;
  const generateLabel = jobBusy ? "생성 중" : "다시 생성";

  const stats = useMemo(() => {
    const ready = storylines.filter((storyline) => storyline.status === "ready").length;
    const failed = storylines.filter((storyline) => storyline.status === "failed").length;
    return { ready, failed, total: storylines.length };
  }, [storylines]);

  function updateStoryline(id: string, patch: Partial<Storyline>) {
    setSnapshot((current) => {
      if (!current) return current;
      return {
        ...current,
        storylines: current.storylines.map((storyline) =>
          storyline.id === id ? { ...storyline, ...patch, revision: storyline.revision + 1 } : storyline,
        ),
      };
    });
  }

  async function patchSelection(
    storyline: Storyline,
    titleIndex: number,
    subtitlesOn = subtitlesEnabled,
    selectedForExport?: boolean,
  ) {
    if (isDemoMode() || !snapshot) return;
    await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/selection`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title_index: titleIndex,
        subtitles_on: subtitlesOn,
        ...(selectedForExport === undefined ? {} : { selected_for_export: selectedForExport }),
      }),
    });
  }

  function chooseTitle(storyline: Storyline, title: string, titleIndex: number) {
    setLiveMessage(`${storyline.label} 제목 오버레이를 반영합니다.`);
    if (isDemoMode()) {
      updateStoryline(storyline.id, { selectedTitle: title, selectedTitleIndex: titleIndex, status: "overlaying", progress: 92 });
      window.setTimeout(() => {
        updateStoryline(storyline.id, { selectedTitle: title, selectedTitleIndex: titleIndex, status: "ready", progress: 100 });
        setLiveMessage(`${storyline.label} 제목이 반영되었습니다.`);
      }, 350);
      return;
    }
    void patchSelection(storyline, titleIndex, subtitlesEnabled, selectedId === storyline.id ? true : undefined).catch(() =>
      setLiveMessage("제목 변경 요청이 실패했습니다."),
    );
  }

  function selectForExport(storyline: Storyline) {
    setSelectedId(storyline.id);
    setLiveMessage(`${storyline.label} 영상을 내보내기 대상으로 선택했습니다.`);
    if (isDemoMode()) return;
    void patchSelection(storyline, storyline.selectedTitleIndex, subtitlesEnabled, true).catch(() =>
      setLiveMessage("내보내기 선택 저장에 실패했습니다."),
    );
  }

  function retryStoryline(storyline: Storyline) {
    setLiveMessage(`${storyline.label} 대표 영상을 다시 렌더합니다.`);
    if (isDemoMode()) {
      updateStoryline(storyline.id, { status: "rendering", progress: 38, error: undefined });
      window.setTimeout(() => {
        updateStoryline(storyline.id, { status: "ready", progress: 100 });
        setLiveMessage(`${storyline.label} 대표 영상이 준비되었습니다.`);
      }, 500);
      return;
    }
    if (snapshot) {
      void apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/retry`, { method: "POST" }).catch(() =>
        setLiveMessage("다시 시도 요청이 실패했습니다."),
      );
    }
  }

  function toggleSubtitles() {
    setSubtitlesEnabled((enabled) => {
      const next = !enabled;
      setLiveMessage(next ? "자막 오버레이를 켭니다." : "자막 오버레이를 끕니다.");
      if (selectedStoryline) {
        if (isDemoMode()) {
          updateStoryline(selectedStoryline.id, { status: "overlaying", progress: 94 });
          window.setTimeout(() => updateStoryline(selectedStoryline.id, { status: "ready", progress: 100 }), 350);
        }
        void patchSelection(selectedStoryline, selectedStoryline.selectedTitleIndex, next, true).catch(() =>
          setLiveMessage("자막 변경 요청이 실패했습니다."),
        );
      }
      return next;
    });
  }

  async function reconnect() {
    setConnection("connecting");
    setLiveMessage("백엔드에 다시 연결합니다.");
    try {
      applySnapshot(await readSnapshot());
    } catch {
      setConnection("disconnected");
      setLiveMessage("재연결하지 못했습니다.");
    }
  }

  async function chooseProject() {
    setLiveMessage("프로젝트 폴더 선택을 요청했습니다.");
    if (isDemoMode()) return;
    try {
      const response = await apiFetch("/api/dialogs/open-folder", { method: "POST" });
      if (!response.ok) throw new Error("open folder failed");
      const payload = (await response.json()) as { path?: string | null };
      if (payload.path) {
        await apiMutation("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_path: payload.path }),
        });
        setLiveMessage("선택한 프로젝트로 대표 영상 3개 렌더를 시작합니다.");
      }
    } catch {
      setLiveMessage("프로젝트 폴더 선택에 실패했습니다.");
    }
  }

  async function exportSelected() {
    if (!readySelected || !selectedStoryline || !snapshot) return;
    setExportState("exporting");
    setLiveMessage(`${selectedStoryline.label} 내보내기를 준비합니다.`);
    try {
      if (!isDemoMode()) {
        await apiMutation(`/api/jobs/${snapshot.jobId}/export`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ storyline_id: selectedStoryline.serverId, subtitles_on: subtitlesEnabled }),
        });
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
      }
      setExportState("done");
      setLiveMessage("선택한 영상 내보내기가 완료되었습니다.");
    } catch {
      setExportState("failed");
      setLiveMessage("내보내기에 실패했습니다.");
    }
  }

  function cancelJob() {
    if (!snapshot || isDemoMode() || !jobBusy) return;
    setLiveMessage("작업 취소를 요청했습니다.");
    void apiMutation(`/api/jobs/${snapshot.jobId}/cancel`, { method: "POST" }).catch(() =>
      setLiveMessage("작업 취소 요청이 실패했습니다."),
    );
  }

  function focusLane(index: number) {
    const story = storylines[index - 1];
    const video = story ? videoRefs.current[story.id] : null;
    video?.focus();
  }

  function playSelected() {
    if (!selectedStoryline) return;
    const selectedVideo = videoRefs.current[selectedStoryline.id];
    if (!selectedVideo) return;
    Object.entries(videoRefs.current).forEach(([id, video]) => {
      if (video && id !== selectedStoryline.id) video.pause();
    });
    if (selectedVideo.paused) void selectedVideo.play().catch(() => undefined);
    else selectedVideo.pause();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const key = event.key.toLowerCase();
      if (event.metaKey && key === "o") {
        event.preventDefault();
        void chooseProject();
      } else if (event.metaKey && key === "e") {
        event.preventDefault();
        void exportSelected();
      } else if (event.altKey && ["1", "2", "3"].includes(event.key)) {
        event.preventDefault();
        focusLane(Number(event.key));
      } else if (["1", "2", "3"].includes(event.key) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        const story = storylines[Number(event.key) - 1];
        if (story?.status === "ready") selectForExport(story);
      } else if (event.code === "Space") {
        event.preventDefault();
        playSelected();
      } else if (key === "s" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        toggleSubtitles();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function onVideoPlay(id: string) {
    Object.entries(videoRefs.current).forEach(([otherId, video]) => {
      if (otherId !== id && video) video.pause();
    });
  }

  if (!snapshot) {
    return (
      <main className="loading-shell" aria-busy="true">
        <Loader2 className="spin" aria-hidden="true" />
        <p>대시보드 준비 중</p>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <div className="topbar">
        <div className="project-block">
          <span className="app-mark" aria-hidden="true"><Scissors size={18} /></span>
          <div>
            <p className="eyebrow">Reels Editor</p>
            <h1>{snapshot.projectName}</h1>
          </div>
        </div>
        <div className="workbar-actions" aria-label="작업 도구">
          <button type="button" className="ghost-button" onClick={chooseProject}> <FolderOpen size={17} /> 프로젝트</button>
          <button
            type="button"
            className="ghost-button"
            disabled={!canGenerate}
            onClick={() => {
              if (!isDemoMode()) {
                if (!snapshot.projectPath) {
                  setLiveMessage("먼저 프로젝트 폴더를 선택하세요.");
                  return;
                }
                void apiMutation("/api/jobs", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ project_path: snapshot.projectPath }),
                }).catch(() => setLiveMessage("생성 요청이 실패했습니다."));
              }
              setLiveMessage("대표 영상 3개 렌더를 시작합니다.");
            }}
          >
            <RefreshCcw size={17} /> {generateLabel}
          </button>
          <button type="button" className="icon-button" onClick={reconnect} aria-label="재연결"><RefreshCcw size={18} /></button>
          {jobBusy ? (
            <button type="button" className="icon-button danger" onClick={cancelJob} aria-label="작업 취소" title="작업 취소">
              <Square size={16} />
            </button>
          ) : null}
        </div>
      </div>

      <section className="status-row" aria-label="작업 상태">
        <div>
          <span className={`connection-dot ${connection}`} />
          <strong>{connection === "connected" ? "로컬 엔진 연결됨" : connection === "connecting" ? "연결 중" : "연결 끊김"}</strong>
          <small>{snapshot.sourceLabel}</small>
        </div>
        <div><strong>{stats.ready}/{stats.total}</strong><small>준비된 대표 영상</small></div>
        <div><strong>{stats.failed}</strong><small>실패한 스토리라인</small></div>
        <div><strong>{subtitlesEnabled ? "ON" : "OFF"}</strong><small>자막 오버레이</small></div>
      </section>

      {connection === "disconnected" ? (
        <section className="notice" role="status">
          <WifiOff size={18} aria-hidden="true" />
          <span>로컬 Python 엔진과 연결이 끊겼습니다. 현재 화면은 마지막 상태입니다.</span>
          <button type="button" onClick={reconnect}>다시 연결</button>
        </section>
      ) : null}

      <section className="lane-scroller" aria-label="스토리라인 비교">
        <div className="lanes">
          {storylines.map((storyline) => (
            <article className={`lane ${selectedId === storyline.id ? "selected-lane" : ""}`} key={storyline.id} aria-labelledby={`${storyline.id}-title`}>
              <header className="lane-header">
                <div>
                  <p className="eyebrow">{storyline.label}</p>
                  <h2 id={`${storyline.id}-title`}>{storyline.hook}</h2>
                </div>
                <span className={`status-pill ${statusTone(storyline.status)}`}>
                  {storyline.status === "ready" ? <Check size={14} /> : storyline.status === "failed" ? <CircleAlert size={14} /> : <Loader2 size={14} className="spin" />}
                  {STATUS_LABEL[storyline.status]}
                </span>
              </header>

              <div className="phone-frame">
                {storyline.videoUrl ? (
                  <video
                    ref={(node) => { videoRefs.current[storyline.id] = node; }}
                    controls
                    preload="metadata"
                    muted={selectedId !== storyline.id}
                    src={storyline.videoUrl}
                    onPlay={() => onVideoPlay(storyline.id)}
                    aria-label={`${storyline.label} 대표 영상`}
                  />
                ) : (
                  <div className="video-placeholder">렌더 대기 중</div>
                )}
                {storyline.status !== "ready" ? (
                  <div className="render-overlay" aria-live="polite">
                    {storyline.status === "failed" ? "렌더 실패" : `${storyline.progress}%`}
                  </div>
                ) : null}
              </div>

              <p className="summary">{storyline.summary}</p>

              <fieldset className="title-options">
                <legend>AI 추천 제목 3개 중 선택</legend>
                {storyline.titleOptions.map((title, optionIndex) => (
                  <label key={title} className="title-option">
                    <input
                      type="radio"
                      name={`title-${storyline.id}`}
                      checked={storyline.selectedTitle === title}
                      onChange={() => chooseTitle(storyline, title, optionIndex)}
                    />
                    <span>{optionIndex + 1}. {title}</span>
                  </label>
                ))}
              </fieldset>

              <div className="lane-footer">
                <label className="select-video">
                  <input
                    type="radio"
                    name="selected-video"
                    checked={selectedId === storyline.id}
                    disabled={storyline.status !== "ready"}
                    onChange={() => selectForExport(storyline)}
                  />
                  <span>이 영상 선택</span>
                </label>
                {storyline.status === "failed" ? <button type="button" onClick={() => retryStoryline(storyline)}>다시 시도</button> : null}
              </div>
              {storyline.error ? <p className="lane-error" role="alert">{storyline.error}</p> : null}
            </article>
          ))}
        </div>
      </section>

      <section className="export-bar" aria-label="내보내기">
        <div className="export-summary">
          <strong>{selectedStoryline ? `${selectedStoryline.label} 선택됨` : "선택된 영상 없음"}</strong>
          <span>{selectedStoryline?.selectedTitle ?? "준비된 대표 영상 하나를 선택하세요."}</span>
        </div>
        <label className="switch">
          <input type="checkbox" checked={subtitlesEnabled} onChange={toggleSubtitles} role="switch" aria-checked={subtitlesEnabled} />
          <span className="switch-track" aria-hidden="true"><Subtitles size={15} /></span>
          <span>자막 {subtitlesEnabled ? "ON" : "OFF"}</span>
        </label>
        <button type="button" className="export-button" disabled={!readySelected || exportState === "exporting"} onClick={exportSelected}>
          {exportState === "exporting" ? <Loader2 size={17} className="spin" /> : <Download size={17} />}
          {exportState === "done" ? "완료됨" : "선택 영상 내보내기"}
        </button>
      </section>

      <div className="sr-only" role="status" aria-live="polite">{liveMessage}</div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
