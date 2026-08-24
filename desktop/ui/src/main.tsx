import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AudioLines,
  Check,
  CircleAlert,
  Download,
  FolderOpen,
  FolderX,
  LayoutDashboard,
  Link,
  Loader2,
  RefreshCcw,
  Scissors,
  Settings2,
  Square,
  Subtitles,
  WifiOff,
  Youtube,
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
type SourceType = "youtube" | "capcut";

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

type StorySection = {
  beat: string;
  role: string;
  text: string;
};

type Storyline = {
  id: string;
  serverId: string;
  index: number;
  label: string;
  hook: string;
  summary: string;
  sections: StorySection[];
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
  sourceType: SourceType;
  sourceUrl: string | null;
  transcriptLanguage: string | null;
  transcriptKind: string | null;
  sourceLabel: string;
  connection: ConnectionState;
  generatedAt: string;
  storylines: Storyline[];
  selectedStorylineId: string | null;
  subtitlesEnabled: boolean;
  durationS: VideoDuration;
  nStorylines: StorylineCount;
  provider: ModelProvider;
  voiceIsolationEnabled: boolean;
  eventSeq: number;
};

type ApiStoryline = {
  id?: string;
  storyline_id?: string;
  index?: number;
  label?: string;
  hook?: string;
  summary?: string;
  sections?: StorySection[];
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
  source_type?: SourceType;
  sourceType?: SourceType;
  source_url?: string | null;
  sourceUrl?: string | null;
  transcript_language?: string | null;
  transcriptLanguage?: string | null;
  transcript_kind?: string | null;
  transcriptKind?: string | null;
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
  voice_isolation?: boolean;
  voiceIsolationEnabled?: boolean;
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

const DEMO_SECTIONS: StorySection[][] = [
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "숫자가 아니라 고객의 한마디가 가장 중요한 판단 기준이었습니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "빠르게 성장하던 시기에도 팀은 매일 같은 질문으로 우선순위를 확인했습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "지표는 좋아 보였지만 실제 고객이 겪는 불편은 좀처럼 줄지 않았습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "회의실을 나와 고객을 직접 만나자 우리가 놓친 문제가 선명하게 보였습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "그날 바로 제품 순서를 바꾸고 가장 작은 불편부터 하나씩 해결했습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "좋은 판단은 더 많은 숫자가 아니라 더 가까이 들은 목소리에서 시작됩니다." },
  ],
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "완벽한 계획을 기다렸다면 우리는 아직도 시작하지 못했을 겁니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "처음에는 사람도 예산도 부족해서 매일 예상하지 못한 문제가 생겼습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "준비가 부족하다는 이유로 중요한 결정을 계속 미루고 싶어졌습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "작게 실행하고 결과를 확인하는 편이 오래 고민하는 것보다 빠르다는 걸 배웠습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "일주일짜리 실험을 반복하자 팀이 스스로 답을 찾기 시작했습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "실행력은 정답을 아는 능력이 아니라 다음 답을 빨리 확인하는 습관입니다." },
  ],
  [
    { beat: "훅", role: "첫 3초에 시선을 붙잡는 문장", text: "고객이 떠나는 이유는 우리가 설명하지 않은 작은 순간에 숨어 있었습니다." },
    { beat: "맥락", role: "이야기를 이해시키는 배경", text: "기능은 계속 늘었지만 처음 방문한 고객은 어디서 시작해야 할지 어려워했습니다." },
    { beat: "갈등", role: "문제와 긴장을 선명하게 만드는 구간", text: "팀은 더 많은 기능이 필요하다고 생각했지만 고객은 이미 충분히 복잡하다고 말했습니다." },
    { beat: "전환", role: "생각이나 행동이 바뀌는 순간", text: "무엇을 더할지가 아니라 무엇을 덜어낼지를 기준으로 제품을 다시 보기 시작했습니다." },
    { beat: "핵심 장면", role: "변화를 증명하는 구체적인 장면", text: "첫 화면의 선택지를 절반으로 줄이자 고객의 다음 행동이 눈에 띄게 빨라졌습니다." },
    { beat: "라스트 답", role: "영상이 남기는 결론과 메시지", text: "고객 관점은 친절한 설명이 아니라 망설일 이유를 먼저 없애는 일입니다." },
  ],
];

const STATUS_LABEL: Record<LaneStatus, string> = {
  queued: "대기",
  rendering: "렌더 중",
  ready: "준비됨",
  overlaying: "오버레이 반영",
  failed: "실패",
};

const EMPTY_TITLES = ["제목 생성 대기", "추천 제목 준비 중", "렌더 후 선택 가능"];
const EMPTY_SUMMARY = "YouTube 인터뷰 링크를 넣으면 클립 후보와 후킹 제목이 여기에 표시됩니다.";
const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay", "exporting"]);
const GENERATION_JOB_STATUSES = new Set<JobStatus>(["loading", "generating", "rendering_base", "rendering_overlay"]);
const GENERATION_STAGES = [
  { label: "영상 다운로드", description: "YouTube 인터뷰 원본을 이 Mac에 저장합니다." },
  { label: "영어 자막 추출", description: "영어 원문 자막과 타임코드를 정리합니다." },
  { label: "클립 선정·번역", description: "AI가 영어 원문에서 구간을 고르고 한국어 자막으로 번역합니다." },
  { label: "릴스 제작", description: "9:16 영상에 한국어 자막과 주황색 후킹 제목을 합성합니다." },
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

function generationStageIndex(phase: string | null | undefined, status: JobStatus): number {
  if (phase === "transcript") return 1;
  if (status === "generating" || phase === "generating") return 2;
  if (["rendering", "overlay"].includes(phase ?? "") || status === "rendering_base" || status === "rendering_overlay") return 3;
  return 0;
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
    sections: [],
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
    sourceType: "youtube",
    sourceUrl: null,
    transcriptLanguage: null,
    transcriptKind: null,
    sourceLabel: "YouTube 링크 없음",
    connection,
    generatedAt: new Date().toISOString(),
    selectedStorylineId: null,
    subtitlesEnabled: true,
    durationS: 30,
    nStorylines: 3,
    provider: "codex-cli",
    voiceIsolationEnabled: false,
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
    projectPath: null,
    sourceType: "youtube",
    sourceUrl: "https://www.youtube.com/watch?v=demo-founder",
    transcriptLanguage: "en",
    transcriptKind: "automatic",
    sourceLabel: "YouTube · 영어 원문 자동 자막",
    connection: "connected",
    generatedAt: "2026-07-20T09:00:00+09:00",
    selectedStorylineId: "storyline-1",
    subtitlesEnabled: true,
    durationS: 30,
    nStorylines: 3,
    provider: "codex-cli",
    voiceIsolationEnabled: false,
    eventSeq: 1,
    storylines: [0, 1, 2].map((index) => ({
      id: `storyline-${index + 1}`,
      serverId: `storyline-${index + 1}`,
      index: index + 1,
      label: `스토리라인 ${index + 1}`,
      hook: ["판단 기준", "실행 원칙", "고객 관점"][index],
      summary: DEMO_SUMMARIES[index],
      sections: DEMO_SECTIONS[index],
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
      sections: (storyline.sections ?? []).filter(
        (section) => section.beat.trim() && section.role.trim() && section.text.trim(),
      ),
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
    sourceType: payload.source_type ?? payload.sourceType ?? "capcut",
    sourceUrl: payload.source_url ?? payload.sourceUrl ?? null,
    transcriptLanguage: payload.transcript_language ?? payload.transcriptLanguage ?? null,
    transcriptKind: payload.transcript_kind ?? payload.transcriptKind ?? null,
    sourceLabel: payload.source_label ?? payload.sourceLabel ?? "선택된 소스",
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
    voiceIsolationEnabled: payload.voice_isolation ?? payload.voiceIsolationEnabled ?? false,
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
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeError, setYoutubeError] = useState<string | null>(null);
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
      setYoutubeUrl(next.sourceUrl ?? "");
      setYoutubeError(null);
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
  const canGenerate = Boolean(snapshot?.sourceUrl || snapshot?.projectPath) && !jobBusy;
  const activeVoiceIsolation = snapshot?.voiceIsolationEnabled ?? false;
  const displayedVoiceIsolation = jobBusy ? activeVoiceIsolation : voiceIsolationEnabled;
  const generateLabel = jobBusy ? "생성 중" : "다시 생성";
  const generationActive = GENERATION_JOB_STATUSES.has(snapshot?.jobStatus ?? "idle");
  const activeGenerationStage = generationStageIndex(snapshot?.jobPhase, snapshot?.jobStatus ?? "idle");
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
    } catch (error) {
      const detail = error instanceof Error ? error.message : "프로젝트 폴더 선택에 실패했습니다.";
      setLiveMessage(detail);
    }
  }

  async function clearProject() {
    if ((!snapshot?.projectPath && !snapshot?.sourceUrl) || jobBusy) return;
    setLiveMessage("현재 인터뷰 선택을 비웁니다.");
    try {
      if (isDemoMode()) {
        applySnapshot(makeEmptySnapshot("connected"));
      } else {
        const response = await apiMutation("/api/snapshot", { method: "DELETE" });
        applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
      }
      setYoutubeUrl("");
      setLiveMessage("인터뷰 선택을 비웠습니다. 기존 작업 파일은 유지됩니다.");
    } catch {
      setLiveMessage("프로젝트 선택을 비우지 못했습니다.");
    }
  }

  async function startProjectJob(projectPath: string) {
    if (voiceIsolationEnabled && !voiceIsolationConfigured) {
      const message = "Voice Isolation + Speech Enhancement를 사용하려면 설정에서 ElevenLabs API 키를 저장하세요.";
      setActiveTab("settings");
      setLiveMessage(message);
      throw new Error(message);
    }
    const response = await apiMutation("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_path: projectPath,
        duration_s: videoDurationS,
        n_storylines: selectedStorylineCount,
        provider: selectedProvider,
        voice_isolation: voiceIsolationEnabled,
      }),
    });
    applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
    setEventConnectionVersion((version) => version + 1);
  }

  async function startYoutubeJob(sourceUrl: string) {
    const normalized = sourceUrl.trim();
    if (!normalized) {
      const message = "YouTube 인터뷰 링크를 입력하세요.";
      setYoutubeError(message);
      setLiveMessage(message);
      return;
    }
    if (voiceIsolationEnabled && !voiceIsolationConfigured) {
      const message = "Voice Isolation + Speech Enhancement를 사용하려면 설정에서 ElevenLabs API 키를 저장하세요.";
      setActiveTab("settings");
      setLiveMessage(message);
      throw new Error(message);
    }
    setYoutubeError(null);
    setLiveMessage("YouTube 영상 정보와 자막을 확인합니다.");
    const response = await apiMutation("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: normalized,
        duration_s: videoDurationS,
        n_storylines: selectedStorylineCount,
        provider: selectedProvider,
        voice_isolation: voiceIsolationEnabled,
      }),
    });
    applySnapshot(normalizeSnapshot((await response.json()) as ApiSnapshot));
    setEventConnectionVersion((version) => version + 1);
  }

  function submitYoutube(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (jobBusy) return;
    if (isDemoMode()) {
      setLiveMessage("YouTube 링크로 클립 생성을 시작합니다.");
      return;
    }
    void startYoutubeJob(youtubeUrl).catch((error) => {
      const detail = error instanceof Error ? error.message : "YouTube 링크를 처리하지 못했습니다.";
      setYoutubeError(detail);
      setLiveMessage(detail);
    });
  }

  async function exportSelected() {
    if (!readySelected || !snapshot) return;
    setExportState("exporting");
    setLiveMessage(
      activeVoiceIsolation
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
      setLiveMessage("Voice Isolation + Speech Enhancement를 켜려면 ElevenLabs API 키가 필요합니다.");
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
      setLiveMessage(
        settings.enabled
          ? "Voice Isolation + Speech Enhancement가 연결되었습니다."
          : "Voice Isolation + Speech Enhancement 기본값을 껐습니다.",
      );
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
          <button type="button" className="ghost-button" onClick={chooseProject}> <FolderOpen size={17} /> CapCut 가져오기</button>
          <button
            type="button"
            className="ghost-button"
            disabled={(!snapshot.projectPath && !snapshot.sourceUrl) || jobBusy}
            onClick={clearProject}
          >
            <FolderX size={17} /> 비우기
          </button>
          <button
            type="button"
            className="ghost-button"
            disabled={!canGenerate}
            onClick={() => {
              if (!isDemoMode()) {
                if (snapshot.sourceType === "youtube" && snapshot.sourceUrl) {
                  setLiveMessage(`YouTube 인터뷰에서 클립 ${selectedStorylineCount}개 생성을 다시 시작합니다.`);
                  void startYoutubeJob(snapshot.sourceUrl).catch((error) => {
                    const detail = error instanceof Error ? error.message : "생성 요청이 실패했습니다.";
                    setYoutubeError(detail);
                    setLiveMessage(detail);
                  });
                  return;
                }
                if (snapshot.projectPath) {
                  setLiveMessage(`대표 영상 ${selectedStorylineCount}개 렌더를 시작합니다.`);
                  void startProjectJob(snapshot.projectPath).catch((error) => {
                    const detail = error instanceof Error ? error.message : "생성 요청이 실패했습니다.";
                    setLiveMessage(detail);
                  });
                  return;
                }
                setLiveMessage("먼저 YouTube 인터뷰 링크를 입력하세요.");
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

      <form className="youtube-source" onSubmit={submitYoutube} hidden={activeTab !== "dashboard"} aria-labelledby="youtube-source-title">
        <div className="youtube-source-heading">
          <span className="youtube-source-icon" aria-hidden="true"><Youtube size={20} /></span>
          <div>
            <p className="eyebrow">LONGFORM TO REELS</p>
            <h2 id="youtube-source-title">창업가 인터뷰 YouTube 링크</h2>
          </div>
        </div>
        <div className="youtube-source-entry">
          <label htmlFor="youtube-url" className="sr-only">YouTube 인터뷰 URL</label>
          <span aria-hidden="true"><Link size={17} /></span>
          <input
            id="youtube-url"
            type="url"
            inputMode="url"
            autoComplete="url"
            placeholder="https://www.youtube.com/watch?v=..."
            value={youtubeUrl}
            disabled={jobBusy}
            aria-invalid={Boolean(youtubeError)}
            aria-describedby="youtube-source-help"
            onChange={(event) => {
              setYoutubeUrl(event.target.value);
              setYoutubeError(null);
            }}
          />
          <button type="submit" disabled={jobBusy || !youtubeUrl.trim()}>
            {jobBusy && snapshot.sourceType === "youtube" ? <Loader2 size={16} className="spin" /> : <Scissors size={16} />}
            {jobBusy && snapshot.sourceType === "youtube" ? "만드는 중" : "클립 만들기"}
          </button>
        </div>
        <p id="youtube-source-help" className={youtubeError ? "youtube-source-help error" : "youtube-source-help"}>
          {youtubeError ?? "영어 인터뷰와 영어 원문 자막을 저장하고, 선택한 구간을 한국어 자막의 1분 이하 릴스로 만듭니다."}
        </p>
      </form>

      {snapshot.jobStatus === "failed" && snapshot.jobError && activeTab === "dashboard" ? (
        <section className="notice error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span><strong>클립 생성 실패</strong>{snapshot.jobError}</span>
        </section>
      ) : null}

      <section
        className={`generation-option ${displayedVoiceIsolation ? "enabled" : ""}`}
        aria-labelledby="voice-processing-title"
        hidden={activeTab !== "dashboard"}
      >
        <div className="generation-option-icon" aria-hidden="true"><AudioLines size={19} /></div>
        <div className="generation-option-copy">
          <div className="generation-option-heading">
            <p className="eyebrow">{jobBusy ? "이번 작업" : "다음 생성 옵션"}</p>
            <span>{displayedVoiceIsolation ? "적용" : "원본 유지"}</span>
          </div>
          <h2 id="voice-processing-title">Voice Isolation + Speech Enhancement</h2>
          <p>배경 소음을 줄이고 목소리의 명료도와 음량을 다듬은 뒤 최종 영상을 내보냅니다.</p>
        </div>
        <div className="generation-option-control">
          <label className="switch">
            <input
              type="checkbox"
              checked={displayedVoiceIsolation}
              disabled={jobBusy}
              onChange={(event) => {
                setVoiceIsolationEnabled(event.target.checked);
                setLiveMessage(
                  event.target.checked
                    ? "다음 생성에 Voice Isolation + Speech Enhancement를 적용합니다."
                    : "다음 생성은 원본 오디오를 유지합니다.",
                );
              }}
              role="switch"
              aria-label="다음 생성에 Voice Isolation과 Speech Enhancement 적용"
              aria-checked={displayedVoiceIsolation}
            />
            <span className="switch-track" aria-hidden="true"><Check size={15} /></span>
            <span>{displayedVoiceIsolation ? "ON" : "OFF"}</span>
          </label>
          {!voiceIsolationConfigured && voiceIsolationEnabled && !jobBusy ? (
            <button type="button" className="inline-settings-button" onClick={() => setActiveTab("settings")}>API 키 설정</button>
          ) : null}
        </div>
      </section>

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
              <h3>Voice Isolation + Speech Enhancement</h3>
              <p>ElevenLabs로 목소리를 분리한 뒤 노이즈 억제·음량 정규화·명료도 보정을 적용합니다. 저장한 ON/OFF는 다음 생성의 기본값입니다.</p>
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
                <span>기본 음성 개선 {voiceIsolationEnabled ? "ON" : "OFF"}</span>
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
        <div><strong>{subtitlesEnabled ? "ON" : "OFF"}</strong><small>클립 자막</small></div>
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

              <section className="story-structure" aria-label={`${storyline.label} 스토리 구성`}>
                <div className="story-structure-heading">
                  <strong>스토리 구성</strong>
                  <span>{storyline.sections.length > 0 ? `${storyline.sections.length}개 구간` : "구성 대기"}</span>
                </div>
                {storyline.sections.length > 0 ? (
                  <ol className="story-beats">
                    {storyline.sections.map((section, sectionIndex) => (
                      <li
                        className={section.beat.includes("훅") ? "story-beat is-hook" : "story-beat"}
                        key={`${section.beat}-${sectionIndex}`}
                      >
                        <span className="story-beat-index" aria-hidden="true">{String(sectionIndex + 1).padStart(2, "0")}</span>
                        <div className="story-beat-content">
                          <div className="story-beat-heading">
                            <strong>{section.beat}</strong>
                            <span>{section.role}</span>
                          </div>
                          <p>{section.text}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="summary">{storyline.summary}</p>
                )}
              </section>

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
              {storyline.status === "failed" ? <button type="button" disabled={jobBusy} onClick={() => retryStoryline(storyline)}>다시 시도</button> : null}
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
              ? `${selectedExportStorylines.map((storyline) => storyline.label).join(" · ")}${activeVoiceIsolation ? " · Voice + Speech 개선 ON" : ""}`
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
