import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  CircleAlert,
  Download,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  RefreshCcw,
  Scissors,
  Settings2,
  Square,
  Subtitles,
  WifiOff,
} from "lucide-react";
import "./styles.css";

type LaneStatus = "queued" | "rendering" | "ready" | "overlaying" | "failed";
type JobStatus = "idle" | "loading" | "generating" | "rendering_base" | "rendering_overlay" | "ready" | "exporting" | "failed" | "cancelled";
type ConnectionState = "connected" | "connecting" | "disconnected";
type ExportState = "idle" | "exporting" | "done" | "failed";
type VideoDuration = 15 | 30 | 60;
type StorylineCount = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10;
type ModelProvider = "codex-cli" | "claude-cli" | "openai" | "kimi";
type ActiveTab = "dashboard" | "settings";
type SettingsSaveState = "idle" | "saving" | "saved" | "error";

type VoiceIsolationSettings = {
  enabled: boolean;
  configured: boolean;
  masked_key: string | null;
};

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
  jobStatus: JobStatus;
  jobPhase: string | null;
  jobProgress: number;
  jobMessage: string | null;
  jobError: string | null;
  projectName: string;
  projectPath: string | null;
  sourceLabel: string;
  connection: ConnectionState;
  generatedAt: string;
  storylines: Storyline[];
  selectedStorylineId: string | null;
  subtitlesEnabled: boolean;
  durationS: VideoDuration;
  nStorylines: StorylineCount;
  provider: ModelProvider;
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
  status?: JobStatus;
  phase?: string | null;
  progress?: number;
  message?: string | null;
  error?: string | null;
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
  duration_s?: number;
  durationS?: number;
  n_storylines?: number;
  nStorylines?: number;
  provider?: string;
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
const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay", "exporting"]);
const GENERATION_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay"]);
const GENERATION_STAGES = [
  { label: "프로젝트 분석", description: "CapCut 타임라인과 원본 미디어를 확인합니다." },
  { label: "스토리라인 구성", description: "AI가 릴스별 관점과 컷 순서를 설계합니다." },
  { label: "영상 제작", description: "세로 영상 렌더링과 제목·자막 합성을 진행합니다." },
] as const;
const VIDEO_DURATIONS: VideoDuration[] = [15, 30, 60];
const STORYLINE_COUNTS: StorylineCount[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const PROVIDER_OPTIONS: Array<{ value: ModelProvider; label: string; description: string }> = [
  { value: "codex-cli", label: "Codex CLI", description: "로컬 Codex 인증과 설치된 기본 모델을 사용합니다." },
  { value: "claude-cli", label: "Claude CLI", description: "설치된 Claude Code CLI를 사용합니다." },
  { value: "openai", label: "OpenAI API", description: "OPENAI_API_KEY 환경변수의 자격증명을 사용합니다." },
  { value: "kimi", label: "Kimi API", description: "MOONSHOT_API_KEY 환경변수의 자격증명을 사용합니다." },
];

function videoDuration(value: number | undefined): VideoDuration {
  return VIDEO_DURATIONS.includes(value as VideoDuration) ? value as VideoDuration : 30;
}

function storylineCount(value: number | undefined): StorylineCount {
  return STORYLINE_COUNTS.includes(value as StorylineCount) ? value as StorylineCount : 3;
}

function modelProvider(value: string | undefined): ModelProvider {
  return PROVIDER_OPTIONS.some((option) => option.value === value) ? value as ModelProvider : "codex-cli";
}

function progressPercent(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return 0;
  const percent = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function generationStageIndex(status: JobStatus): number {
  if (status === "loading") return 0;
  if (status === "generating") return 1;
  return 2;
}

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
  if (!response.ok) {
    let detail = `request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // JSON이 아닌 오류 응답은 상태 코드 메시지를 유지한다.
    }
    throw new Error(detail);
  }
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
    jobStatus: "idle",
    jobPhase: null,
    jobProgress: 0,
    jobMessage: null,
    jobError: null,
    projectName: "Reels Editor",
    projectPath: null,
    sourceLabel: "프로젝트 없음",
    connection,
    generatedAt: new Date().toISOString(),
    selectedStorylineId: null,
    subtitlesEnabled: true,
    durationS: 30,
    nStorylines: 3,
    provider: "codex-cli",
    eventSeq: 0,
    storylines: [0, 1, 2].map(makePlaceholderStoryline),
  };
}

function makeDemoSnapshot(media?: MediaItem[]): Snapshot {
  const items = media?.length ? media : [1, 2, 3].map((number) => ({ name: `sample-${number}.mp4`, url: `/media/sample-${number}.mp4` }));
  const showGenerationProgress = new URLSearchParams(window.location.search).has("generation-progress");
  return {
    jobId: "demo-job-kim-hyunji",
    jobStatus: showGenerationProgress ? "rendering_base" : "ready",
    jobPhase: showGenerationProgress ? "rendering" : "ready",
    jobProgress: showGenerationProgress ? 64 : 100,
    jobMessage: showGenerationProgress
      ? "스토리라인 2: 제목·자막 오버레이와 오디오를 합성하는 중입니다. · 전체 1/3개 완료"
      : "대표 영상 3개가 준비되었습니다.",
    jobError: null,
    projectName: "김현지대표인터뷰",
    projectPath: "/demo/kim-hyunji",
    sourceLabel: "대표 인터뷰 원본",
    connection: "connected",
    generatedAt: "2026-07-20T09:00:00+09:00",
    selectedStorylineId: "storyline-1",
    subtitlesEnabled: true,
    durationS: 30,
    nStorylines: 3,
    provider: "codex-cli",
    eventSeq: 1,
    storylines: [0, 1, 2].map((index) => ({
      id: `storyline-${index + 1}`,
      serverId: `storyline-${index + 1}`,
      index: index + 1,
      label: `스토리라인 ${index + 1}`,
      hook: ["판단 기준", "실행 원칙", "고객 관점"][index],
      summary: DEMO_SUMMARIES[index],
      status: showGenerationProgress ? (["ready", "overlaying", "rendering"] as LaneStatus[])[index] : "ready",
      progress: showGenerationProgress ? [100, 78, 45][index] : 100,
      videoUrl: mediaUrl(items[index]?.url ?? `/media/sample-${index + 1}.mp4`),
      titleOptions: DEMO_TITLES[index],
      selectedTitle: DEMO_TITLES[index][0],
      selectedTitleIndex: 0,
      revision: 1,
    })),
  };
}

function normalizeSnapshot(payload: ApiSnapshot): Snapshot {
  const targetStorylineCount = storylineCount(payload.n_storylines ?? payload.nStorylines);
  const storylines: Storyline[] = (payload.storylines ?? []).slice(0, targetStorylineCount).map((storyline, index) => {
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
  while (storylines.length < targetStorylineCount) {
    storylines.push(makePlaceholderStoryline(storylines.length));
  }

  return {
    jobId: payload.job_id ?? payload.jobId ?? "active-job",
    jobStatus: payload.status ?? "idle",
    jobPhase: payload.phase ?? null,
    jobProgress: progressPercent(payload.progress),
    jobMessage: payload.message ?? null,
    jobError: payload.error ?? null,
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
    durationS: videoDuration(payload.duration_s ?? payload.durationS),
    nStorylines: targetStorylineCount,
    provider: modelProvider(payload.provider),
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
  const [selectedExportIds, setSelectedExportIds] = useState<string[]>([]);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [exportState, setExportState] = useState<ExportState>("idle");
  const [videoDurationS, setVideoDurationS] = useState<VideoDuration>(30);
  const [selectedStorylineCount, setSelectedStorylineCount] = useState<StorylineCount>(3);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider>("codex-cli");
  const [voiceIsolationEnabled, setVoiceIsolationEnabled] = useState(false);
  const [voiceIsolationConfigured, setVoiceIsolationConfigured] = useState(false);
  const [voiceIsolationMaskedKey, setVoiceIsolationMaskedKey] = useState<string | null>(null);
  const [voiceIsolationApiKey, setVoiceIsolationApiKey] = useState("");
  const [voiceSettingsSaveState, setVoiceSettingsSaveState] = useState<SettingsSaveState>("idle");
  const [activeTab, setActiveTab] = useState<ActiveTab>("dashboard");
  const [eventConnectionVersion, setEventConnectionVersion] = useState(0);
  const [liveMessage, setLiveMessage] = useState("대시보드 연결 중");
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const eventSeqRef = useRef(0);
  const activeJobIdRef = useRef<string | null>(null);
  const exportSelectionSeededRef = useRef(false);

  const applySnapshot = useCallback((next: Snapshot) => {
    const jobChanged = activeJobIdRef.current !== next.jobId;
    activeJobIdRef.current = next.jobId;
    if (jobChanged) exportSelectionSeededRef.current = false;
    const defaultSelectedId = next.selectedStorylineId
      ?? next.storylines.find((storyline) => storyline.status === "ready")?.id
      ?? null;
    const availableIds = new Set(next.storylines.map((storyline) => storyline.id));
    setSnapshot(next);
    setSelectedId((current) => current && availableIds.has(current) ? current : defaultSelectedId);
    setSelectedExportIds((current) => {
      if (jobChanged) current = [];
      const retained = current.filter((id) => availableIds.has(id));
      if (!exportSelectionSeededRef.current && defaultSelectedId) {
        exportSelectionSeededRef.current = true;
        return [defaultSelectedId];
      }
      return retained;
    });
    setSubtitlesEnabled(next.subtitlesEnabled);
    if (jobChanged) {
      setVideoDurationS(next.durationS);
      setSelectedStorylineCount(next.nStorylines);
      setSelectedProvider(next.provider);
    }
    setConnection(next.connection);
    eventSeqRef.current = jobChanged ? next.eventSeq : Math.max(eventSeqRef.current, next.eventSeq);
    setLiveMessage(next.jobMessage ?? `${next.projectName} 작업 상태를 불러왔습니다.`);
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
    if (isDemoMode()) return;
    let cancelled = false;
    void apiFetch("/api/settings/voice-isolation")
      .then(async (response) => {
        if (!response.ok) throw new Error("Voice Isolator 설정을 불러오지 못했습니다.");
        const settings = (await response.json()) as VoiceIsolationSettings;
        if (cancelled) return;
        setVoiceIsolationEnabled(settings.enabled);
        setVoiceIsolationConfigured(settings.configured);
        setVoiceIsolationMaskedKey(settings.masked_key);
      })
      .catch(() => {
        if (!cancelled) setVoiceSettingsSaveState("error");
      });
    return () => { cancelled = true; };
  }, []);

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
  }, [applySnapshot, eventConnectionVersion]);

  const storylines = snapshot?.storylines ?? [];
  const selectedStoryline = storylines.find((storyline) => storyline.id === selectedId) ?? null;
  const selectedExportStorylines = storylines.filter((storyline) => selectedExportIds.includes(storyline.id));
  const readySelected = selectedExportStorylines.length > 0
    && selectedExportStorylines.every((storyline) => storyline.status === "ready");
  const jobBusy = ACTIVE_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle") || storylines.some(
    (storyline) => !storyline.serverId.startsWith("placeholder-") && ["queued", "rendering", "overlaying"].includes(storyline.status),
  );
  const canGenerate = Boolean(snapshot?.projectPath) && !jobBusy;
  const generateLabel = jobBusy ? "생성 중" : "다시 생성";
  const generationActive = GENERATION_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle");
  const activeGenerationStage = generationStageIndex(snapshot?.jobStatus ?? "idle");
  const generationProgress = snapshot?.jobProgress ?? 0;

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
  ) {
    if (isDemoMode() || !snapshot) return;
    await apiMutation(`/api/jobs/${snapshot.jobId}/storylines/${storyline.serverId}/selection`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title_index: titleIndex,
        subtitles_on: subtitlesOn,
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
    void patchSelection(storyline, titleIndex, subtitlesEnabled).catch(() =>
      setLiveMessage("제목 변경 요청이 실패했습니다."),
    );
  }

  function selectForExport(storyline: Storyline, checked?: boolean) {
    setSelectedId(storyline.id);
    setSelectedExportIds((current) => {
      const isSelected = current.includes(storyline.id);
      const shouldSelect = checked ?? !isSelected;
      const next = shouldSelect
        ? Array.from(new Set([...current, storyline.id]))
        : current.filter((id) => id !== storyline.id);
      setLiveMessage(
        shouldSelect
          ? `${storyline.label} 영상을 내보내기 목록에 추가했습니다.`
          : `${storyline.label} 영상을 내보내기 목록에서 제외했습니다.`,
      );
      return next;
    });
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
        void patchSelection(selectedStoryline, selectedStoryline.selectedTitleIndex, next).catch(() =>
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
        await startProjectJob(payload.path);
        setLiveMessage(`선택한 프로젝트로 대표 영상 ${selectedStorylineCount}개 렌더를 시작합니다.`);
      }
    } catch {
      setLiveMessage("프로젝트 폴더 선택에 실패했습니다.");
    }
  }

  async function startProjectJob(projectPath: string) {
    const response = await apiMutation("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_path: projectPath,
        duration_s: videoDurationS,
        n_storylines: selectedStorylineCount,
        provider: selectedProvider,
      }),
    });
    applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
    setEventConnectionVersion((version) => version + 1);
  }

  async function exportSelected() {
    if (!readySelected || !snapshot) return;
    setExportState("exporting");
    setLiveMessage(
      voiceIsolationEnabled
        ? `선택한 영상 ${selectedExportStorylines.length}개의 목소리를 선명하게 처리합니다.`
        : `선택한 영상 ${selectedExportStorylines.length}개 내보내기를 준비합니다.`,
    );
    try {
      if (!isDemoMode()) {
        await apiMutation(`/api/jobs/${snapshot.jobId}/export-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            storyline_ids: selectedExportStorylines.map((storyline) => storyline.serverId),
            subtitles_on: subtitlesEnabled,
          }),
        });
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 450));
      }
      setExportState("done");
      setLiveMessage(`선택한 영상 ${selectedExportStorylines.length}개 내보내기가 완료되었습니다.`);
    } catch (error) {
      setExportState("failed");
      const detail = error instanceof Error ? `: ${error.message}` : "";
      setLiveMessage(`내보내기에 실패했습니다${detail}`);
    }
  }

  async function saveVoiceIsolationSettings() {
    if (voiceIsolationEnabled && !voiceIsolationConfigured && !voiceIsolationApiKey.trim()) {
      setVoiceSettingsSaveState("error");
      setLiveMessage("Voice Isolator를 켜려면 ElevenLabs API 키가 필요합니다.");
      return;
    }
    setVoiceSettingsSaveState("saving");
    try {
      const response = await apiMutation("/api/settings/voice-isolation", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: voiceIsolationEnabled,
          ...(voiceIsolationApiKey.trim() ? { api_key: voiceIsolationApiKey.trim() } : {}),
        }),
      });
      const settings = (await response.json()) as VoiceIsolationSettings;
      setVoiceIsolationEnabled(settings.enabled);
      setVoiceIsolationConfigured(settings.configured);
      setVoiceIsolationMaskedKey(settings.masked_key);
      setVoiceIsolationApiKey("");
      setVoiceSettingsSaveState("saved");
      setLiveMessage(settings.enabled ? "ElevenLabs Voice Isolator가 연결되었습니다." : "Voice Isolator를 껐습니다.");
    } catch (error) {
      setVoiceSettingsSaveState("error");
      setLiveMessage(error instanceof Error ? error.message : "Voice Isolator 설정 저장에 실패했습니다.");
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
                setLiveMessage(`대표 영상 ${selectedStorylineCount}개 렌더를 시작합니다.`);
                void startProjectJob(snapshot.projectPath).catch(() => setLiveMessage("생성 요청이 실패했습니다."));
                return;
              }
              setLiveMessage(`대표 영상 ${selectedStorylineCount}개 렌더를 시작합니다.`);
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

      <nav className="workspace-tabs" role="tablist" aria-label="작업 화면">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "dashboard"}
          className={activeTab === "dashboard" ? "active" : ""}
          onClick={() => setActiveTab("dashboard")}
        >
          <LayoutDashboard size={16} /> 대시보드
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "settings"}
          className={activeTab === "settings" ? "active" : ""}
          onClick={() => setActiveTab("settings")}
        >
          <Settings2 size={16} /> 설정
        </button>
      </nav>

      <section className="settings-panel" hidden={activeTab !== "settings"} aria-labelledby="settings-title">
        <header className="settings-header">
          <div>
            <p className="eyebrow">생성 환경</p>
            <h2 id="settings-title">영상 생성 설정</h2>
          </div>
          <span className="settings-state">{jobBusy ? "작업 중 변경 불가" : "다음 생성부터 적용"}</span>
        </header>

        <div className="settings-list">
          <div className="settings-row">
            <div>
              <h3>영상 길이</h3>
              <p>완성될 릴스의 목표 길이를 선택합니다.</p>
            </div>
            <fieldset className="segmented-control" disabled={jobBusy}>
              <legend className="sr-only">영상 길이</legend>
              {VIDEO_DURATIONS.map((duration) => (
                <label key={duration}>
                  <input
                    type="radio"
                    name="video-duration"
                    value={duration}
                    checked={videoDurationS === duration}
                    onChange={() => setVideoDurationS(duration)}
                  />
                  <span>{duration}초</span>
                </label>
              ))}
            </fieldset>
          </div>

          <div className="settings-row">
            <div>
              <h3>스토리텔링 개수</h3>
              <p>서로 다른 관점으로 생성할 후보 영상 수입니다.</p>
            </div>
            <fieldset className="segmented-control storyline-count-control" disabled={jobBusy}>
              <legend className="sr-only">스토리텔링 개수</legend>
              {STORYLINE_COUNTS.map((count) => (
                <label key={count}>
                  <input
                    type="radio"
                    name="storyline-count"
                    value={count}
                    checked={selectedStorylineCount === count}
                    onChange={() => setSelectedStorylineCount(count)}
                  />
                  <span>{count}개</span>
                </label>
              ))}
            </fieldset>
          </div>

          <div className="settings-row provider-row">
            <div>
              <h3>모델 프로바이더</h3>
              <p>{PROVIDER_OPTIONS.find((option) => option.value === selectedProvider)?.description}</p>
            </div>
            <label className="provider-select" htmlFor="model-provider">
              <span className="sr-only">모델 프로바이더</span>
              <select
                id="model-provider"
                aria-label="모델 프로바이더"
                value={selectedProvider}
                disabled={jobBusy}
                onChange={(event) => setSelectedProvider(event.target.value as ModelProvider)}
              >
                {PROVIDER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="settings-row voice-isolation-row">
            <div>
              <h3>ElevenLabs Voice Isolator</h3>
              <p>최종 내보내기에서만 사람 목소리를 분리합니다. 30초 영상은 공개 가격 기준 약 $0.06입니다.</p>
            </div>
            <div className="voice-isolation-control">
              <label className="switch voice-isolation-switch">
                <input
                  type="checkbox"
                  checked={voiceIsolationEnabled}
                  onChange={(event) => {
                    setVoiceIsolationEnabled(event.target.checked);
                    setVoiceSettingsSaveState("idle");
                  }}
                  role="switch"
                  aria-checked={voiceIsolationEnabled}
                />
                <span className="switch-track" aria-hidden="true"><Check size={15} /></span>
                <span>음성 개선 {voiceIsolationEnabled ? "ON" : "OFF"}</span>
              </label>
              <div className="api-key-entry">
                <input
                  type="password"
                  value={voiceIsolationApiKey}
                  autoComplete="off"
                  placeholder={voiceIsolationConfigured ? `저장됨: ${voiceIsolationMaskedKey ?? "••••"}` : "ElevenLabs API 키"}
                  aria-label="ElevenLabs API 키"
                  onChange={(event) => {
                    setVoiceIsolationApiKey(event.target.value);
                    setVoiceSettingsSaveState("idle");
                  }}
                />
                <button
                  type="button"
                  onClick={() => void saveVoiceIsolationSettings()}
                  disabled={voiceSettingsSaveState === "saving"}
                >
                  {voiceSettingsSaveState === "saving" ? <Loader2 size={15} className="spin" /> : null}
                  {voiceSettingsSaveState === "saved" ? "저장됨" : "연결 저장"}
                </button>
              </div>
              <small className={voiceSettingsSaveState === "error" ? "settings-error" : ""}>
                {voiceIsolationConfigured
                  ? "API 키는 이 Mac에 암호화되지 않은 로컬 설정 파일(권한 600)로 저장됩니다."
                  : "ElevenLabs 대시보드에서 만든 API 키가 필요합니다."}
              </small>
            </div>
          </div>
        </div>
      </section>

      <section className="status-row" aria-label="작업 상태" hidden={activeTab !== "dashboard"}>
        <div>
          <span className={`connection-dot ${connection}`} />
          <strong>{connection === "connected" ? "로컬 엔진 연결됨" : connection === "connecting" ? "연결 중" : "연결 끊김"}</strong>
          <small>{snapshot.sourceLabel}</small>
        </div>
        <div><strong>{stats.ready}/{stats.total}</strong><small>준비된 대표 영상</small></div>
        <div><strong>{stats.failed}</strong><small>실패한 스토리라인</small></div>
        <div><strong>{subtitlesEnabled ? "ON" : "OFF"}</strong><small>자막 오버레이</small></div>
      </section>

      {generationActive && activeTab === "dashboard" ? (
        <section className="generation-progress" aria-labelledby="generation-progress-title" aria-live="polite">
          <div className="generation-progress-heading">
            <div className="generation-progress-title">
              <span className="generation-progress-icon" aria-hidden="true"><Loader2 size={17} className="spin" /></span>
              <div>
                <p className="eyebrow">생성 진행 · {activeGenerationStage + 1}/{GENERATION_STAGES.length}단계</p>
                <h2 id="generation-progress-title">{GENERATION_STAGES[activeGenerationStage].label}</h2>
                <p>{snapshot?.jobMessage ?? GENERATION_STAGES[activeGenerationStage].description}</p>
              </div>
            </div>
            <strong className="generation-progress-percent">{generationProgress}%</strong>
          </div>
          <div
            className="generation-progress-track"
            role="progressbar"
            aria-label="전체 영상 생성 진행률"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={generationProgress}
          >
            <span style={{ width: `${generationProgress}%` }} />
          </div>
          <ol className="generation-steps">
            {GENERATION_STAGES.map((stage, index) => {
              const state = index < activeGenerationStage ? "done" : index === activeGenerationStage ? "active" : "upcoming";
              return (
                <li className={state} key={stage.label}>
                  <span aria-hidden="true">{state === "done" ? <Check size={13} /> : index + 1}</span>
                  <div><strong>{stage.label}</strong><small>{stage.description}</small></div>
                </li>
              );
            })}
          </ol>
          <p className="generation-progress-detail">
            준비 완료 {stats.ready}개 · 렌더링 {storylines.filter((storyline) => storyline.status === "rendering").length}개 · 오버레이 {storylines.filter((storyline) => storyline.status === "overlaying").length}개
          </p>
        </section>
      ) : null}

      {connection === "disconnected" && activeTab === "dashboard" ? (
        <section className="notice" role="status">
          <WifiOff size={18} aria-hidden="true" />
          <span>로컬 Python 엔진과 연결이 끊겼습니다. 현재 화면은 마지막 상태입니다.</span>
          <button type="button" onClick={reconnect}>다시 연결</button>
        </section>
      ) : null}

      <section className="lane-scroller" aria-label="스토리라인 비교" hidden={activeTab !== "dashboard"}>
        <div className="lanes">
          {storylines.map((storyline) => (
            <article className={`lane ${selectedExportIds.includes(storyline.id) ? "selected-lane" : ""}`} key={storyline.id} aria-labelledby={`${storyline.id}-title`}>
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
                    type="checkbox"
                    name="selected-video"
                    checked={selectedExportIds.includes(storyline.id)}
                    disabled={storyline.status !== "ready"}
                    onChange={(event) => selectForExport(storyline, event.target.checked)}
                  />
                  <span>내보내기 선택</span>
                </label>
                {storyline.status === "failed" ? <button type="button" onClick={() => retryStoryline(storyline)}>다시 시도</button> : null}
              </div>
              {storyline.error ? <p className="lane-error" role="alert">{storyline.error}</p> : null}
            </article>
          ))}
        </div>
      </section>

      <section className="export-bar" aria-label="내보내기" hidden={activeTab !== "dashboard"}>
        <div className="export-summary">
          <strong>{selectedExportStorylines.length > 0 ? `${selectedExportStorylines.length}개 영상 선택됨` : "선택된 영상 없음"}</strong>
          <span>
            {selectedExportStorylines.length > 0
              ? `${selectedExportStorylines.map((storyline) => storyline.label).join(" · ")}${voiceIsolationEnabled ? " · Voice Isolator ON" : ""}`
              : "준비된 대표 영상을 복수로 선택할 수 있습니다."}
          </span>
        </div>
        <label className="switch">
          <input type="checkbox" checked={subtitlesEnabled} onChange={toggleSubtitles} role="switch" aria-checked={subtitlesEnabled} />
          <span className="switch-track" aria-hidden="true"><Subtitles size={15} /></span>
          <span>자막 {subtitlesEnabled ? "ON" : "OFF"}</span>
        </label>
        <button type="button" className="export-button" disabled={!readySelected || exportState === "exporting"} onClick={exportSelected}>
          {exportState === "exporting" ? <Loader2 size={17} className="spin" /> : <Download size={17} />}
          {exportState === "done" ? "완료됨" : `선택 영상 ${selectedExportStorylines.length}개 내보내기`}
        </button>
      </section>

      <div className="sr-only" role="status" aria-live="polite">{liveMessage}</div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
