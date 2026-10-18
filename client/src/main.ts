import {
  createIcons,
  Network,
  FlaskConical,
  LayoutDashboard,
  History,
  LibraryBig,
  SlidersHorizontal,
  ArrowUpRight,
  ArrowRight,
  Upload,
  Download,
  Play,
  Plus,
  Check,
  ChevronRight,
  ChevronDown,
  Dna,
  CircleHelp,
  Copy,
  RefreshCw,
  Search,
  X,
  FileText,
  CircleCheck,
  Clock,
  Menu,
  Activity,
  ArrowDownUp,
  ExternalLink,
  TriangleAlert,
  Square,
  Microscope,
} from "lucide";
import {
  api,
  post,
  upload,
  downloadURL,
  type Target,
  type Run,
  type Library,
  type Model,
  type Result,
  type Candidate,
  type Artifact,
} from "./api";
import "./tokens.css";
import "./style.css";

const icons = {
  Network,
  FlaskConical,
  LayoutDashboard,
  History,
  LibraryBig,
  SlidersHorizontal,
  ArrowUpRight,
  ArrowRight,
  Upload,
  Download,
  Play,
  Plus,
  Check,
  ChevronRight,
  ChevronDown,
  Dna,
  CircleHelp,
  Copy,
  RefreshCw,
  Search,
  X,
  FileText,
  CircleCheck,
  Clock,
  Menu,
  Activity,
  ArrowDownUp,
  ExternalLink,
  TriangleAlert,
  Square,
  Microscope,
};
const icon = (name: string, cls = "") =>
  `<i data-lucide="${name}" class="${cls}" aria-hidden="true"></i>`;
const h = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const fmt = (v: unknown, places = 2) =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(places) : "—";
const active = (r: Run) =>
  ["queued", "running", "cancel_requested"].includes(r.status);
const statusNames: Record<string, string> = {
  queued: "대기 중",
  running: "계산 중",
  succeeded: "완료",
  failed: "실패",
  cancel_requested: "취소 중",
  cancelled: "취소됨",
};
const kindNames: Record<string, string> = {
  design: "파트너 설계",
  orthogonal: "직교 세트",
  structure: "구조 분석",
  calibration: "모델 보정",
  export: "결과 내보내기",
  dockprep: "도킹 준비",
};
const badge = (status: string) =>
  `<span class="badge ${h(status)}"><span></span>${h(statusNames[status] || status)}</span>`;
const date = (ts: number) =>
  new Date(ts * 1000).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
const $ = <T extends HTMLElement>(selector: string) =>
  document.querySelector<T>(selector)!;
const terminal = ["succeeded", "failed", "cancelled"];

class ProteinLab {
  root = $("#app");
  targets: Target[] = [];
  runs: Run[] = [];
  libraries: Library[] = [];
  models: Model[] = [];
  targetId = "";
  modelId = "default";
  libraryId = "default";
  runId = "";
  result: Result | null = null;
  artifacts: Artifact[] = [];
  resultTitle = "";
  resultTarget: Target | undefined;
  resultKind = "";
  resultKey = "";
  selected = new Set<string>();
  inspected = "";
  sort: "specificity" | "hetero" | "name" = "specificity";
  ascending = true;
  worker = false;
  connected = false;
  loaded = false;
  refreshing = false;
  pending = false;
  revision = 0;
  page = location.hash.slice(1) || "workspace";
  inputTab = "sequence";
  mode = "design";
  search = "";
  name = "";
  sequence = "";
  offset = "auto";
  chain = "";
  file: File | null = null;
  settings = {
    steps: "4000",
    restarts: "8",
    seed: "",
    pairs: "2",
    margin: "3",
    partnerOffset: "0",
    fixed: true,
  };
  catalogFile: File | null = null;
  calibrationFile: File | null = null;
  libraryView = "default";
  menuOpen = false;

  constructor() {
    this.root.addEventListener("click", (e) => {
      void this.click(e);
    });
    this.root.addEventListener("input", (e) => this.input(e));
    this.root.addEventListener("change", (e) => {
      void this.change(e);
    });
    this.root.addEventListener("submit", (e) => {
      e.preventDefault();
      void this.submitForm((e.target as HTMLFormElement).id);
    });
    this.root.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const tab = (e.target as Element).closest<HTMLElement>('[role="tab"]');
      if (tab) {
        e.preventDefault();
        this.inputTab = this.inputTab === "sequence" ? "file" : "sequence";
        this.renderPage();
        document
          .querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
          ?.focus();
      }
    });
    window.addEventListener("hashchange", () => {
      this.page = location.hash.slice(1) || "workspace";
      this.menuOpen = false;
      this.render();
    });
    this.render();
    void this.refresh(true);
    window.setInterval(() => {
      if (!document.hidden) void this.refresh();
    }, 2000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void this.refresh();
    });
  }

  get target() {
    return this.targets.find((t) => t.id === this.targetId);
  }
  get run() {
    return this.runs.find((r) => r.id === this.runId);
  }
  get rows(): Candidate[] {
    return this.result?.candidates || [];
  }
  paintIcons() {
    createIcons({ icons, attrs: { "stroke-width": 1.7 } });
  }
  notify(text: string, isError = false) {
    const el = document.createElement("div");
    el.className = `toast ${isError ? "toast-error" : ""}`;
    el.role = isError ? "alert" : "status";
    el.textContent = text;
    $("#notifications").replaceChildren(el);
    setTimeout(() => el.remove(), isError ? 6500 : 4000);
  }
  async perform(fn: () => Promise<void>) {
    if (this.pending) return;
    this.pending = true;
    this.revision++;
    this.togglePending();
    try {
      await fn();
    } catch (e) {
      this.notify(
        e instanceof Error ? e.message : "요청에 실패했습니다.",
        true,
      );
    } finally {
      this.pending = false;
      this.togglePending();
    }
  }
  togglePending() {
    document.querySelectorAll<HTMLButtonElement>("[data-busy]").forEach((b) => {
      b.disabled =
        this.pending ||
        (b.dataset.action === "screen" && !this.target) ||
        (b.form?.id === "design-form" &&
          this.mode === "design" &&
          !this.target);
      b.classList.toggle("busy", this.pending);
    });
  }
  async refresh(initial = false) {
    if (this.refreshing) return;
    this.refreshing = true;
    const revision = this.revision;
    try {
      const [targets, runs, libraries, models, health] = await Promise.all([
        api<Target[]>("/targets?limit=500"),
        api<Run[]>("/runs?limit=200"),
        api<Library[]>("/libraries"),
        api<Model[]>("/models"),
        fetch("/api/v1/health/ready").then((r) => r.json()),
      ]);
      if (revision !== this.revision) return;
      const old = this.run;
      this.targets = targets;
      this.runs = runs;
      this.libraries = libraries;
      this.models = models;
      this.connected = true;
      this.worker = health.ready === true;
      this.loaded = true;
      if (initial) {
        this.targetId = targets.at(-1)?.id || "";
        const latest = runs.find(
          (r) =>
            ["design", "orthogonal"].includes(r.kind) &&
            r.status === "succeeded",
        );
        if (latest) {
          this.runId = latest.id;
          this.targetId = latest.request.target_id || this.targetId;
        }
        this.render();
      } else {
        this.renderStatus();
        this.renderMetrics();
        if (this.page === "history") this.renderPage();
      }
      if (this.run?.status === "succeeded" && this.resultKey !== this.run.id)
        await this.loadRunResult();
      if (
        old &&
        old.status !== this.run?.status &&
        this.run &&
        terminal.includes(this.run.status)
      ) {
        this.notify(
          `${kindNames[this.run.kind]} ${statusNames[this.run.status]}`,
          this.run.status === "failed",
        );
        if (this.page === "models") this.renderPage();
      }
    } catch {
      this.connected = false;
      this.worker = false;
      this.loaded = true;
      this.renderStatus();
      if (initial) this.render();
    } finally {
      this.refreshing = false;
    }
  }

  render() {
    const nav = [
      ["workspace", "layout-dashboard", "파트너 탐색"],
      ["history", "history", "실행 이력"],
      ["libraries", "library-big", "서열 라이브러리"],
      ["models", "sliders-horizontal", "모델 보정"],
    ];
    this.root.innerHTML = `
      <header class="topbar">
        <button class="icon-button mobile-menu" data-action="menu" aria-label="탐색 메뉴" aria-expanded="${this.menuOpen}">${icon("menu")}</button>
        <a href="#workspace" class="brand">${icon("network")}<span>Protein Lab</span></a>
        <span class="brand-divider"></span><span class="product-name">LZ Research <span>류신 지퍼 연구 워크스페이스</span></span>
        <div class="topbar-right"><div id="connection"></div><a class="icon-button" href="/docs" target="_blank" aria-label="API 문서 열기" title="API 문서">${icon("circle-help")}</a><span class="local-avatar" title="로컬 연구 환경">PL</span></div>
      </header>
      <div class="app-layout">
        <aside class="sidebar ${this.menuOpen ? "open" : ""}">
          <div class="workspace-label">RESEARCH WORKSPACE</div>
          <nav aria-label="주요 탐색">${nav.map(([id, i, label]) => `<a class="nav-link ${this.page === id ? "active" : ""}" href="#${id}" ${this.page === id ? 'aria-current="page"' : ""}>${icon(i)}${label}${id === "history" ? `<span class="nav-count" aria-hidden="true">${this.runs.filter(active).length || ""}</span>` : ""}</a>`).join("")}</nav>
          <div class="sidebar-project"><span class="eyebrow">CURRENT RESEARCH</span><div>${icon("dna")}<strong>Leucine zipper</strong></div><p>평행 이중나선의<br>선택적 결합 파트너 설계</p><span class="mini-tag">COILED-COIL · 2-STRANDED</span></div>
          <div class="sidebar-footer"><div class="helix-mark" aria-hidden="true">${this.helixGraphic()}</div><span class="eyebrow blue">01 / COBALT RESEARCH</span><p>서열에서 시작해,<br>더 정교한 연결을 설계합니다.</p><span class="local-note">${icon("square")} 로컬 연구 환경</span></div>
        </aside>
        <main id="main-content" tabindex="-1"><div id="page"></div><footer class="page-footer"><span>Protein Lab <b>·</b> Leucine Zipper Research</span><span>계산 결과는 후보 탐색을 위한 순위입니다.</span></footer></main>
      </div>`;
    this.renderPage();
    this.renderStatus();
    this.paintIcons();
    this.togglePending();
  }
  helixGraphic() {
    // Schematic, not a molecular structure or predicted conformation.
    return `<svg viewBox="0 0 150 160" fill="none"><path d="M46 8C123 33 23 48 103 77S26 123 102 150" stroke="#d5e3fc" stroke-width="17"/><path d="M101 8C25 33 124 48 45 77S122 123 46 150" stroke="#87a9ed" stroke-width="17"/><path d="M101 8C25 33 124 48 45 77S122 123 46 150" stroke="#2459d3" stroke-width="2"/>${[24, 53, 83, 113, 140].map((y) => `<path d="M49 ${y}L99 ${y + 6}" stroke="#c3d3f0" stroke-width="2"/>`).join("")}</svg>`;
  }
  renderStatus() {
    const el = document.getElementById("connection");
    if (el)
      el.innerHTML = `<span class="connection ${this.connected && this.worker ? "online" : "offline"}"><span></span>${!this.loaded ? "연결 확인 중" : !this.connected ? "서버 연결 끊김" : this.worker ? "연구 워커 연결됨" : "워커 연결 대기"}</span>`;
    const navCount = document.querySelector(".nav-count");
    if (navCount)
      navCount.textContent = String(this.runs.filter(active).length || "");
    document
      .querySelectorAll<HTMLElement>(".workflow-step")
      .forEach((step, i) => {
        const done = !!((this.target && i < 2) || (this.result && i === 2));
        const current = this.result ? i === 3 : this.target ? i === 2 : i === 0;
        step.classList.toggle("done", done);
        step.classList.toggle("current", current);
        const index = step.querySelector(".step-index");
        if (index) index.innerHTML = done ? icon("check") : String(i + 1);
      });
    const runBox = document.getElementById("run-status");
    if (runBox) runBox.innerHTML = this.runStatus();
    const banner = document.getElementById("offline-banner");
    if (banner)
      banner.innerHTML =
        !this.connected && this.loaded
          ? `<div class="notice error">${icon("triangle-alert")} 서버 연결이 끊겼습니다. 자동으로 다시 연결합니다.<button data-action="refresh" class="text-button">다시 연결</button></div>`
          : "";
    this.paintIcons();
  }
  renderMetrics() {
    const el = document.getElementById("metrics");
    if (el) el.innerHTML = this.metrics();
  }
  metrics() {
    const items = [
      ["dna", this.targets.length, "등록 표적"],
      [
        "circle-check",
        this.runs.filter((r) => r.status === "succeeded").length,
        "완료된 실행",
      ],
      ["clock", this.runs.filter(active).length, "진행 / 대기"],
    ];
    return items
      .map(
        ([i, n, l]) =>
          `<div class="metric">${icon(String(i))}<div><span>${l}</span><strong>${this.loaded ? n : "—"}<small>개</small></strong></div></div>`,
      )
      .join("");
  }
  renderPage() {
    const focused = document.activeElement as HTMLInputElement | null;
    const searchFocus = focused?.id === "history-search";
    const selection = searchFocus ? focused!.selectionStart : null;
    const pages: Record<string, () => string> = {
      workspace: () => this.workspace(),
      history: () => this.history(),
      libraries: () => this.libraryPage(),
      models: () => this.modelPage(),
    };
    $("#page").innerHTML = (pages[this.page] || pages.workspace)();
    if (this.page === "workspace") {
      this.renderResults();
      this.renderStatus();
    }
    if (searchFocus && this.page === "history") {
      const input = $<HTMLInputElement>("#history-search");
      input.focus({ preventScroll: true });
      input.setSelectionRange(selection, selection);
    }
    this.paintIcons();
    this.togglePending();
  }
  heading(section: string, title: string, description: string, actions = "") {
    return `<div class="breadcrumb">단백질 분석 ${icon("chevron-right")} ${section}</div><div class="page-heading"><div><div class="eyebrow blue">LEUCINE ZIPPER RESEARCH</div><h1>${title}</h1><p>${description}</p></div>${actions}</div>`;
  }
  workspace() {
    return `${this.heading("파트너 탐색", "류신 지퍼 파트너 탐색", "표적 나선에 강하게, 그리고 선택적으로 결합하는 파트너를 설계합니다.", `<div id="metrics" class="metrics">${this.metrics()}</div>`)}
      <div id="offline-banner"></div>
      <div class="workflow" aria-label="연구 진행 단계">${[
        ["표적 준비", "서열 또는 구조 입력"],
        ["계면 분석", "헵타드 레지스터 확인"],
        ["파트너 탐색", "스크리닝 · 신규 설계"],
        ["결과 검토", "특이성 비교 · 내보내기"],
      ]
        .map(
          ([title, sub], i) =>
            `<div class="workflow-step ${(this.target && i < 2) || (this.result && i === 2) ? "done" : ""} ${this.result ? (i === 3 ? "current" : "") : this.target && i === 2 ? "current" : !this.target && i === 0 ? "current" : ""}"><span class="step-index">${(this.target && i < 2) || (this.result && i === 2) ? icon("check") : i + 1}</span><div><strong>${title}</strong><small>${sub}</small></div>${i < 3 ? icon("chevron-right", "step-chevron") : ""}</div>`,
        )
        .join("")}</div>
      <div class="setup-grid">
        <section class="panel target-panel"><div class="panel-heading"><h2>${icon("dna")} 표적 나선</h2><span class="section-number">01 / TARGET</span></div>
          <div class="saved-target"><label for="saved-target">등록된 표적</label><select id="saved-target"><option value="">새 표적 등록</option>${this.targets.map((t) => `<option value="${h(t.id)}" ${t.id === this.targetId ? "selected" : ""}>${h(t.name)} · ${t.sequence.length} aa</option>`).join("")}</select></div>
          <div class="tabs" role="tablist" aria-label="표적 입력 방식"><button role="tab" aria-selected="${this.inputTab === "sequence"}" data-action="input-tab" data-value="sequence" class="${this.inputTab === "sequence" ? "selected" : ""}">서열 입력</button><button role="tab" aria-selected="${this.inputTab === "file"}" data-action="input-tab" data-value="file" class="${this.inputTab === "file" ? "selected" : ""}">PDB / FASTA 가져오기</button></div>
          <form id="target-form"><div class="two-fields"><label>표적 이름<input id="target-name" value="${h(this.name)}" placeholder="예: GCN4-p1" maxlength="120" required /></label><label class="short-field">${this.inputTab === "sequence" ? "시작 레지스터" : "표적 사슬 (선택)"}${
            this.inputTab === "sequence"
              ? `<select id="target-offset"><option value="auto">자동 예측</option>${"abcdefg"
                  .split("")
                  .map(
                    (p, i) =>
                      `<option value="${i}" ${this.offset === String(i) ? "selected" : ""}>${p} · offset ${i}</option>`,
                  )
                  .join("")}</select>`
              : `<input id="target-chain" value="${h(this.chain)}" placeholder="예: A" maxlength="1" />`
          }</label></div>
          ${this.inputTab === "sequence" ? `<div class="sequence-label"><label for="target-sequence">아미노산 서열</label><button class="text-button" type="button" data-action="demo">GCN4 예제 <span class="demo-label">DEMO</span></button></div><textarea id="target-sequence" class="sequence-input" placeholder="1-letter 아미노산 서열을 입력하세요" required spellcheck="false" maxlength="1000">${h(this.sequence)}</textarea><div class="field-note"><span>공백과 줄바꿈은 자동으로 정리됩니다.</span><span id="residue-count">${this.sequence.replace(/\s/g, "").length} aa</span></div>` : `<label class="dropzone" for="target-file">${icon("upload")}<strong>${h(this.file?.name || "구조 또는 서열 파일 선택")}</strong><span>PDB, FASTA, TXT · 최대 5 MiB</span><input id="target-file" type="file" accept=".pdb,.fasta,.fa,.faa,.txt" ${this.file ? "" : "required"} /></label>`}
          <div class="panel-actions"><span class="subtle">${icon("file-text")} 원본과 분석 근거를 함께 보관</span><button type="submit" class="button secondary" data-busy>${icon("plus")} 표적 등록 · 분석</button></div></form>
        </section>
        <section class="panel design-panel"><div class="panel-heading"><h2>${icon("flask-conical")} 탐색 설정</h2><span class="section-number">02 / DISCOVERY</span></div>
          <form id="design-form"><div class="mode-options"><label class="mode-option ${this.mode === "design" ? "chosen" : ""}"><input type="radio" name="mode" value="design" ${this.mode === "design" ? "checked" : ""}/><span><strong>파트너 설계</strong><small>표적에 맞는 새로운 나선 탐색</small></span></label><label class="mode-option ${this.mode === "orthogonal" ? "chosen" : ""}"><input type="radio" name="mode" value="orthogonal" ${this.mode === "orthogonal" ? "checked" : ""}/><span><strong>직교 세트 설계</strong><small>교차 결합을 억제하는 쌍 설계</small></span></label></div>
          <div class="two-fields"><label>점수 모델<select id="model-select">${this.models.map((m) => `<option value="${h(m.id)}" ${this.modelId === m.id ? "selected" : ""}>${h(m.id === "default" ? "기본 모델 · 미보정" : m.name)}</option>`).join("")}</select></label><label>라이브러리<select id="library-select">${this.libraries.map((l) => `<option value="${h(l.id)}" ${this.libraryId === l.id ? "selected" : ""}>${h(l.name)} · ${l.members.length}개</option>`).join("")}</select></label></div>
          <div class="parameter-grid"><label>독립 탐색 수<input id="restarts" type="number" min="1" max="${this.mode === "design" ? 32 : 16}" value="${h(this.settings.restarts)}" required/></label><label>탐색 단계 수<input id="steps" type="number" min="1" max="20000" value="${h(this.settings.steps)}" required/></label><label>Seed <span class="optional">선택</span><input id="seed" type="number" min="0" max="9007199254740991" value="${h(this.settings.seed)}" placeholder="자동 생성"/></label>${
            this.mode === "orthogonal"
              ? `<label>직교 쌍 수<input id="pairs" type="number" min="1" max="4" value="${h(this.settings.pairs)}" required/></label><label>최소 마진<input id="margin" type="number" min="0.1" max="20" step="0.1" value="${h(this.settings.margin)}" required/></label><label class="check-field"><input id="fixed-target" type="checkbox" ${this.settings.fixed ? "checked" : ""}/> 표적 나선 고정</label>`
              : `<label>파트너 시작 위치<select id="partnerOffset">${"abcdefg"
                  .split("")
                  .map(
                    (v, i) =>
                      `<option value="${i}" ${this.settings.partnerOffset === String(i) ? "selected" : ""}>${v} · offset ${i}</option>`,
                  )
                  .join("")}</select></label>`
          }</div>
          <div class="model-note">${icon("circle-help")} 결합 점수와 경쟁 호모다이머를 함께 평가합니다.</div>
          <div class="panel-actions"><button type="button" data-action="screen" class="button secondary" data-busy ${!this.target ? "disabled" : ""}>${icon("search")} 라이브러리 스크리닝</button><button type="submit" class="button primary" data-busy ${this.mode === "design" && !this.target ? "disabled" : ""}>${icon("play")} 설계 실행</button></div></form>
        </section>
      </div>
      <div id="run-status">${this.runStatus()}</div>
      <div id="results"></div>
      <div class="detail-grid"><section class="panel"><div class="panel-heading"><h2>표적 서열 · 레지스터</h2><button class="button small secondary" data-action="copy-target" ${!this.target ? "disabled" : ""}>${icon("copy")} FASTA 복사</button></div><div id="target-detail">${this.sequencePanel()}</div></section><section class="panel research-note"><div class="panel-heading"><h2>분석 근거</h2><span class="section-number">RESEARCH NOTES</span></div>${this.target ? `<dl><div><dt>표적</dt><dd>${h(this.target.name)}</dd></div><div><dt>레지스터 근거</dt><dd>${this.target.register_source === "structure" ? "구조 좌표 측정" : this.target.register_source === "explicit" ? "사용자 지정" : "서열 기반 예측"}</dd></div><div><dt>구조 적합도</dt><dd>${fmt(this.target.register_fit, 3)}</dd></div><div><dt>모델 범위</dt><dd>평행 이중나선 coiled-coil</dd></div></dl>${this.target.register_source === "structure" && this.target.input_id ? `<div class="structure-actions"><button class="button small secondary" data-action="structure" data-busy>${icon("refresh-cw")} 구조 재분석</button><button class="button small secondary" data-action="dockprep" data-busy>${icon("download")} 도킹 입력 준비</button></div>` : ""}${this.target.warnings.map((w) => `<p class="warning-text">${icon("triangle-alert")}${h(w)}</p>`).join("")}` : `<div class="empty-small">표적을 등록하면 분석 근거와 구조 경고를 확인할 수 있습니다.</div>`}<p class="note-footer">순위 점수는 결합 에너지나 실험적 친화도를 의미하지 않습니다.</p></section></div>`;
  }
  sequencePanel() {
    const t = this.target;
    if (!t)
      return `<div class="empty-small">${icon("dna")}아직 등록된 표적이 없습니다.<span>서열을 입력하거나 PDB 구조를 가져오세요.</span></div>`;
    return `<div class="sequence-meta"><span>길이 <strong>${t.sequence.length} aa</strong></span><span>시작 위치 <strong>${"abcdefg"[t.offset]}</strong></span><span>신뢰도 차이 <strong>${fmt(t.confidence, 3)}</strong></span>${t.orientation ? `<span>배향 <strong>${h(t.orientation)}</strong></span>` : ""}</div><div class="sequence-view">${Array.from(
      { length: Math.ceil(t.sequence.length / 50) },
      (_, i) =>
        `<div><span class="residue-number">${i * 50 + 1}</span><code>${t.sequence
          .slice(i * 50, i * 50 + 50)
          .split("")
          .map((r, j) => {
            const p = "abcdefg"[(t.offset + i * 50 + j) % 7];
            return `<span class="residue ${p === "a" || p === "d" ? "core" : p === "e" || p === "g" ? "charge" : ""}" title="${i * 50 + j + 1}: ${r} / ${p}">${r}</span>`;
          })
          .join(
            "",
          )}</code></div><div class="register-row"><span></span><code>${h(t.positions.slice(i * 50, i * 50 + 50))}</code></div>`,
    ).join(
      "",
    )}</div><div class="sequence-legend"><span><i class="legend-core"></i>a / d 코어</span><span><i class="legend-charge"></i>e / g 계면 전하</span><span>나머지: 용매 노출 위치</span></div>`;
  }
  runStatus() {
    const r = this.run;
    if (!r) return "";
    return `<div class="run-strip ${r.status === "failed" ? "run-error" : ""}"><div class="run-strip-title">${icon(active(r) ? "activity" : r.status === "succeeded" ? "circle-check" : "clock")}<strong>${kindNames[r.kind] || h(r.kind)}</strong>${badge(r.status)}<span class="run-short-id">${h(r.id.slice(0, 16))}</span></div><div class="run-progress">${active(r) ? `<progress max="1" value="${r.progress}" aria-label="설계 진행률"></progress><span>${Math.round(r.progress * 100)}%</span>` : `<span>${r.status === "failed" ? h(r.error?.message) : r.status === "succeeded" ? "결과와 재현 정보를 저장했습니다." : "실행이 취소되었습니다."}</span>`}</div>${active(r) ? `<button class="button small secondary" data-action="cancel" data-id="${h(r.id)}" ${r.status === "cancel_requested" ? "disabled" : ""}>${icon("x")} 취소</button>` : ["failed", "cancelled"].includes(r.status) ? `<button class="button small secondary" data-action="retry" data-id="${h(r.id)}">${icon("refresh-cw")} 다시 실행</button>` : ""}</div>`;
  }
  renderResults() {
    const el = document.getElementById("results");
    if (!el) return;
    if (!this.result) {
      el.innerHTML = `<section class="panel result-empty"><div>${icon("microscope")}</div><h2>${this.run && active(this.run) ? "파트너를 탐색하고 있습니다" : "다음 연결을 발견할 준비가 되었습니다"}</h2><p>${this.run && active(this.run) ? "계산이 완료되면 후보와 비교 결과가 자동으로 표시됩니다." : "표적을 등록한 뒤 라이브러리를 스크리닝하거나 새로운 파트너를 설계하세요."}</p><span class="empty-flow">표적 나선 ${icon("arrow-right")} 후보 탐색 ${icon("arrow-right")} 특이성 비교</span></section>`;
      this.paintIcons();
      return;
    }
    const r = this.result;
    const table = this.rows.length
      ? this.candidateTable()
      : r.matrix
        ? this.matrixPanel()
        : this.genericResult();
    el.innerHTML = `<section class="panel results-panel"><div class="panel-heading result-heading"><div><h2>${h(this.resultTitle || "분석 결과")}</h2><span class="result-context">${h(this.resultTarget?.name || (r.matrix ? "전체 공동 설계" : ""))}${this.rows.length ? ` · ${this.rows.length}개 후보` : ""}</span></div><div class="result-actions">${this.rows.length ? `<button data-action="sort" class="button secondary small">${icon("arrow-down-up")} 특이성 ${this.ascending ? "↑" : "↓"}</button><button class="button secondary small" data-action="export-csv">${icon("download")} CSV <span id="selected-count">${this.selected.size}</span></button>` : ""}${this.artifacts.length ? `<details class="download-menu"><summary class="button primary small">${icon("download")} 결과 파일 ${icon("chevron-down")}</summary><div>${this.artifacts.map((a) => `<a href="${downloadURL(a.id)}" download>${icon("file-text")}<span>${h(a.name)}</span><small>${Math.ceil(a.size / 1024)} KB</small></a>`).join("")}</div></details>` : ""}</div></div>
      ${this.rows.length ? `<div class="result-grid"><div class="table-area">${table}</div><section class="comparison-panel"><div class="chart-title"><h3>상호작용 점수 비교</h3><span>낮을수록 유리</span></div>${this.comparisonChart()}<div class="chart-legend"><span><i class="blue-dot"></i>이종이량체</span><span><i class="gray-dot"></i>후보 호모다이머</span></div><div class="chart-note">${icon("circle-help")} 두 점 사이의 차이를 비교하세요.<br>상대 순위이며 측정된 결합 에너지가 아닙니다.</div></section></div>` : table}
      ${this.rows.length ? `<div class="result-footnote">${icon("circle-help")}${this.resultKind === "screen" ? "특이성 = 이종이량체 − 후보 호모다이머. ‘양쪽 기준’은 표적 호모다이머까지 비교합니다." : "특이성 = 이종이량체 − 두 호모다이머 중 더 강한 경쟁자. 음수일수록 유리합니다."}</div><div id="candidate-detail">${this.candidateDetail()}</div>` : ""}
      ${(r.warnings || []).length ? `<div class="result-warnings">${r.warnings!.map((w) => `<span>${icon("circle-help")}${h(w)}</span>`).join("")}</div>` : ""}</section>`;
    this.paintIcons();
  }
  sortedRows() {
    return [...this.rows].sort((a, b) => {
      const v =
        this.sort === "name"
          ? a.name.localeCompare(b.name)
          : a[this.sort] - b[this.sort];
      return this.ascending ? v : -v;
    });
  }
  candidateTable() {
    return `<div class="table-scroll"><table class="candidate-table"><thead><tr><th class="check-cell"><input type="checkbox" aria-label="후보 전체 선택" data-select-all ${this.rows.length && this.selected.size === this.rows.length ? "checked" : ""}/></th><th><button data-action="sort-name">후보</button></th><th class="numeric">결합 점수</th><th class="numeric">호모 점수</th><th class="numeric"><button data-action="sort">특이성</button></th>${this.resultKind === "screen" ? '<th class="numeric">양쪽 기준</th>' : ""}<th>모델 판정</th></tr></thead><tbody>${this.sortedRows()
      .map(
        (c, i) =>
          `<tr class="${this.inspected === c.name ? "inspected" : ""}"><td class="check-cell"><input type="checkbox" aria-label="${h(c.name)} 선택" data-candidate="${h(c.name)}" ${this.selected.has(c.name) ? "checked" : ""}/></td><td><button class="candidate-name" data-action="inspect" data-name="${h(c.name)}"><span class="row-index">${String(i + 1).padStart(2, "0")}</span>${h(c.name)}</button><small class="sequence-preview">${h(c.sequence.slice(0, 16))}…</small></td><td class="numeric">${fmt(c.hetero)}</td><td class="numeric">${fmt(c.candidate_self)}</td><td class="numeric ${c.specificity < 0 ? "good-number" : ""}">${fmt(c.specificity)}</td>${this.resultKind === "screen" ? `<td class="numeric ${c.specificity_both! < 0 ? "good-number" : ""}">${fmt(c.specificity_both)}</td>` : ""}<td><span class="verdict ${c.specificity < 0 ? "good" : "neutral"}">${icon(c.specificity < 0 ? "circle-check" : "clock")}${c.specificity < 0 ? "후보 우세" : "경쟁 우세"}</span></td></tr>`,
      )
      .join("")}</tbody></table></div>`;
  }
  comparisonChart() {
    const rows = this.sortedRows().slice(0, 10);
    if (!rows.length) return "";
    const values = rows.flatMap((r) => [r.hetero, r.candidate_self]);
    const min = Math.floor(Math.min(...values) - 1),
      max = Math.ceil(Math.max(...values) + 1);
    const width = 450,
      height = 60 + rows.length * 43;
    const x = (v: number) => 110 + ((v - min) / (max - min)) * 310;
    return `<svg class="score-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="후보별 이종이량체와 호모다이머 점수 비교"><title>실제 계산 점수 비교. 낮을수록 유리합니다.</title>${Array.from(
      { length: 5 },
      (_, i) => {
        const v = min + ((max - min) * i) / 4;
        return `<line x1="${x(v)}" y1="20" x2="${x(v)}" y2="${height - 35}" stroke="#e7edf5"/><text x="${x(v)}" y="${height - 12}" text-anchor="middle" class="chart-axis">${v.toFixed(1)}</text>`;
      },
    ).join("")}${rows
      .map((c, i) => {
        const y = 38 + i * 43;
        return `<text x="98" y="${y + 4}" text-anchor="end" class="chart-row-label">${h(c.name.length > 13 ? c.name.slice(0, 12) + "…" : c.name)}</text><line x1="${x(c.hetero)}" x2="${x(c.candidate_self)}" y1="${y}" y2="${y}" stroke="#bdd0f7" stroke-width="3"/><circle cx="${x(c.candidate_self)}" cy="${y}" r="5" fill="#a2aec1"><title>${h(c.name)} 호모다이머 ${fmt(c.candidate_self)}</title></circle><circle cx="${x(c.hetero)}" cy="${y}" r="5" fill="#2459d3"><title>${h(c.name)} 이종이량체 ${fmt(c.hetero)}</title></circle>`;
      })
      .join("")}</svg>`;
  }
  candidateDetail() {
    const c = this.rows.find((r) => r.name === this.inspected);
    if (!c) return "";
    return `<div class="candidate-detail"><div><strong>${h(c.name)}</strong><span>${c.sequence.length} aa · 선택 후보 서열</span></div><code>${h(c.sequence)}</code><button data-action="copy-candidate" class="button small secondary">${icon("copy")} FASTA 복사</button></div>`;
  }
  matrixPanel() {
    const r = this.result!,
      names = r.names!,
      matrix = r.matrix!;
    const values = matrix.flat(),
      min = Math.min(...values),
      max = Math.max(...values);
    return `<div class="orthogonal-layout"><div class="matrix-block"><h3>전체 상호작용 행렬 <span>허용 shift 최종 재평가</span></h3><div class="table-scroll"><table class="matrix-table"><thead><tr><th></th>${names.map((n) => `<th>${h(n)}</th>`).join("")}</tr></thead><tbody>${names.map((n, i) => `<tr><th>${h(n)}</th>${names.map((_, j) => `<td style="background:rgba(36,89,211,${0.03 + (0.25 * (max - matrix[i][j])) / (max - min || 1)})" class="${j === (i % 2 === 0 ? i + 1 : i - 1) ? "cognate" : ""}" title="shift ${r.shifts?.[i]?.[j] ?? 0}">${fmt(matrix[i][j])}${j === (i % 2 === 0 ? i + 1 : i - 1) ? "<span>*</span>" : ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="subtle">* 의도한 결합 쌍 · 대각선은 호모다이머</p></div><div class="pair-summary"><span class="eyebrow">SET EVALUATION</span><h3 class="${r.evaluation?.passed ? "good-number" : ""}">${r.evaluation?.passed ? "설계 마진 충족" : "설계 마진 미충족"}</h3>${r.pairs?.map((p) => `<div class="pair-row"><strong>${h(p.names.join(" / "))}</strong><span>최종 마진 <b>${fmt(p.margin)}</b></span><small>최강 경쟁자: ${h(p.worst_competitor[1])} / ${h(p.worst_competitor[2])}</small></div>`).join("")}<p class="subtle">계산 완료와 직교 조건 충족은 별도로 판정합니다.</p></div></div><div class="set-sequences">${names.map((n, i) => `<div><strong>${h(n)}</strong><code>${h(r.sequences?.[i])}</code></div>`).join("")}</div>`;
  }
  genericResult() {
    const r = this.result!;
    if (r.model)
      return `<div class="generic-result"><h3>보정 모델 저장 완료</h3><p>학습 데이터 ${r.model.metrics?.n}개 · R² ${fmt(r.model.metrics?.r2, 3)} · RMSE ${fmt(r.model.metrics?.rmse)} °C</p><p class="subtle">학습 오차이며 독립 검증 성능이 아닙니다.</p><a href="#models" class="button secondary">보정 모델 확인 ${icon("arrow-right")}</a></div>`;
    return `<div class="generic-result"><h3>${h(this.resultTitle)}</h3><dl>${[
      ["배향", r.orientation],
      [
        "레지스터 적합도",
        typeof r.register_fit === "number" ? fmt(r.register_fit, 3) : null,
      ],
      ["시작 위치", typeof r.offset === "number" ? "abcdefg"[r.offset] : null],
    ]
      .filter(([, v]) => v != null)
      .map(([label, v]) => `<div><dt>${label}</dt><dd>${h(v)}</dd></div>`)
      .join(
        "",
      )}</dl>${r.sequence ? `<code>${h(r.sequence)}</code>` : ""}<p class="subtle">전체 결과와 입력 근거는 결과 파일에서 내려받을 수 있습니다.</p></div>`;
  }
  history() {
    const filtered = this.runs.filter((r) =>
      `${r.id} ${kindNames[r.kind]} ${r.snapshot.target?.name || ""} ${statusNames[r.status]}`
        .toLowerCase()
        .includes(this.search.toLowerCase()),
    );
    return `${this.heading("실행 이력", "연구 실행 이력", "입력과 설정, 실행 결과를 한곳에서 추적합니다.", `<button class="button secondary" data-action="refresh">${icon("refresh-cw")} 새로고침</button>`)}<section class="panel"><div class="panel-heading"><h2>최근 실행 <span class="count">${this.runs.length}</span></h2><label class="search-field">${icon("search")}<input id="history-search" placeholder="표적, 분석 종류, 상태 검색" aria-label="실행 검색" value="${h(this.search)}"/></label></div><div class="table-scroll"><table><thead><tr><th>분석 · 표적</th><th>실행 ID</th><th>상태</th><th>시작 시간</th><th>진행률</th><th>작업</th></tr></thead><tbody>${filtered.map((r) => `<tr><td><strong>${kindNames[r.kind] || h(r.kind)}</strong><small class="table-secondary">${h(r.snapshot.target?.name || "개별 입력 / 공동 설계")}</small></td><td class="mono">${h(r.id.slice(0, 16))}…</td><td>${badge(r.status)}</td><td>${date(r.created)}</td><td><div class="table-progress"><progress max="1" value="${r.progress}"></progress>${Math.round(r.progress * 100)}%</div></td><td><div class="inline-actions"><button class="button small secondary" data-action="view-run" data-id="${h(r.id)}">${r.status === "succeeded" ? "결과 보기" : "상태 보기"}</button>${active(r) ? `<button class="icon-button" data-action="cancel" data-id="${h(r.id)}" aria-label="실행 취소">${icon("x")}</button>` : ["failed", "cancelled"].includes(r.status) ? `<button class="icon-button" data-action="retry" data-id="${h(r.id)}" aria-label="다시 실행">${icon("refresh-cw")}</button>` : ""}</div></td></tr>`).join("") || `<tr><td colspan="6" class="table-empty">${this.loaded ? "표시할 실행이 없습니다." : "실행 이력을 불러오는 중입니다."}</td></tr>`}</tbody></table></div><div class="panel-bottom subtle">최근 최대 200개 실행 · 재시도는 이전 기록을 보존하고 새 실행으로 생성됩니다.</div></section>`;
  }
  libraryPage() {
    const lib =
      this.libraries.find((l) => l.id === this.libraryView) ||
      this.libraries[0];
    return `${this.heading("서열 라이브러리", "검토 가능한 서열 라이브러리", "출처와 서열을 확인하고 연구용 라이브러리를 추가하세요.", `<label class="button primary upload-button">${icon("upload")} 라이브러리 가져오기<input id="library-file" type="file" accept=".json,.fasta,.fa,.faa"/></label>`)}<div class="catalog-grid"><section class="panel catalog-list"><div class="panel-heading"><h2>라이브러리</h2><span>${this.libraries.length}개</span></div>${this.libraries.map((l) => `<button class="catalog-item ${l.id === lib?.id ? "chosen" : ""}" data-action="library-view" data-id="${h(l.id)}">${icon("library-big")}<span><strong>${h(l.name)}</strong><small>${l.members.length}개 서열 · ${l.id === "default" ? "기본 제공" : "사용자 등록"}</small></span>${icon("chevron-right")}</button>`).join("")}</section><section class="panel"><div class="panel-heading"><h2>${h(lib?.name || "서열 목록")}</h2><span class="section-number">SEQUENCE CATALOG</span></div><div class="notice">${icon("circle-help")} 제공 서열은 실험 전 원문과 대조해 주세요. recall은 서열 출처의 신뢰 표시입니다.</div><div class="table-scroll"><table><thead><tr><th>서열 이름</th><th>길이</th><th>서열 · 출처</th><th>Recall</th></tr></thead><tbody>${lib?.members.map((m) => `<tr><td><strong>${h(m.name)}</strong></td><td>${m.sequence.length} aa</td><td><code class="library-sequence">${h(m.sequence)}</code><small class="table-secondary">${h(m.reference || "출처 미등록")}</small></td><td>${h(m.recall || "—")}</td></tr>`).join("") || '<tr><td colspan="4" class="table-empty">라이브러리가 없습니다.</td></tr>'}</tbody></table></div></section></div>`;
  }
  modelPage() {
    return `${this.heading("모델 보정", "실험 데이터로 점수 보정", "측정한 Tm 데이터를 연결해 가중치와 예측 변환식을 함께 보관합니다.")}<div class="calibration-layout"><section class="panel"><div class="panel-heading"><h2>${icon("sliders-horizontal")} Tm 데이터 가져오기</h2><span class="section-number">CALIBRATION</span></div><form id="calibration-form"><label class="dropzone" for="calibration-file">${icon("upload")}<strong>${h(this.calibrationFile?.name || "측정 데이터 CSV 선택")}</strong><span>sequence1, sequence2, tm · 최소 5개 측정</span><input id="calibration-file" type="file" accept=".csv" ${this.calibrationFile ? "" : "required"}/></label><p class="subtle">버퍼·pH·농도 등 실험 조건이 비교 가능한 데이터를 사용하세요. 표본 다양성이 부족하면 보정이 거부됩니다.</p><div class="panel-actions"><span class="subtle">학습 오차와 독립 검증은 구분됩니다.</span><button class="button primary" type="submit" data-busy>${icon("play")} 보정 실행</button></div></form></section><section class="panel calibration-explainer"><span class="eyebrow blue">FROM MEASUREMENT TO MODEL</span><h2>조건과 근거를 남기는<br>연구의 다음 반복.</h2><p>가중치뿐 아니라 Tm 변환 계수와 절편도 함께 저장합니다. 생성된 모델은 탐색 설정에서 선택할 수 있습니다.</p><code>Tm = slope × score + intercept</code></section></div><section class="panel"><div class="panel-heading"><h2>저장된 점수 모델</h2><span>${this.models.length}개 모델</span></div><div class="table-scroll"><table><thead><tr><th>모델</th><th>코어 가중치</th><th>정전기 가중치</th><th>나선 가중치</th><th>학습 표본</th><th>R² / RMSE (°C)</th><th>평가 범위</th></tr></thead><tbody>${this.models.map((m) => `<tr><td><strong>${h(m.name)}</strong><small class="table-secondary mono">${h(m.id.slice(0, 20))}</small></td><td class="numeric">${fmt(m.weights.core)}</td><td class="numeric">${fmt(m.weights.electrostatic)}</td><td class="numeric">${fmt(m.weights.helix)}</td><td class="numeric">${m.metrics?.n || "—"}</td><td class="numeric">${fmt(m.metrics?.r2, 3)} / ${fmt(m.metrics?.rmse)}</td><td><span class="mini-tag">${m.id === "default" ? "미보정 순위" : "학습 데이터만 평가"}</span></td></tr>`).join("")}</tbody></table></div></section>`;
  }

  async submitForm(id: string) {
    if (id === "target-form") await this.saveTarget();
    if (id === "design-form") await this.startDesign();
    if (id === "calibration-form") await this.calibrate();
  }
  async saveTarget() {
    await this.perform(async () => {
      let request: unknown;
      if (this.inputTab === "sequence")
        request = {
          name: this.name.trim(),
          helix: {
            sequence: this.sequence,
            offset: this.offset === "auto" ? null : Number(this.offset),
          },
        };
      else {
        if (!this.file) throw new Error("파일을 선택해 주세요.");
        const item = await upload(this.file);
        request = {
          name: this.name.trim(),
          input_id: item.id,
          ...(this.chain ? { chain: this.chain } : {}),
        };
      }
      const target = await post<Target>("/targets", request);
      this.targets = [
        ...this.targets.filter((t) => t.id !== target.id),
        target,
      ];
      this.targetId = target.id;
      this.clearResults();
      this.render();
      this.notify("표적 등록과 레지스터 분석을 완료했습니다.");
    });
  }
  async screen() {
    if (!this.target) return;
    const target = this.target;
    await this.perform(async () => {
      const result = await post<Result>("/analyses/screen", {
        target_id: target.id,
        model_id: this.modelId,
        library_id: this.libraryId,
        top: 500,
      });
      this.runId = "";
      this.resultKey = "screen";
      this.result = result;
      this.resultTitle = "라이브러리 스크리닝 결과";
      this.resultTarget = target;
      this.resultKind = "screen";
      this.artifacts = [];
      this.selectResults();
      this.render();
      this.notify(`${this.rows.length}개 후보를 비교했습니다.`);
    });
  }
  async startDesign() {
    if (this.mode === "design" && !this.target) {
      this.notify("먼저 표적을 등록하거나 선택해 주세요.", true);
      return;
    }
    if (this.mode === "orthogonal" && this.settings.fixed && !this.target) {
      this.notify("고정할 표적을 선택하거나 표적 고정을 해제해 주세요.", true);
      return;
    }
    await this.perform(async () => {
      const request: Record<string, unknown> = {
        kind: this.mode,
        model_id: this.modelId,
        seed: this.settings.seed === "" ? null : Number(this.settings.seed),
        parameters: {
          n_restarts: Number(this.settings.restarts),
          n_steps: Number(this.settings.steps),
          offset: Number(this.settings.partnerOffset),
          ...(this.mode === "orthogonal"
            ? {
                n_pairs: Number(this.settings.pairs),
                margin: Number(this.settings.margin),
              }
            : {}),
        },
      };
      if (this.mode === "design" || this.settings.fixed)
        request.target_id = this.targetId;
      const run = await post<Run>("/runs", request);
      this.runs.unshift(run);
      this.clearResults();
      this.runId = run.id;
      this.render();
      this.notify(
        this.worker
          ? "설계 작업을 시작했습니다."
          : "대기열에 저장했습니다. 워커 연결 후 실행됩니다.",
      );
    });
  }
  async calibrate() {
    if (!this.calibrationFile) {
      this.notify("CSV 파일을 선택해 주세요.", true);
      return;
    }
    await this.perform(async () => {
      const input = await upload(this.calibrationFile!);
      const run = await post<Run>("/runs", {
        kind: "calibration",
        input_id: input.id,
      });
      this.runs.unshift(run);
      this.clearResults();
      this.runId = run.id;
      location.hash = "history";
      this.notify("모델 보정 작업을 제출했습니다.");
    });
  }
  clearResults() {
    this.runId = "";
    this.result = null;
    this.resultKey = "";
    this.artifacts = [];
    this.selected.clear();
    this.inspected = "";
  }
  selectResults() {
    this.selected = new Set(this.rows.map((c) => c.name));
    this.inspected = this.rows[0]?.name || "";
  }
  async loadRunResult() {
    const run = this.run;
    if (!run) return;
    try {
      const [result, artifacts] = await Promise.all([
        api<Result>(`/runs/${run.id}/results`),
        api<Artifact[]>(`/runs/${run.id}/artifacts`),
      ]);
      if (this.runId !== run.id) return;
      this.result = result;
      this.artifacts = artifacts;
      this.resultKey = run.id;
      this.resultTitle = `${kindNames[run.kind]} 결과`;
      this.resultKind = run.kind;
      this.resultTarget = run.snapshot.target;
      this.selectResults();
      if (this.page === "workspace") {
        this.renderResults();
        this.renderStatus();
      }
    } catch (e) {
      this.notify(
        e instanceof Error ? e.message : "결과를 불러오지 못했습니다.",
        true,
      );
    }
  }
  async click(event: Event) {
    const button = (event.target as Element).closest<HTMLElement>(
      "[data-action]",
    );
    if (!button || button.hasAttribute("disabled")) return;
    const action = button.dataset.action;
    if (action === "menu") {
      this.menuOpen = !this.menuOpen;
      this.render();
    }
    if (action === "refresh") await this.refresh(!this.loaded);
    if (action === "input-tab") {
      this.inputTab = button.dataset.value!;
      this.renderPage();
    }
    if (action === "demo") {
      this.name = "GCN4-p1 · DEMO";
      this.sequence = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER";
      this.offset = "6";
      this.renderPage();
    }
    if (action === "screen") await this.screen();
    if (action === "structure" || action === "dockprep")
      await this.perform(async () => {
        if (!this.target?.input_id)
          throw new Error("PDB에서 등록한 표적을 선택해 주세요.");
        const run = await post<Run>("/runs", {
          kind: action,
          input_id: this.target.input_id,
          chain: this.target.chain || null,
        });
        this.runs.unshift(run);
        this.clearResults();
        this.runId = run.id;
        this.render();
        this.notify("구조 작업을 제출했습니다.");
      });
    if (action === "inspect") {
      this.inspected = button.dataset.name!;
      this.renderResults();
    }
    if (action === "sort" || action === "sort-name") {
      const key = action === "sort" ? "specificity" : "name";
      this.ascending = this.sort === key ? !this.ascending : true;
      this.sort = key;
      this.renderResults();
    }
    if (action === "copy-target" && this.target)
      await this.copy(`>${this.target.name}\n${this.target.sequence}\n`);
    if (action === "copy-candidate") {
      const c = this.rows.find((c) => c.name === this.inspected);
      if (c) await this.copy(`>${c.name}\n${c.sequence}\n`);
    }
    if (action === "export-csv") this.exportCSV();
    if (action === "library-view") {
      this.libraryView = button.dataset.id!;
      this.renderPage();
    }
    if (action === "view-run") {
      this.clearResults();
      this.runId = button.dataset.id!;
      const run = this.run;
      if (run?.request.target_id) this.targetId = run.request.target_id;
      if (location.hash !== "#workspace") location.hash = "workspace";
      else this.render();
      if (run?.status === "succeeded") await this.loadRunResult();
    }
    if (action === "cancel")
      await this.perform(async () => {
        await post(`/runs/${button.dataset.id}/cancel`, {});
        await this.refresh();
        this.notify("취소를 요청했습니다.");
      });
    if (action === "retry")
      await this.perform(async () => {
        const run = await post<Run>(`/runs/${button.dataset.id}/retry`, {});
        this.runs.unshift(run);
        this.clearResults();
        this.runId = run.id;
        this.render();
        this.notify("같은 설정으로 새 실행을 생성했습니다.");
      });
  }
  input(event: Event) {
    const el = event.target as HTMLInputElement;
    if (el.id === "target-name") this.name = el.value;
    if (el.id === "target-sequence") {
      this.sequence = el.value;
      const count = document.getElementById("residue-count");
      if (count) count.textContent = `${el.value.replace(/\s/g, "").length} aa`;
    }
    if (el.id === "target-chain") this.chain = el.value;
    if (
      [
        "steps",
        "restarts",
        "seed",
        "pairs",
        "margin",
        "partnerOffset",
      ].includes(el.id)
    )
      (this.settings as unknown as Record<string, string>)[el.id] = el.value;
    if (el.id === "history-search") {
      this.search = el.value;
      const start = el.selectionStart;
      this.renderPage();
      const next = $<HTMLInputElement>("#history-search");
      next.focus();
      next.setSelectionRange(start, start);
    }
  }
  async change(event: Event) {
    const el = event.target as HTMLInputElement;
    if (el.id === "saved-target") {
      this.targetId = el.value;
      this.clearResults();
      this.renderPage();
    }
    if (el.id === "target-offset") this.offset = el.value;
    if (el.id === "model-select") this.modelId = el.value;
    if (el.id === "library-select") this.libraryId = el.value;
    if (el.name === "mode") {
      this.mode = el.value;
      this.settings.restarts = el.value === "design" ? "8" : "4";
      this.settings.steps = el.value === "design" ? "4000" : "6000";
      this.renderPage();
    }
    if (el.id === "fixed-target") this.settings.fixed = el.checked;
    if (el.id === "target-file") {
      this.file = el.files?.[0] || null;
      if (!this.name && this.file)
        this.name = this.file.name.replace(/\.[^.]+$/, "");
      this.renderPage();
    }
    if (el.id === "calibration-file") {
      this.calibrationFile = el.files?.[0] || null;
      this.renderPage();
    }
    if (el.id === "library-file" && el.files?.[0])
      await this.perform(async () => {
        const input = await upload(el.files![0]);
        const lib = await post<Library>(
          `/libraries?input_id=${encodeURIComponent(input.id)}`,
          {},
        );
        this.libraries.push(lib);
        this.libraryView = lib.id;
        this.libraryId = lib.id;
        this.renderPage();
        this.notify("새 라이브러리를 등록했습니다.");
      });
    if (el.hasAttribute("data-select-all")) {
      this.selected = el.checked
        ? new Set(this.rows.map((c) => c.name))
        : new Set();
      this.renderResults();
    }
    if (el.dataset.candidate) {
      el.checked
        ? this.selected.add(el.dataset.candidate)
        : this.selected.delete(el.dataset.candidate);
      const n = document.getElementById("selected-count");
      if (n) n.textContent = String(this.selected.size);
      const all = document.querySelector<HTMLInputElement>("[data-select-all]");
      if (all) {
        all.checked = this.selected.size === this.rows.length;
        all.indeterminate =
          this.selected.size > 0 && this.selected.size < this.rows.length;
      }
    }
  }
  async copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      this.notify("FASTA 서열을 복사했습니다.");
    } catch {
      this.notify(
        "복사 권한이 없습니다. 표시된 서열을 직접 선택해 주세요.",
        true,
      );
    }
  }
  exportCSV() {
    const rows = this.sortedRows().filter((c) => this.selected.has(c.name));
    if (!rows.length) {
      this.notify("내보낼 후보를 선택해 주세요.", true);
      return;
    }
    const keys = [
      "name",
      "sequence",
      "hetero",
      "candidate_self",
      "target_self",
      "specificity",
      ...(this.resultKind === "screen" ? ["specificity_both"] : []),
    ];
    const cell = (v: unknown) =>
      `"${(typeof v === "string" && /^[=+@-]/.test(v) ? "'" + v : String(v ?? "")).replace(/"/g, '""')}"`;
    const csv =
      "\uFEFF" +
      [
        keys.join(","),
        ...rows.map((c) =>
          keys
            .map((k) => cell((c as unknown as Record<string, unknown>)[k]))
            .join(","),
        ),
      ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8;" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "lz-candidates.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    this.notify(`${rows.length}개 후보를 CSV로 내보냈습니다.`);
  }
}

new ProteinLab();
