/**
 * Virtual Mouse 대시보드 (https://virtual-mouse.iseohyun.com 및 로컬 가이드 http://127.0.0.1:18080/guide)
 *
 * - 서버 유무와 상관없이 열리며(PWA 오프라인 캐시 지원), 오프라인일 때 virtualmouse://start 로
 *   로컬 에이전트를 자동/수동 실행할 수 있다.
 * - 좌측 아코디언 패널에서 PC(Arduino Uno USB HID)와 BT(ESP32 Bluetooth BLE HID) 각각의
 *   설치 · 테스트 · 로그 · 안내 화면을 제공한다.
 * - 모든 API 요청에 `Authorization: Bearer <토큰>` 을 붙인다. 토큰은 로컬 가이드(#token=) 또는
 *   상단 토큰 입력란을 통해 이 브라우저(localStorage)에 저장된다.
 * - 버전 표시: SW_VERSION(SemVer, 승인 후 변경) · BUILD_TAG(YYYYMMDDvN, scripts/bump_build_tag.ps1 로 갱신)
 */
(() => {
  // 공개 도메인에 http:// 로 진입한 경우 즉시 https:// 로 승격한다 (로컬 127.0.0.1/localhost 제외)
  if (location.protocol === "http:" && location.hostname === "virtual-mouse.iseohyun.com") {
    location.replace(`https://virtual-mouse.iseohyun.com${location.pathname}${location.search}${location.hash}`);
    return;
  }

  const API_BASE = "http://127.0.0.1:18080";
  const PROTOCOL_LAUNCH_URI = "virtualmouse://start";
  const TOTAL_CLICKS = 5;
  const POLL_INTERVAL_MS = 1800; // 에이전트와 연결된 동안
  const POLL_INTERVAL_IDLE_MS = 5000; // 에이전트가 없거나 토큰을 기다리는 동안
  const FAST_POLL_INTERVAL_MS = 500; // 로컬 서버 실행 직후 빠른 연결 확인
  const FAST_POLL_DURATION_MS = 10000;

  const TOKEN_KEY = "vm.apiToken";
  const AUTO_LAUNCH_KEY = "vm.autoLaunchAgent";
  const PROTOCOL_READY_KEY = "vm.protocolReady";
  const PWA_DISMISSED_KEY = "vm.pwaBannerDismissed";
  const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,256}$/;

  const FETCH_TIMEOUT_MS = 10000;
  const FIRMWARE_TIMEOUT_MS = 180000;
  const DRIVER_INSTALL_TIMEOUT_MS = 340000;

  // 에이전트가 직접 서빙하는 로컬 가이드인지 (트레이가 #token= 으로 토큰을 넘기는 곳은 여기뿐이다)
  const IS_LOCAL_GUIDE = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(location.origin);
  const SW_VERSION = "v1.4.0";
  const BUILD_TAG = "20261127v2";

  const swLabel = document.getElementById("swVersionLabel");
  if (swLabel) swLabel.textContent = `SW ${SW_VERSION} · ${BUILD_TAG}`;

  const TAB_META = {
    "pc-install": { title: "PC · 설치", group: "pc", panelId: "tab-pc-install" },
    "pc-test": { title: "PC · 테스트", group: "pc", panelId: "tab-pc-test" },
    "pc-logs": { title: "PC · 로그", group: "pc", panelId: "tab-logs" },
    "pc-guide": { title: "PC · 안내", group: "pc", panelId: "tab-pc-guide" },
    "bt-install": { title: "BT · 설치", group: "bt", panelId: "tab-bt-install" },
    "bt-test": { title: "BT · 테스트", group: "bt", panelId: "tab-bt-test" },
    "bt-logs": { title: "BT · 로그", group: "bt", panelId: "tab-logs" },
    "bt-guide": { title: "BT · 안내", group: "bt", panelId: "tab-bt-guide" },
  };
  const LEGACY_HASH_ALIASES = {
    install: "pc-install",
    test: "pc-test",
    logs: "pc-logs",
    guide: "pc-guide",
  };

  const el = {
    sidebar: document.getElementById("sidebar"),
    btnToggleDrawer: document.getElementById("btnToggleDrawer"),
    pageTitle: document.getElementById("pageTitle"),
    pwaModeBadge: document.getElementById("pwaModeBadge"),
    navGroups: Array.from(document.querySelectorAll(".nav-group")),
    navGroupToggles: Array.from(document.querySelectorAll("[data-group-toggle]")),
    navItems: Array.from(document.querySelectorAll(".nav-item")),
    tabPanels: Array.from(document.querySelectorAll(".tab-panel")),
    pcGroupDot: document.getElementById("pcGroupDot"),
    btGroupDot: document.getElementById("btGroupDot"),

    agentBadge: document.getElementById("agentBadge"),
    btnSidebarLaunch: document.getElementById("btnSidebarLaunch"),
    btnInstallPwaSidebar: document.getElementById("btnInstallPwaSidebar"),
    btnEmergencyStop: document.getElementById("btnEmergencyStop"),
    sidebarMsg: document.getElementById("sidebarMsg"),
    fwBadge: document.getElementById("fwBadge"),
    runBadge: document.getElementById("runBadge"),

    // Global Banners
    offlineBanner: document.getElementById("offlineBanner"),
    offlineBannerDesc: document.getElementById("offlineBannerDesc"),
    btnLaunchAgentTop: document.getElementById("btnLaunchAgentTop"),
    chkAutoLaunch: document.getElementById("chkAutoLaunch"),
    launchStatusMsg: document.getElementById("launchStatusMsg"),
    tokenBanner: document.getElementById("tokenBanner"),
    tokenInput: document.getElementById("tokenInput"),
    btnSaveToken: document.getElementById("btnSaveToken"),
    btnClearToken: document.getElementById("btnClearToken"),
    tokenMsg: document.getElementById("tokenMsg"),
    pwaBanner: document.getElementById("pwaBanner"),
    btnInstallPwaBanner: document.getElementById("btnInstallPwaBanner"),
    btnDismissPwaBanner: document.getElementById("btnDismissPwaBanner"),

    // PC Install
    step1Card: document.getElementById("step1Card"),
    step2Card: document.getElementById("step2Card"),
    step3Card: document.getElementById("step3Card"),
    step4Card: document.getElementById("step4Card"),
    step1Status: document.getElementById("step1Status"),
    step2Status: document.getElementById("step2Status"),
    step3Status: document.getElementById("step3Status"),
    step4Status: document.getElementById("step4Status"),
    step1Desc: document.getElementById("step1Desc"),
    jumperDiagram: document.getElementById("jumperDiagram"),
    btnFlashLocal: document.getElementById("btnFlashLocal"),
    btnRemoteUpdate: document.getElementById("btnRemoteUpdate"),
    pillMouse: document.getElementById("pillMouse"),
    pillKeyboard: document.getElementById("pillKeyboard"),
    pillPort: document.getElementById("pillPort"),
    pillProtocol: document.getElementById("pillProtocol"),
    pillAutostart: document.getElementById("pillAutostart"),
    agentInstallHint: document.getElementById("agentInstallHint"),
    btnLaunchAgentStep3: document.getElementById("btnLaunchAgentStep3"),
    driverHint: document.getElementById("driverHint"),
    driverAuto: document.getElementById("driverAuto"),
    driverCurrent: document.getElementById("driverCurrent"),
    btnInstallDriver: document.getElementById("btnInstallDriver"),
    driverMsg: document.getElementById("driverMsg"),
    step1Msg: document.getElementById("step1Msg"),

    // PC Test
    btnStartClickTest: document.getElementById("btnStartClickTest"),
    btnStopTest: document.getElementById("btnStopTest"),
    btnCopyLog: document.getElementById("btnCopyLog"),
    scoreText: document.getElementById("scoreText"),
    arena: document.getElementById("arena"),
    targetBtn: document.getElementById("targetBtn"),
    kbdInput: document.getElementById("kbdInput"),
    btnKbdTest: document.getElementById("btnKbdTest"),
    kbdStatus: document.getElementById("kbdStatus"),
    kbdSteps: Array.from(document.querySelectorAll("#kbdSteps li")),
    logBox: document.getElementById("logBox"),

    // BT Install
    btStep1Card: document.getElementById("btStep1Card"),
    btStep2Card: document.getElementById("btStep2Card"),
    btStep3Card: document.getElementById("btStep3Card"),
    btStep1Status: document.getElementById("btStep1Status"),
    btStep2Status: document.getElementById("btStep2Status"),
    btStep3Status: document.getElementById("btStep3Status"),
    btStep1Desc: document.getElementById("btStep1Desc"),
    btStep2Desc: document.getElementById("btStep2Desc"),
    btStep3Desc: document.getElementById("btStep3Desc"),
    pillBtBridge: document.getElementById("pillBtBridge"),
    pillBtPort: document.getElementById("pillBtPort"),
    pillBtFw: document.getElementById("pillBtFw"),
    btDriverHint: document.getElementById("btDriverHint"),
    btFwHint: document.getElementById("btFwHint"),
    pillBleState: document.getElementById("pillBleState"),
    pillBleName: document.getElementById("pillBleName"),

    // BT Test
    btTestCard: document.getElementById("btTestCard"),
    btTestStatus: document.getElementById("btTestStatus"),
    btnBtDemo: document.getElementById("btnBtDemo"),
    btnBtClickL: document.getElementById("btnBtClickL"),
    btnBtClickR: document.getElementById("btnBtClickR"),
    btnBtScrollUp: document.getElementById("btnBtScrollUp"),
    btnBtScrollDown: document.getElementById("btnBtScrollDown"),
    btStepSize: document.getElementById("btStepSize"),
    btnBtUp: document.getElementById("btnBtUp"),
    btnBtDown: document.getElementById("btnBtDown"),
    btnBtLeft: document.getElementById("btnBtLeft"),
    btnBtRight: document.getElementById("btnBtRight"),
    btnBtCenterClick: document.getElementById("btnBtCenterClick"),
    btTrackpad: document.getElementById("btTrackpad"),
    btLogBox: document.getElementById("btLogBox"),

    // Shared Logs & Runtime Control
    logsModeChip: document.getElementById("logsModeChip"),
    runtimeStatusTag: document.getElementById("runtimeStatusTag"),
    logPillMode: document.getElementById("logPillMode"),
    logPillDevice: document.getElementById("logPillDevice"),
    logPillAuto: document.getElementById("logPillAuto"),
    btnLaunchAgentLogs: document.getElementById("btnLaunchAgentLogs"),
    btnToggleRun: document.getElementById("btnToggleRun"),
    btnToggleAutostart: document.getElementById("btnToggleAutostart"),
    btnQuitAgent: document.getElementById("btnQuitAgent"),
    btnRefreshLogs: document.getElementById("btnRefreshLogs"),
    btnClearServerLogs: document.getElementById("btnClearServerLogs"),
    btnCopyServerLogs: document.getElementById("btnCopyServerLogs"),
    btnForgetToken: document.getElementById("btnForgetToken"),
    runtimeMsg: document.getElementById("runtimeMsg"),
    serverLogBox: document.getElementById("serverLogBox"),
  };

  let activeTab = "pc-install";
  let serverOnline = false;
  let authRequired = false;
  let serverPaused = false;
  let autostartEnabled = false;
  let lastStatus = null;
  let testRunning = false;
  let stopRequested = false;
  let clickCount = 0;
  let calibration = null;
  let pollInFlight = false;
  let pollTimerId = null;
  let fastPollUntil = 0;
  let flashing = false;
  let installingDriver = false;
  let autoLaunchAttempted = false;
  let userQuitThisSession = false;
  let btBusy = false;
  let deferredInstallPrompt = null;

  function readStorage(key, fallback = "") {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch {
      return fallback;
    }
  }

  function writeStorage(key, value) {
    try {
      if (value === null || value === "") localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      // 저장소를 막아 둔 브라우저에서는 이 창에서만 기억한다
    }
  }

  // --- API 토큰 ---
  let apiToken = readStorage(TOKEN_KEY, "");

  function storeToken(value) {
    apiToken = value || "";
    writeStorage(TOKEN_KEY, apiToken);
  }

  // 자동 실행 설정 (기본 ON)
  let autoLaunchPref = readStorage(AUTO_LAUNCH_KEY, "1") !== "0";
  if (el.chkAutoLaunch) el.chkAutoLaunch.checked = autoLaunchPref;

  // 트레이 '로컬 가이드 열기'가 여는 로컬 주소(#token=...)에서만 토큰을 받아 저장한다.
  function takeTokenFromHash() {
    const match = location.hash.match(/^#token=([A-Za-z0-9_-]{32,256})$/);
    if (!match) return false;
    if (IS_LOCAL_GUIDE) storeToken(match[1]);
    history.replaceState(null, "", `${location.pathname}${location.search}#pc-install`);
    return true;
  }
  takeTokenFromHash();

  class AuthRequiredError extends Error {}
  class AgentTimeoutError extends Error {}
  class AgentHttpError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  // 굵은 글씨가 섞인 안내문을 innerHTML 없이 만든다
  function setRich(node, ...parts) {
    node.replaceChildren(
      ...parts.map((part) => {
        if (typeof part === "string") return document.createTextNode(part);
        const strong = document.createElement("strong");
        strong.textContent = part.strong;
        return strong;
      })
    );
  }

  function setInlineMsg(node, text, kind = "") {
    if (!node) return;
    node.textContent = text || "";
    node.className = `inline-msg ${kind}`.trim();
  }

  function flashButtonText(btn, text, ms = 1200) {
    const orig = btn.dataset.label || btn.textContent;
    btn.dataset.label = orig;
    btn.textContent = text;
    setTimeout(() => {
      btn.textContent = orig;
    }, ms);
  }

  function log(msg) {
    const ts = new Date().toLocaleTimeString();
    el.logBox.textContent = `[${ts}] ${msg}\n` + el.logBox.textContent;
  }

  function btLog(msg) {
    const ts = new Date().toLocaleTimeString();
    el.btLogBox.textContent = `[${ts}] ${msg}\n` + el.btLogBox.textContent;
  }

  window.addEventListener("error", (e) => log(`[DIAG:error] ${e.message || "unknown error"}`));
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason && e.reason.message ? e.reason.message : String(e.reason);
    log(`[DIAG:promise] ${reason}`);
  });

  document.addEventListener(
    "click",
    (e) => {
      if (!testRunning) return;
      const targetId = e.target && e.target.id ? `#${e.target.id}` : e.target ? e.target.tagName : "unknown";
      log(`[DEBUG:click] landed on ${targetId} client=(${Math.round(e.clientX)}, ${Math.round(e.clientY)})`);
    },
    true
  );

  // --- PWA 설치(beforeinstallprompt) 및 실행 모드 표시 ---
  const isStandalonePwa =
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  if (isStandalonePwa && el.pwaModeBadge) {
    el.pwaModeBadge.classList.remove("hidden");
    el.pwaModeBadge.classList.add("ok");
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    if (el.btnInstallPwaSidebar) el.btnInstallPwaSidebar.classList.remove("hidden");
    if (!isStandalonePwa && readStorage(PWA_DISMISSED_KEY, "") !== "1" && el.pwaBanner) {
      el.pwaBanner.classList.remove("hidden");
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    if (el.btnInstallPwaSidebar) el.btnInstallPwaSidebar.classList.add("hidden");
    if (el.pwaBanner) el.pwaBanner.classList.add("hidden");
    if (el.pwaModeBadge) {
      el.pwaModeBadge.classList.remove("hidden");
      el.pwaModeBadge.classList.add("ok");
    }
    setInlineMsg(el.sidebarMsg, "PC에 대시보드 앱이 설치되었습니다.", "ok");
  });

  async function promptPwaInstall() {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    try {
      await deferredInstallPrompt.userChoice;
    } catch {
      // ignore
    }
    deferredInstallPrompt = null;
    if (el.btnInstallPwaSidebar) el.btnInstallPwaSidebar.classList.add("hidden");
    if (el.pwaBanner) el.pwaBanner.classList.add("hidden");
  }

  if (el.btnInstallPwaSidebar) el.btnInstallPwaSidebar.addEventListener("click", promptPwaInstall);
  if (el.btnInstallPwaBanner) el.btnInstallPwaBanner.addEventListener("click", promptPwaInstall);
  if (el.btnDismissPwaBanner) {
    el.btnDismissPwaBanner.addEventListener("click", () => {
      writeStorage(PWA_DISMISSED_KEY, "1");
      if (el.pwaBanner) el.pwaBanner.classList.add("hidden");
    });
  }

  // --- 로컬 서버 자동/수동 실행 (virtualmouse://start) ---
  function triggerAgentLaunch(reason = "manual") {
    userQuitThisSession = false;
    fastPollUntil = Date.now() + FAST_POLL_DURATION_MS;
    const msg =
      reason === "auto"
        ? "로컬 서버 자동 실행을 요청했습니다(virtualmouse://start). 연결을 기다리는 중..."
        : "로컬 서버 실행을 요청했습니다(virtualmouse://start). 브라우저 확인 창이 뜨면 [열기]를 눌러 주세요.";
    setInlineMsg(el.launchStatusMsg, msg);
    setInlineMsg(el.runtimeMsg, msg);

    const anchor = document.createElement("a");
    anchor.href = PROTOCOL_LAUNCH_URI;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();

    // 즉시 빠른 폴링 스케줄링
    reschedulePoll(FAST_POLL_INTERVAL_MS);
  }

  el.btnLaunchAgentTop.addEventListener("click", () => triggerAgentLaunch("manual"));
  el.btnLaunchAgentStep3.addEventListener("click", () => triggerAgentLaunch("manual"));
  el.btnLaunchAgentLogs.addEventListener("click", () => triggerAgentLaunch("manual"));
  el.btnSidebarLaunch.addEventListener("click", () => triggerAgentLaunch("manual"));
  el.chkAutoLaunch.addEventListener("change", () => {
    autoLaunchPref = Boolean(el.chkAutoLaunch.checked);
    writeStorage(AUTO_LAUNCH_KEY, autoLaunchPref ? "1" : "0");
  });

  // --- Sidebar Accordion & Tab Navigation ---
  function setGroupOpen(groupName, open) {
    const groupEl = el.navGroups.find((g) => g.dataset.group === groupName);
    if (!groupEl) return;
    groupEl.classList.toggle("open", open);
    const toggleBtn = groupEl.querySelector("[data-group-toggle]");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", String(open));
  }

  el.navGroupToggles.forEach((btn) => {
    btn.addEventListener("click", () => {
      const groupName = btn.dataset.groupToggle;
      const groupEl = el.navGroups.find((g) => g.dataset.group === groupName);
      if (!groupEl) return;
      setGroupOpen(groupName, !groupEl.classList.contains("open"));
    });
  });

  function resolveTab(rawTab) {
    if (TAB_META[rawTab]) return rawTab;
    if (LEGACY_HASH_ALIASES[rawTab]) return LEGACY_HASH_ALIASES[rawTab];
    return "pc-install";
  }

  function updateLogsContextHeader() {
    const isBt = activeTab === "bt-logs";
    el.logsModeChip.textContent = isBt ? "BT · 구동 제어" : "PC · 구동 제어";
    el.logPillMode.textContent = isBt ? "모드: BT (블루투스 · 모바일)" : "모드: PC (유선 USB)";
    el.logPillMode.className = "mini-pill ok";
    if (!lastStatus) {
      el.logPillDevice.textContent = "장치: 미연결";
      el.logPillDevice.className = "mini-pill";
      el.logPillAuto.textContent = "시작 자동 실행: -";
      el.logPillAuto.className = "mini-pill";
      return;
    }
    if (isBt) {
      const bt = lastStatus.bt || {};
      const btText = bt.ble_connected
        ? `ESP32 (${bt.port}) · BLE 연결됨`
        : bt.port
          ? `ESP32 (${bt.port}) · 페어링 대기`
          : "ESP32 미연결";
      el.logPillDevice.textContent = `장치: ${btText}`;
      el.logPillDevice.className = `mini-pill ${bt.ble_connected ? "ok" : ""}`;
    } else {
      const pcText =
        lastStatus.device_type === "uno" && lastStatus.port
          ? `Arduino Uno (${lastStatus.port}) · v${lastStatus.firmware_version || "-"}`
          : lastStatus.state === "dfu_ready"
            ? "DFU 모드 대기"
            : "Arduino 미연결";
      el.logPillDevice.textContent = `장치: ${pcText}`;
      el.logPillDevice.className = `mini-pill ${lastStatus.state === "ready" ? "ok" : ""}`;
    }
    el.logPillAuto.textContent = `시작 자동 실행: ${autostartEnabled ? "켜짐" : "꺼짐"}`;
    el.logPillAuto.className = `mini-pill ${autostartEnabled ? "ok" : ""}`;
  }

  function switchTab(rawTab) {
    const tab = resolveTab(rawTab);
    const meta = TAB_META[tab];
    activeTab = tab;
    setGroupOpen(meta.group, true);
    el.pageTitle.textContent = meta.title;
    el.navItems.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
    el.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === meta.panelId));
    el.sidebar.classList.remove("open");
    if (location.hash !== `#${tab}`) {
      history.replaceState(null, "", `#${tab}`);
    }
    if (meta.panelId === "tab-logs") {
      updateLogsContextHeader();
      fetchServerLogs();
    }
  }

  el.navItems.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
  el.btnToggleDrawer.addEventListener("click", () => {
    el.sidebar.classList.toggle("open");
  });

  function setTag(node, text, cls = "") {
    if (!node) return;
    node.textContent = text;
    node.className = `status-tag ${cls}`.trim();
  }

  function setCardState(card, state) {
    if (!card) return;
    card.classList.remove("active", "done");
    if (state) card.classList.add(state);
  }

  // timeoutMs: 0 이면 기다림 제한 없음
  async function apiFetch(path, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
    const headers = {};
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (apiToken) headers.Authorization = `Bearer ${apiToken}`;
    const controller = timeoutMs > 0 ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, { ...options, headers, signal: controller ? controller.signal : undefined });
    } catch (err) {
      if (controller && controller.signal.aborted) {
        throw new AgentTimeoutError(`로컬 서버가 ${Math.round(timeoutMs / 1000)}초 동안 응답하지 않았습니다`);
      }
      throw err;
    } finally {
      if (timer) clearTimeout(timer);
    }
    let data = {};
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (res.status === 401) {
      throw new AuthRequiredError(data.error || "API token required");
    }
    if (!res.ok) {
      throw new AgentHttpError(data.error || `HTTP ${res.status}`, res.status);
    }
    return data;
  }

  async function calibrateFromEvent(mouseEvent) {
    const health = await apiFetch("/health");
    const dpr = window.devicePixelRatio || 1;
    if (health.cursor && typeof health.cursor.x === "number") {
      calibration = {
        winX: health.cursor.x,
        winY: health.cursor.y,
        clientX: mouseEvent.clientX,
        clientY: mouseEvent.clientY,
        dpr,
      };
      log(`[CALIB] ok: click client=(${Math.round(mouseEvent.clientX)}, ${Math.round(mouseEvent.clientY)}) -> win=(${health.cursor.x}, ${health.cursor.y}), dpr=${dpr}`);
      return true;
    }
    calibration = null;
    log(`[CALIB] fallback (cursor=null), dpr=${dpr}`);
    return false;
  }

  function getElementScreenCenter(node) {
    const rect = node.getBoundingClientRect();
    const elemClientX = rect.left + rect.width / 2;
    const elemClientY = rect.top + rect.height / 2;

    if (calibration) {
      return {
        x: Math.round(calibration.winX + (elemClientX - calibration.clientX) * calibration.dpr),
        y: Math.round(calibration.winY + (elemClientY - calibration.clientY) * calibration.dpr),
        elemClientX: Math.round(elemClientX),
        elemClientY: Math.round(elemClientY),
      };
    }

    const dpr = window.devicePixelRatio || 1;
    const chromeBorderX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
    const chromeTopY = Math.max(0, window.outerHeight - window.innerHeight - chromeBorderX);
    return {
      x: Math.round((window.screenX + chromeBorderX + elemClientX) * dpr),
      y: Math.round((window.screenY + chromeTopY + elemClientY) * dpr),
      elemClientX: Math.round(elemClientX),
      elemClientY: Math.round(elemClientY),
    };
  }

  function moveTargetRandomly() {
    const arenaRect = el.arena.getBoundingClientRect();
    const btnRect = el.targetBtn.getBoundingClientRect();
    const pad = 20;
    const maxX = Math.max(pad, arenaRect.width - btnRect.width - pad);
    const maxY = Math.max(pad, arenaRect.height - btnRect.height - pad);
    el.targetBtn.style.left = `${Math.floor(pad + Math.random() * (maxX - pad))}px`;
    el.targetBtn.style.top = `${Math.floor(pad + Math.random() * (maxY - pad))}px`;
  }

  function setBtControlsEnabled(enabled) {
    const disable = !enabled || btBusy;
    el.btnBtDemo.disabled = disable;
    el.btnBtClickL.disabled = disable;
    el.btnBtClickR.disabled = disable;
    el.btnBtScrollUp.disabled = disable;
    el.btnBtScrollDown.disabled = disable;
    el.btnBtUp.disabled = disable;
    el.btnBtDown.disabled = disable;
    el.btnBtLeft.disabled = disable;
    el.btnBtRight.disabled = disable;
    el.btnBtCenterClick.disabled = disable;
  }

  function renderBtStatus(status) {
    const bt = status.bt || {};
    const btState = bt.state || "no_device";

    el.pillBtBridge.textContent = `USB 브리지: ${bt.usb_bridge || "-"}`;
    el.pillBtBridge.className = `mini-pill ${bt.usb_bridge ? "ok" : ""}`;
    el.pillBtPort.textContent = `포트: ${bt.port || "-"}`;
    el.pillBtPort.className = `mini-pill ${bt.port ? "ok" : ""}`;
    el.pillBtFw.textContent = `펌웨어: ${bt.firmware_version ? `v${bt.firmware_version}` : "-"}`;
    el.pillBtFw.className = `mini-pill ${bt.firmware_version ? "ok" : ""}`;
    el.pillBleName.textContent = `기기 이름: ${bt.ble_name || "VirtualMouse BLE"}`;

    el.btDriverHint.classList.toggle("hidden", btState !== "driver_needed");
    el.btFwHint.classList.toggle("hidden", btState !== "esp32_no_fw");

    if (btState === "ble_connected" && !serverPaused) {
      el.btGroupDot.className = "group-dot ok";
      setTag(el.btStep1Status, "완료", "ok");
      setTag(el.btStep2Status, "완료", "ok");
      setTag(el.btStep3Status, "연결됨", "ok");
      setCardState(el.btStep1Card, "done");
      setCardState(el.btStep2Card, "done");
      setCardState(el.btStep3Card, "done");
      setRich(el.btStep1Desc, "ESP32 USB 연결(", { strong: `${bt.usb_bridge || "USB"} · ${bt.port}` }, ")이 정상 확인되었습니다.");
      setRich(el.btStep2Desc, "ESP32 BLE HID 펌웨어(", { strong: `v${bt.firmware_version}` }, ")가 정상 동작 중입니다.");
      setRich(el.btStep3Desc, "스마트폰과 ", { strong: `${bt.ble_name || "VirtualMouse BLE"}` }, " 블루투스 연결이 완료되었습니다. [BT · 테스트] 탭에서 바로 조작해 보세요.");
      el.pillBleState.textContent = "BLE 상태: 연결됨 (CONNECTED)";
      el.pillBleState.className = "mini-pill ok";

      setTag(el.btTestStatus, "BLE 연결됨", "ok");
      setCardState(el.btTestCard, "active");
      setBtControlsEnabled(true);
      return;
    }

    setBtControlsEnabled(false);
    setCardState(el.btTestCard, "");

    if (btState === "ble_advertising") {
      el.btGroupDot.className = "group-dot warn";
      setTag(el.btStep1Status, "완료", "ok");
      setTag(el.btStep2Status, "완료", "ok");
      setTag(el.btStep3Status, "페어링 대기", "warn");
      setCardState(el.btStep1Card, "done");
      setCardState(el.btStep2Card, "done");
      setCardState(el.btStep3Card, "active");
      setRich(el.btStep3Desc, "ESP32가 페어링 신호를 보내는 중입니다. 스마트폰 블루투스 설정에서 ", { strong: bt.ble_name || "VirtualMouse BLE" }, "를 선택해 연결하세요.");
      el.pillBleState.textContent = "BLE 상태: 페어링 대기 (ADVERTISING)";
      el.pillBleState.className = "mini-pill";
      setTag(el.btTestStatus, "페어링 대기", "warn");
    } else if (btState === "esp32_no_fw") {
      el.btGroupDot.className = "group-dot warn";
      setTag(el.btStep1Status, "연결됨", "ok");
      setTag(el.btStep2Status, "펌웨어 필요", "warn");
      setTag(el.btStep3Status, "대기");
      setCardState(el.btStep1Card, "done");
      setCardState(el.btStep2Card, "active");
      setCardState(el.btStep3Card, "");
      el.pillBleState.textContent = "BLE 상태: 펌웨어 미설치";
      el.pillBleState.className = "mini-pill";
      setTag(el.btTestStatus, "펌웨어 필요", "warn");
    } else if (btState === "driver_needed") {
      el.btGroupDot.className = "group-dot warn";
      setTag(el.btStep1Status, "드라이버 필요", "warn");
      setTag(el.btStep2Status, "대기");
      setTag(el.btStep3Status, "대기");
      setCardState(el.btStep1Card, "active");
      setCardState(el.btStep2Card, "");
      setCardState(el.btStep3Card, "");
      el.pillBleState.textContent = "BLE 상태: 드라이버 확인 필요";
      el.pillBleState.className = "mini-pill";
      setTag(el.btTestStatus, "드라이버 필요", "warn");
    } else {
      el.btGroupDot.className = "group-dot";
      setTag(el.btStep1Status, serverPaused ? "일시 중지" : "미연결");
      setTag(el.btStep2Status, "대기");
      setTag(el.btStep3Status, "대기");
      setCardState(el.btStep1Card, "active");
      setCardState(el.btStep2Card, "");
      setCardState(el.btStep3Card, "");
      setRich(el.btStep1Desc, "ESP32 보드(CP210x / CH340)를 ", { strong: "데이터 전송용 USB 케이블" }, "로 PC에 연결하세요.");
      el.pillBleState.textContent = "BLE 상태: 미연결";
      el.pillBleState.className = "mini-pill";
      setTag(el.btTestStatus, serverPaused ? "서비스 중지됨" : "ESP32 미연결");
    }
  }

  function updateUI(status) {
    renderStatus(status);
    applyBusyLocks();
  }

  function applyBusyLocks() {
    if (flashing || installingDriver) {
      el.btnFlashLocal.disabled = true;
      el.btnRemoteUpdate.disabled = true;
      el.btnInstallDriver.disabled = true;
      el.btnStartClickTest.disabled = true;
      el.btnKbdTest.disabled = true;
    }
    if (testRunning) {
      el.btnStartClickTest.disabled = true;
      el.btnKbdTest.disabled = true;
      el.btnFlashLocal.disabled = true;
    }
  }

  function renderStatus(status) {
    lastStatus = status;
    serverOnline = true;
    authRequired = false;
    serverPaused = Boolean(status.paused);
    autostartEnabled = Boolean(status.autostart_enabled);
    fastPollUntil = 0;

    if (status.protocol_registered) {
      writeStorage(PROTOCOL_READY_KEY, "1");
    }

    el.agentBadge.textContent = status.busy ? "로컬 서버 연결됨 (작업 중)" : "로컬 서버 연결됨";
    el.agentBadge.className = "pill online";
    el.btnSidebarLaunch.classList.add("hidden");
    el.btnLaunchAgentLogs.classList.add("hidden");
    el.offlineBanner.classList.add("hidden");
    el.tokenBanner.classList.add("hidden");
    setInlineMsg(el.launchStatusMsg, "");
    el.btnEmergencyStop.disabled = false;
    el.agentInstallHint.classList.add("hidden");
    setTag(el.step3Status, "연결됨", "ok");
    setCardState(el.step3Card, "done");

    el.pillProtocol.textContent = `자동 실행 프로토콜: ${status.protocol_registered ? "등록됨" : "미등록"}`;
    el.pillProtocol.className = `mini-pill ${status.protocol_registered ? "ok" : ""}`;
    el.pillAutostart.textContent = `Windows 시작 자동 실행: ${autostartEnabled ? "켜짐" : "꺼짐"}`;
    el.pillAutostart.className = `mini-pill ${autostartEnabled ? "ok" : ""}`;

    el.runBadge.textContent = serverPaused ? "구동: 일시 중지" : "구동: 실행 중";
    el.runBadge.className = serverPaused ? "pill warn" : "pill online";
    setTag(el.runtimeStatusTag, serverPaused ? "일시 중지" : "실행 중", serverPaused ? "warn" : "ok");
    el.btnToggleRun.disabled = false;
    el.btnToggleRun.textContent = serverPaused ? "서비스 시작" : "서비스 중지";
    el.btnToggleAutostart.disabled = false;
    el.btnToggleAutostart.textContent = `Windows 시작 자동 실행: ${autostartEnabled ? "켜짐" : "꺼짐"}`;
    el.btnQuitAgent.disabled = false;

    const st = status.state;
    const fw = status.firmware_version || "-";
    if (status.device_type === "esp32") {
      const btReady = status.bt && status.bt.ble_connected;
      el.fwBadge.textContent = `BT: ESP32 v${fw} (${btReady ? "연결됨" : "대기"})`;
    } else if (status.device_type === "uno") {
      el.fwBadge.textContent = `PC: Uno v${fw}`;
    } else {
      el.fwBadge.textContent = "장치: 미연결";
    }

    el.pillMouse.textContent = `HID 마우스: ${status.hid_mouse ? "정상" : "미인식"}`;
    el.pillMouse.className = `mini-pill ${status.hid_mouse ? "ok" : ""}`;
    el.pillKeyboard.textContent = `HID 키보드: ${status.hid_keyboard ? "정상" : "미인식"}`;
    el.pillKeyboard.className = `mini-pill ${status.hid_keyboard ? "ok" : ""}`;
    el.pillPort.textContent = `포트: ${status.device_type === "uno" ? status.port || "-" : "-"}`;
    el.pillPort.className = `mini-pill ${status.device_type === "uno" && status.port ? "ok" : ""}`;

    renderBtStatus(status);
    updateLogsContextHeader();

    // WinUSB 드라이버가 없는 DFU 장치
    const needsDriver = st === "dfu_ready" && !status.dfu_driver_ok;
    el.driverHint.classList.toggle("hidden", !needsDriver);
    el.driverAuto.classList.toggle("hidden", !(needsDriver && status.driver_installer));
    el.btnInstallDriver.disabled = Boolean(status.driver_installing);
    const currentDriver = status.dfu_driver_service;
    el.driverCurrent.classList.toggle("hidden", !(needsDriver && currentDriver));
    el.driverCurrent.textContent = currentDriver
      ? `지금 이 장치에 붙어 있는 드라이버(${currentDriver})는 WinUSB로 바뀝니다.`
      : "";
    if (needsDriver && status.driver_installing && !installingDriver) {
      setInlineMsg(el.driverMsg, "드라이버 설치가 진행 중입니다. Windows 「사용자 계정 컨트롤」 창을 확인해 주세요.");
    }

    if (st === "ready" && !serverPaused) {
      el.pcGroupDot.className = "group-dot ok";
      setTag(el.step1Status, "자동 스킵", "ok");
      setTag(el.step2Status, "완료", "ok");
      setCardState(el.step1Card, "done");
      setCardState(el.step2Card, "done");
      setRich(el.step1Desc, "최신 펌웨어(", { strong: `v${fw}` }, ")가 이미 설치되어 있어 1·2단계를 자동으로 건너뛰었습니다.");
      el.jumperDiagram.classList.add("hidden");
      el.btnFlashLocal.disabled = true;
      el.btnRemoteUpdate.classList.add("hidden");

      setTag(el.step4Status, testRunning ? "테스트 중" : "준비 완료", testRunning ? "warn" : "ok");
      setCardState(el.step4Card, "active");
      el.btnStartClickTest.disabled = testRunning;
      el.btnKbdTest.disabled = testRunning;
      return;
    }

    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    setTag(el.step4Status, serverPaused ? "서비스 중지됨" : "PC 장치 준비 대기");
    setCardState(el.step4Card, "");

    if (serverPaused) {
      el.pcGroupDot.className = "group-dot warn";
      return;
    }

    if (st === "outdated") {
      el.pcGroupDot.className = "group-dot warn";
      setTag(el.step1Status, "업데이트 필요", "warn");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "현재 펌웨어(", { strong: `v${fw}` }, ")가 구버전입니다. 아래 버튼으로 자동 업데이트할 수 있습니다.");
      el.jumperDiagram.classList.add("hidden");
      el.btnFlashLocal.disabled = false;
      el.btnRemoteUpdate.classList.remove("hidden");
      return;
    }

    if (st === "port_busy") {
      el.pcGroupDot.className = "group-dot warn";
      setTag(el.step1Status, "포트 사용 중", "warn");
      setCardState(el.step1Card, "active");
      setRich(
        el.step1Desc,
        "VirtualMouse 장치는 연결되어 있지만 ",
        { strong: "COM 포트를 열 수 없습니다" },
        ". Arduino IDE 시리얼 모니터처럼 포트를 쓰는 프로그램을 닫거나, 에이전트가 두 개 실행 중인지 확인하세요."
      );
      if (!flashing) setInlineMsg(el.step1Msg, status.connect_error ? `상세: ${status.connect_error}` : "");
      el.jumperDiagram.classList.add("hidden");
      el.btnFlashLocal.disabled = true;
      el.btnRemoteUpdate.classList.add("hidden");
      return;
    }

    el.jumperDiagram.classList.remove("hidden");
    el.btnRemoteUpdate.classList.add("hidden");

    if (st === "dfu_ready") {
      el.pcGroupDot.className = "group-dot warn";
      setTag(el.step1Status, "DFU 감지됨", "warn");
      setCardState(el.step1Card, "active");
      if (status.dfu_driver_ok) {
        setRich(el.step1Desc, "DFU 모드와 WinUSB 드라이버가 확인되었습니다. ", { strong: "[DFU 펌웨어 설치 실행]" }, "을 눌러 주세요.");
      } else if (status.driver_installer) {
        setRich(
          el.step1Desc,
          "DFU 모드가 감지되었으나 ",
          { strong: "WinUSB 드라이버 설치" },
          "가 필요합니다. 아래 [드라이버 자동 설치]를 누르거나 Zadig로 직접 설치해 주세요."
        );
      } else {
        setRich(el.step1Desc, "DFU 모드가 감지되었으나 ", { strong: "WinUSB 드라이버 설치" }, "가 필요합니다. 아래 안내를 따라 주세요.");
      }
      el.btnFlashLocal.disabled = !status.dfu_driver_ok;
    } else if (st === "stock_uno") {
      el.pcGroupDot.className = "group-dot warn";
      setTag(el.step1Status, "점퍼 접촉 필요", "warn");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "순정 Arduino Uno R3가 감지되었습니다. ", { strong: "USB 쪽 2핀(RESET-GND)" }, "을 점퍼선으로 1초간 접촉했다 떼어 주세요.");
      el.btnFlashLocal.disabled = true;
    } else {
      el.pcGroupDot.className = "group-dot";
      setTag(el.step1Status, "보드 미연결");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "Arduino Uno R3를 USB 포트에 연결해 주세요. (모바일용 ESP32를 쓰는 경우 좌측 BT 메뉴를 확인하세요.)");
      el.btnFlashLocal.disabled = true;
    }
  }

  function disableAgentControls() {
    lastStatus = null;
    serverOnline = false;
    el.fwBadge.textContent = "장치: -";
    el.runBadge.className = "pill muted";
    el.pcGroupDot.className = "group-dot";
    el.btGroupDot.className = "group-dot";
    el.driverHint.classList.add("hidden");
    el.btDriverHint.classList.add("hidden");
    el.btFwHint.classList.add("hidden");
    setCardState(el.step3Card, "active");
    el.btnToggleRun.disabled = true;
    el.btnToggleAutostart.disabled = true;
    el.btnQuitAgent.disabled = true;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnFlashLocal.disabled = true;
    el.btnInstallDriver.disabled = true;
    el.btnRemoteUpdate.classList.add("hidden");
    el.btnEmergencyStop.disabled = true;
    setBtControlsEnabled(false);
    updateLogsContextHeader();
  }

  function updateOfflineUI() {
    authRequired = false;
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버 미실행";
    el.agentBadge.className = "pill offline";
    el.runBadge.textContent = "구동: 미연결";
    el.btnSidebarLaunch.classList.remove("hidden");
    el.btnLaunchAgentLogs.classList.remove("hidden");
    el.offlineBanner.classList.remove("hidden");
    el.agentInstallHint.classList.remove("hidden");
    el.tokenBanner.classList.add("hidden");
    setTag(el.step3Status, "미연결", "warn");
    setTag(el.runtimeStatusTag, "미연결", "warn");

    // 이 브라우저에서 프로토콜 등록 이력이 있고 자동 실행이 켜져 있으면 최초 1회 자동 기동 시도
    const hasProtocol = readStorage(PROTOCOL_READY_KEY, "") === "1";
    if (!autoLaunchAttempted && autoLaunchPref && hasProtocol && !userQuitThisSession) {
      autoLaunchAttempted = true;
      triggerAgentLaunch("auto");
    }
  }

  function updateAgentErrorUI(message) {
    authRequired = false;
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버 응답 오류";
    el.agentBadge.className = "pill warn";
    el.runBadge.textContent = "구동: 확인 필요";
    el.btnSidebarLaunch.classList.add("hidden");
    el.btnLaunchAgentLogs.classList.add("hidden");
    el.offlineBanner.classList.add("hidden");
    el.agentInstallHint.classList.add("hidden");
    el.tokenBanner.classList.add("hidden");
    setTag(el.step3Status, "응답 오류", "warn");
    setTag(el.runtimeStatusTag, "응답 오류", "warn");
    setInlineMsg(el.sidebarMsg, message, "warn");
  }

  function updateAuthRequiredUI() {
    authRequired = true;
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버: 토큰 필요";
    el.agentBadge.className = "pill warn";
    el.runBadge.textContent = "구동: 인증 대기";
    el.btnSidebarLaunch.classList.add("hidden");
    el.btnLaunchAgentLogs.classList.add("hidden");
    el.offlineBanner.classList.add("hidden");
    el.agentInstallHint.classList.add("hidden");
    el.tokenBanner.classList.remove("hidden");
    setTag(el.step3Status, "토큰 필요", "warn");
    setTag(el.runtimeStatusTag, "토큰 필요", "warn");
  }

  async function fetchServerLogs() {
    if (!serverOnline) {
      el.serverLogBox.textContent = authRequired
        ? "API 토큰이 필요합니다. 상단 안내에서 토큰을 입력해 주세요."
        : "로컬 서버에 연결되어 있지 않습니다. 상단의 [로컬 서버 실행]을 눌러 시작하세요.";
      return;
    }
    try {
      const data = await apiFetch("/logs");
      const lines = data.lines || [];
      el.serverLogBox.textContent = lines.length ? lines.slice().reverse().join("\n") : "아직 기록된 서버 로그가 없습니다.";
    } catch (err) {
      el.serverLogBox.textContent =
        err instanceof AuthRequiredError ? "API 토큰이 필요합니다. 상단 안내에서 토큰을 입력하세요." : `서버 로그를 불러올 수 없습니다: ${err.message}`;
    }
  }

  async function pollStatus() {
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      const status = await apiFetch("/status");
      if (el.sidebarMsg.classList.contains("warn")) setInlineMsg(el.sidebarMsg, "");
      updateUI(status);
      if (TAB_META[activeTab] && TAB_META[activeTab].panelId === "tab-logs") {
        await fetchServerLogs();
      }
    } catch (err) {
      if (err instanceof AuthRequiredError) updateAuthRequiredUI();
      else if (err instanceof AgentTimeoutError || err instanceof AgentHttpError) updateAgentErrorUI(err.message);
      else updateOfflineUI();
    } finally {
      pollInFlight = false;
    }
  }

  // --- API Token ---
  el.btnSaveToken.addEventListener("click", async () => {
    const value = el.tokenInput.value.trim();
    if (!TOKEN_PATTERN.test(value)) {
      setInlineMsg(el.tokenMsg, "토큰 형식이 아닙니다. 트레이 메뉴의 'API 토큰 복사'로 다시 복사해 주세요.", "warn");
      return;
    }
    storeToken(value);
    el.tokenInput.value = "";
    setInlineMsg(el.tokenMsg, "확인 중...");
    try {
      const status = await apiFetch("/status");
      setInlineMsg(el.tokenMsg, "");
      updateUI(status);
    } catch (err) {
      if (err instanceof AuthRequiredError) {
        setInlineMsg(el.tokenMsg, "토큰이 맞지 않습니다. 에이전트의 현재 토큰을 다시 복사해 주세요.", "warn");
      } else {
        setInlineMsg(el.tokenMsg, `로컬 서버에 연결할 수 없습니다: ${err.message}`, "warn");
      }
    }
  });

  el.tokenInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") el.btnSaveToken.click();
  });

  function forgetToken(msgNode) {
    storeToken("");
    setInlineMsg(msgNode, "이 브라우저에 저장된 토큰을 지웠습니다.", "ok");
    pollStatus();
  }

  el.btnClearToken.addEventListener("click", () => forgetToken(el.tokenMsg));
  el.btnForgetToken.addEventListener("click", () => forgetToken(el.runtimeMsg));

  // --- PC Install Actions ---
  async function runFirmwareUpdate(body, startText) {
    if (flashing) return;
    flashing = true;
    applyBusyLocks();
    setInlineMsg(el.step1Msg, startText);
    log(startText);
    try {
      const res = await apiFetch("/firmware/update", { method: "POST", body: JSON.stringify(body) }, FIRMWARE_TIMEOUT_MS);
      const done = res.updated === false
        ? `이미 최신 펌웨어입니다 (현재 ${res.current_version || "-"}, 배포 ${res.remote_version || "-"}).`
        : "플래싱 완료! USB 케이블을 뺐다가 다시 연결해 주세요.";
      setInlineMsg(el.step1Msg, done, "ok");
      log(done);
    } catch (err) {
      setInlineMsg(el.step1Msg, `펌웨어 설치 실패: ${err.message}`, "warn");
      log(`펌웨어 설치 실패: ${err.message}`);
    } finally {
      flashing = false;
      el.btnRemoteUpdate.disabled = false;
      pollStatus();
    }
  }

  el.btnFlashLocal.addEventListener("click", () => {
    runFirmwareUpdate({ use_local: true }, "펌웨어 플래싱 중입니다... (USB 케이블을 뽑지 마세요)");
  });

  el.btnRemoteUpdate.addEventListener("click", () => {
    runFirmwareUpdate({ force: false }, "최신 펌웨어를 받아 설치하는 중입니다... (USB 케이블을 뽑지 마세요)");
  });

  async function installDriver() {
    if (installingDriver || flashing) return;
    installingDriver = true;
    applyBusyLocks();
    const startText =
      "드라이버 설치를 요청했습니다. Windows 「사용자 계정 컨트롤」 창이 뜨면 [예]를 눌러 주세요. " +
      "창이 보이지 않으면 작업 표시줄에서 깜빡이는 방패 아이콘을 누르세요.";
    setInlineMsg(el.driverMsg, startText);
    log("WinUSB 드라이버 자동 설치 요청");
    try {
      const res = await apiFetch("/driver/install", { method: "POST", body: "{}" }, DRIVER_INSTALL_TIMEOUT_MS);
      const text = res.message || `결과: ${res.status}`;
      const kind = res.ok && res.verified !== false ? "ok" : "warn";
      setInlineMsg(el.driverMsg, text, kind);
      if (res.ok) setInlineMsg(el.step1Msg, text, kind);
      log(`드라이버 자동 설치 결과: ${res.status}`);
    } catch (err) {
      setInlineMsg(el.driverMsg, `드라이버 설치 요청 실패: ${err.message}`, "warn");
      log(`드라이버 설치 요청 실패: ${err.message}`);
    } finally {
      installingDriver = false;
      pollStatus();
    }
  }

  el.btnInstallDriver.addEventListener("click", installDriver);

  // --- PC Mouse Live Click Test ---
  el.targetBtn.addEventListener("click", () => {
    if (!testRunning) {
      moveTargetRandomly();
      return;
    }
    clickCount += 1;
    el.scoreText.textContent = `진행: ${clickCount} / ${TOTAL_CLICKS}`;
    log(`타겟 버튼 클릭 성공! (${clickCount}/${TOTAL_CLICKS})`);
    moveTargetRandomly();
  });

  el.btnStartClickTest.addEventListener("click", async (evt) => {
    if (testRunning) return;
    if (!isPointerClick(evt)) {
      log("마우스로 시작 버튼을 직접 눌러 주세요. (화면 위치를 맞추려면 실제 클릭 좌표가 필요합니다)");
      return;
    }
    testRunning = true;
    stopRequested = false;
    clickCount = 0;
    el.scoreText.textContent = `진행: 0 / ${TOTAL_CLICKS}`;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnStopTest.disabled = false;
    log("자동 클릭 테스트(5회) 시작...");

    try {
      await calibrateFromEvent(evt);
      for (let i = 1; i <= TOTAL_CLICKS; i++) {
        if (stopRequested) break;
        moveTargetRandomly();
        await new Promise((r) => setTimeout(r, 280));
        const pos = getElementScreenCenter(el.targetBtn);
        log(`[${i}/${TOTAL_CLICKS}] 요청 win=(${pos.x}, ${pos.y}) / target client=(${pos.elemClientX}, ${pos.elemClientY})`);
        const res = await apiFetch(
          "/action",
          {
            method: "POST",
            body: JSON.stringify({ action: "click_at", x: pos.x, y: pos.y, button: "L" }),
          },
          0
        );
        const actual = res.result && res.result.cursor ? `(${res.result.cursor.x}, ${res.result.cursor.y})` : "null";
        log(`[${i}/${TOTAL_CLICKS}] 서버 도달 cursor=${actual}`);
        await new Promise((r) => setTimeout(r, 250));
      }
      log(stopRequested ? "사용자에 의해 중단되었습니다." : `자동 클릭 테스트 종료 (성공 ${clickCount}/${TOTAL_CLICKS})`);
    } catch (err) {
      log(`테스트 오류: ${err.message}`);
    } finally {
      testRunning = false;
      el.btnStopTest.disabled = true;
      pollStatus();
    }
  });

  async function emergencyStop() {
    stopRequested = true;
    try {
      await apiFetch("/action", { method: "POST", body: JSON.stringify({ action: "release_all" }) });
      log("비상 정지: 진행 중인 동작을 끊고 눌린 버튼·키를 모두 해제했습니다.");
      btLog("비상 정지: 눌린 버튼을 모두 해제했습니다.");
      setInlineMsg(el.sidebarMsg, "비상 정지 완료", "ok");
    } catch (err) {
      const msg = `비상 정지 요청 실패: ${err.message} (USB 케이블을 뽑으면 즉시 멈춥니다)`;
      log(msg);
      btLog(msg);
      setInlineMsg(el.sidebarMsg, msg, "warn");
    }
  }

  el.btnStopTest.addEventListener("click", emergencyStop);
  el.btnEmergencyStop.addEventListener("click", emergencyStop);

  function isPointerClick(evt) {
    return evt && evt.detail > 0 && (evt.clientX !== 0 || evt.clientY !== 0);
  }

  el.btnCopyLog.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(el.logBox.textContent);
      log("테스트 로그를 클립보드에 복사했습니다.");
    } catch {
      log("클립보드 복사 실패");
    }
  });

  // --- PC Keyboard Scenario Test ---
  function markKbdStep(stepIdx, state) {
    el.kbdSteps.forEach((li) => {
      const idx = Number(li.dataset.step);
      if (idx < stepIdx) li.className = "done";
      else if (idx === stepIdx) li.className = state;
      else li.className = "";
    });
  }

  function ensureKbdTarget(stepLabel) {
    if (stopRequested) throw new Error("사용자가 비상 정지를 눌러 멈췄습니다.");
    if (!document.hasFocus() || document.activeElement !== el.kbdInput) {
      throw new Error(`${stepLabel} 전에 입력창이 선택되어 있지 않아 멈췄습니다. 다른 창에 키가 입력되지 않도록 키를 보내지 않았습니다.`);
    }
  }

  el.btnKbdTest.addEventListener("click", async (evt) => {
    if (testRunning) return;
    if (!isPointerClick(evt)) {
      log("마우스로 실행 버튼을 직접 눌러 주세요. (화면 위치를 맞추려면 실제 클릭 좌표가 필요합니다)");
      return;
    }
    testRunning = true;
    stopRequested = false;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnStopTest.disabled = false;
    setTag(el.kbdStatus, "실행 중", "warn");
    el.kbdInput.value = "";
    markKbdStep(0, "");

    try {
      await calibrateFromEvent(evt);
      const pos = getElementScreenCenter(el.kbdInput);

      markKbdStep(1, "active");
      log(`[KBD 1/5] 입력창(${pos.x}, ${pos.y}) 자동 클릭`);
      await apiFetch(
        "/action",
        {
          method: "POST",
          body: JSON.stringify({ action: "click_at", x: pos.x, y: pos.y, button: "L" }),
        },
        0
      );
      await new Promise((r) => setTimeout(r, 150));

      ensureKbdTarget("타이핑");
      markKbdStep(2, "active");
      log('[KBD 2/5] "Hello VirtualMouse!" 사람처럼 타이핑');
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({
          actions: [
            { action: "sleep", ms: 120 },
            { action: "type", text: "Hello VirtualMouse!" },
            { action: "sleep", ms: 350 },
          ],
        }),
      });

      ensureKbdTarget("Ctrl + A");
      markKbdStep(3, "active");
      log("[KBD 3/5] Ctrl + A 전체 선택");
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({
          actions: [
            { action: "hotkey", keys: ["ctrl", "a"] },
            { action: "sleep", ms: 250 },
          ],
        }),
      });

      ensureKbdTarget("Backspace");
      markKbdStep(4, "active");
      log("[KBD 4/5] Backspace 삭제");
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({
          actions: [
            { action: "key_tap", key: "backspace" },
            { action: "sleep", ms: 220 },
          ],
        }),
      });

      ensureKbdTarget("최종 입력");
      markKbdStep(5, "active");
      log('[KBD 5/5] "Keyboard OK 123" 최종 입력');
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({ action: "type", text: "Keyboard OK 123" }),
      });

      markKbdStep(6, "done");
      const ok = el.kbdInput.value === "Keyboard OK 123";
      setTag(el.kbdStatus, ok ? "성공" : "확인 필요", ok ? "ok" : "warn");
      log(`키보드 시나리오 완료! 입력창 값: "${el.kbdInput.value}"`);
    } catch (err) {
      setTag(el.kbdStatus, stopRequested ? "중단됨" : "오류", "warn");
      log(`키보드 시나리오 중단: ${err.message}`);
    } finally {
      testRunning = false;
      el.btnStopTest.disabled = true;
      pollStatus();
    }
  });

  // --- BT Live Mouse Test ---
  async function sendBtAction(payload, label) {
    if (btBusy) return;
    btBusy = true;
    setBtControlsEnabled(false);
    btLog(`${label} 전송...`);
    try {
      await apiFetch("/action", { method: "POST", body: JSON.stringify(payload) });
      btLog(`${label} 완료`);
    } catch (err) {
      btLog(`${label} 실패: ${err.message}`);
    } finally {
      btBusy = false;
      const ready = Boolean(lastStatus && lastStatus.bt && lastStatus.bt.ble_connected && !serverPaused);
      setBtControlsEnabled(ready);
    }
  }

  function btStepPx() {
    return Number(el.btStepSize.value) || 70;
  }

  el.btnBtDemo.addEventListener("click", () => sendBtAction({ action: "bt_demo" }, "사각형 이동 데모"));
  el.btnBtClickL.addEventListener("click", () => sendBtAction({ action: "click", button: "L" }, "좌클릭 (탭)"));
  el.btnBtCenterClick.addEventListener("click", () => sendBtAction({ action: "click", button: "L" }, "좌클릭 (탭)"));
  el.btnBtClickR.addEventListener("click", () => sendBtAction({ action: "click", button: "R" }, "우클릭 (뒤로)"));
  el.btnBtScrollUp.addEventListener("click", () => sendBtAction({ action: "scroll", delta: 3 }, "위로 스크롤 (+3)"));
  el.btnBtScrollDown.addEventListener("click", () => sendBtAction({ action: "scroll", delta: -3 }, "아래로 스크롤 (-3)"));
  el.btnBtUp.addEventListener("click", () => sendBtAction({ action: "move", dx: 0, dy: -btStepPx() }, `위로 이동 (${btStepPx()}px)`));
  el.btnBtDown.addEventListener("click", () => sendBtAction({ action: "move", dx: 0, dy: btStepPx() }, `아래로 이동 (${btStepPx()}px)`));
  el.btnBtLeft.addEventListener("click", () => sendBtAction({ action: "move", dx: -btStepPx(), dy: 0 }, `왼쪽 이동 (${btStepPx()}px)`));
  el.btnBtRight.addEventListener("click", () => sendBtAction({ action: "move", dx: btStepPx(), dy: 0 }, `오른쪽 이동 (${btStepPx()}px)`));

  // 트랙패드 드래그/탭 -> BT 상대 이동 / 클릭
  let trackpadActive = false;
  let trackStart = null;
  let trackLast = null;
  let trackAccumX = 0;
  let trackAccumY = 0;
  let trackMovedTotal = 0;
  let trackFlushPending = false;

  async function flushTrackpadDelta() {
    if (trackFlushPending) return;
    const dx = Math.round(trackAccumX);
    const dy = Math.round(trackAccumY);
    if (dx === 0 && dy === 0) return;
    trackAccumX -= dx;
    trackAccumY -= dy;
    trackFlushPending = true;
    try {
      await apiFetch("/action", { method: "POST", body: JSON.stringify({ action: "move", dx, dy, human: false }) });
    } catch (err) {
      btLog(`트랙패드 이동 실패: ${err.message}`);
    } finally {
      trackFlushPending = false;
      if (Math.abs(trackAccumX) >= 2 || Math.abs(trackAccumY) >= 2) {
        flushTrackpadDelta();
      }
    }
  }

  el.btTrackpad.addEventListener("pointerdown", (e) => {
    const ready = Boolean(lastStatus && lastStatus.bt && lastStatus.bt.ble_connected && !serverPaused);
    if (!ready) return;
    trackpadActive = true;
    trackStart = { x: e.clientX, y: e.clientY };
    trackLast = { x: e.clientX, y: e.clientY };
    trackAccumX = 0;
    trackAccumY = 0;
    trackMovedTotal = 0;
    el.btTrackpad.classList.add("active");
    el.btTrackpad.setPointerCapture(e.pointerId);
  });

  el.btTrackpad.addEventListener("pointermove", (e) => {
    if (!trackpadActive || !trackLast) return;
    const dx = (e.clientX - trackLast.x) * 1.4;
    const dy = (e.clientY - trackLast.y) * 1.4;
    trackLast = { x: e.clientX, y: e.clientY };
    trackAccumX += dx;
    trackAccumY += dy;
    trackMovedTotal += Math.hypot(dx, dy);
    if (Math.abs(trackAccumX) >= 4 || Math.abs(trackAccumY) >= 4) {
      flushTrackpadDelta();
    }
  });

  function finishTrackpad(e) {
    if (!trackpadActive) return;
    trackpadActive = false;
    el.btTrackpad.classList.remove("active");
    if (trackStart && trackMovedTotal < 6) {
      sendBtAction({ action: "click", button: "L" }, "트랙패드 탭");
    } else if (Math.abs(trackAccumX) >= 1 || Math.abs(trackAccumY) >= 1) {
      flushTrackpadDelta();
    }
    trackStart = null;
    trackLast = null;
    try {
      if (e && el.btTrackpad.hasPointerCapture(e.pointerId)) {
        el.btTrackpad.releasePointerCapture(e.pointerId);
      }
    } catch {
      // ignore
    }
  }

  el.btTrackpad.addEventListener("pointerup", finishTrackpad);
  el.btTrackpad.addEventListener("pointercancel", finishTrackpad);

  // --- Runtime Control & Server Logs ---
  el.btnToggleRun.addEventListener("click", async () => {
    try {
      el.btnToggleRun.disabled = true;
      const endpoint = serverPaused ? "/control/resume" : "/control/pause";
      await apiFetch(endpoint, { method: "POST", body: "{}" });
      setInlineMsg(el.runtimeMsg, "");
      await pollStatus();
    } catch (err) {
      setInlineMsg(el.runtimeMsg, `구동 전환 실패: ${err.message}`, "warn");
      el.btnToggleRun.disabled = false;
    }
  });

  el.btnToggleAutostart.addEventListener("click", async () => {
    try {
      el.btnToggleAutostart.disabled = true;
      const nextEnabled = !autostartEnabled;
      const res = await apiFetch("/control/autostart", {
        method: "POST",
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      autostartEnabled = Boolean(res.autostart_enabled);
      setInlineMsg(
        el.runtimeMsg,
        autostartEnabled ? "Windows 로그인 시 로컬 서버가 자동 실행됩니다." : "Windows 시작 시 자동 실행을 껐습니다.",
        "ok"
      );
      await pollStatus();
    } catch (err) {
      setInlineMsg(el.runtimeMsg, `자동 실행 설정 변경 실패: ${err.message}`, "warn");
      el.btnToggleAutostart.disabled = false;
    }
  });

  el.btnQuitAgent.addEventListener("click", async () => {
    if (!confirm("VirtualMouse 트레이 에이전트를 완전히 종료할까요?")) return;
    try {
      userQuitThisSession = true;
      await apiFetch("/control/quit", { method: "POST", body: "{}" });
      setInlineMsg(el.runtimeMsg, "에이전트를 종료했습니다. 다시 켜려면 [로컬 서버 실행]을 누르세요.", "ok");
      setTimeout(pollStatus, 600);
    } catch (err) {
      userQuitThisSession = false;
      setInlineMsg(el.runtimeMsg, `에이전트 종료 요청 실패: ${err.message}`, "warn");
      pollStatus();
    }
  });

  el.btnRefreshLogs.addEventListener("click", fetchServerLogs);

  el.btnClearServerLogs.addEventListener("click", async () => {
    try {
      await apiFetch("/logs/clear", { method: "POST", body: "{}" });
      setInlineMsg(el.runtimeMsg, "");
      await fetchServerLogs();
    } catch (err) {
      setInlineMsg(el.runtimeMsg, `로그를 비우지 못했습니다: ${err.message}`, "warn");
    }
  });

  el.btnCopyServerLogs.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(el.serverLogBox.textContent);
      flashButtonText(el.btnCopyServerLogs, "복사됨!");
    } catch {
      flashButtonText(el.btnCopyServerLogs, "복사 실패");
    }
  });

  // --- API Guide Code Copy ---
  document.querySelectorAll(".copy-code").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = document.getElementById(btn.dataset.target);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent);
        flashButtonText(btn, "복사됨!");
      } catch {
        flashButtonText(btn, "복사 실패");
      }
    });
  });

  // Register Service Worker for PWA installability & offline shell
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch((err) => {
      console.warn("Service worker registration failed:", err);
    });
  }

  // Initial route from URL hash
  const initialHash = location.hash.replace("#", "");
  switchTab(initialHash || "pc-install");

  window.addEventListener("hashchange", () => {
    if (takeTokenFromHash()) {
      switchTab("pc-install");
      pollStatus();
      return;
    }
    const tab = resolveTab(location.hash.replace("#", ""));
    if (tab !== activeTab) switchTab(tab);
  });

  function nextPollDelay() {
    if (Date.now() < fastPollUntil) return FAST_POLL_INTERVAL_MS;
    return serverOnline ? POLL_INTERVAL_MS : POLL_INTERVAL_IDLE_MS;
  }

  function reschedulePoll(delayMs) {
    if (pollTimerId !== null) clearTimeout(pollTimerId);
    pollTimerId = setTimeout(async () => {
      pollTimerId = null;
      await pollStatus();
      schedulePoll();
    }, delayMs);
  }

  function schedulePoll() {
    reschedulePoll(nextPollDelay());
  }

  pollStatus().finally(schedulePoll);
})();
