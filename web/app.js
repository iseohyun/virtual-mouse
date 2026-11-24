/**
 * Virtual Mouse 대시보드 (https://virtual-mouse.iseohyun.com 및 로컬 가이드 http://127.0.0.1:18080/guide)
 *
 * - 로컬 에이전트(API_BASE)의 /status 를 주기적으로 읽어 설치 1~3단계와 테스트·구동 탭을 갱신한다.
 * - 모든 API 요청에 `Authorization: Bearer <토큰>` 을 붙인다. 토큰은 트레이 '대시보드 보기'가 #token= 으로
 *   넘겨 주거나(로컬 가이드에서만), 사용자가 3단계 카드에 붙여 넣으면 이 브라우저(localStorage)에 저장된다.
 * - 사이드바 '비상 정지'는 에이전트와 연결된 동안 언제나 누를 수 있다 (진행 중·대기 중인 동작을 끊고 입력 해제).
 * - 키보드 시나리오는 입력창에 포커스가 있을 때만 키를 보낸다 (다른 앱에 입력되는 사고 방지).
 * - WinUSB 드라이버는 사용자가 1단계의 [드라이버 자동 설치]를 누를 때만 설치를 요청한다 (에이전트가 UAC 확인 창을 띄움).
 * - 버전 표시: SW_VERSION(SemVer, 승인 후 변경) · BUILD_TAG(YYYYMMDDvN, scripts/bump_build_tag.ps1 로 갱신)
 */
(() => {
  const API_BASE = "http://127.0.0.1:18080";
  const TOTAL_CLICKS = 5;
  const POLL_INTERVAL_MS = 1800; // 에이전트와 연결된 동안
  const POLL_INTERVAL_IDLE_MS = 5000; // 에이전트가 없거나 토큰을 기다리는 동안 (요청·콘솔 기록 줄이기)
  const TOKEN_KEY = "vm.apiToken";
  const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,256}$/;
  const FETCH_TIMEOUT_MS = 10000; // 상태 조회 등 짧은 요청
  const FIRMWARE_TIMEOUT_MS = 180000; // 펌웨어 다운로드·플래싱
  const DRIVER_INSTALL_TIMEOUT_MS = 340000; // 에이전트가 UAC 응답(120초)·설치(180초)·확인(15초)을 기다리는 시간보다 길게
  // 에이전트가 직접 서빙하는 로컬 가이드인지 (트레이가 #token= 으로 토큰을 넘기는 곳은 여기뿐이다)
  const IS_LOCAL_GUIDE = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(location.origin);
  const SW_VERSION = "v1.3.0";
  const BUILD_TAG = "20261124v12";

  const swLabel = document.getElementById("swVersionLabel");
  if (swLabel) swLabel.textContent = `SW ${SW_VERSION} · ${BUILD_TAG}`;

  const TAB_TITLES = {
    install: "설치하기",
    test: "테스트",
    logs: "로그 · 구동",
    guide: "안내 (API)",
  };

  const el = {
    sidebar: document.getElementById("sidebar"),
    btnToggleDrawer: document.getElementById("btnToggleDrawer"),
    pageTitle: document.getElementById("pageTitle"),
    navItems: Array.from(document.querySelectorAll(".nav-item")),
    tabPanels: Array.from(document.querySelectorAll(".tab-panel")),

    agentBadge: document.getElementById("agentBadge"),
    btnEmergencyStop: document.getElementById("btnEmergencyStop"),
    sidebarMsg: document.getElementById("sidebarMsg"),
    fwBadge: document.getElementById("fwBadge"),
    runBadge: document.getElementById("runBadge"),

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
    agentInstallHint: document.getElementById("agentInstallHint"),
    driverHint: document.getElementById("driverHint"),
    driverAuto: document.getElementById("driverAuto"),
    driverCurrent: document.getElementById("driverCurrent"),
    btnInstallDriver: document.getElementById("btnInstallDriver"),
    driverMsg: document.getElementById("driverMsg"),
    step1Msg: document.getElementById("step1Msg"),
    tokenBox: document.getElementById("tokenBox"),
    tokenInput: document.getElementById("tokenInput"),
    btnSaveToken: document.getElementById("btnSaveToken"),
    btnClearToken: document.getElementById("btnClearToken"),
    tokenMsg: document.getElementById("tokenMsg"),

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

    runtimeStatusTag: document.getElementById("runtimeStatusTag"),
    btnToggleRun: document.getElementById("btnToggleRun"),
    btnQuitAgent: document.getElementById("btnQuitAgent"),
    btnRefreshLogs: document.getElementById("btnRefreshLogs"),
    btnClearServerLogs: document.getElementById("btnClearServerLogs"),
    btnCopyServerLogs: document.getElementById("btnCopyServerLogs"),
    btnForgetToken: document.getElementById("btnForgetToken"),
    runtimeMsg: document.getElementById("runtimeMsg"),
    serverLogBox: document.getElementById("serverLogBox"),
  };

  let activeTab = "install";
  let serverOnline = false;
  let serverPaused = false;
  let testRunning = false;
  let stopRequested = false;
  let clickCount = 0;
  let calibration = null;
  let pollInFlight = false;
  let flashing = false;
  let installingDriver = false;

  // --- API 토큰 (브라우저별 저장, 저장소를 쓸 수 없으면 이 창에서만 기억) ---
  let apiToken = readStoredToken();

  function readStoredToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return "";
    }
  }

  function storeToken(value) {
    apiToken = value || "";
    try {
      if (apiToken) localStorage.setItem(TOKEN_KEY, apiToken);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      // 저장소를 막아 둔 브라우저: 이 창에서만 기억한다
    }
  }

  // 트레이 '대시보드 보기'가 여는 로컬 가이드 주소(#token=...)에서 토큰을 받아 저장하고 주소창에서 지운다.
  // 공개 사이트에서는 받지 않는다: 아무 사이트나 링크로 저장된 토큰을 덮어쓰지 못하게 (주소창에서는 지운다).
  function takeTokenFromHash() {
    const match = location.hash.match(/^#token=([A-Za-z0-9_-]{32,256})$/);
    if (!match) return false;
    if (IS_LOCAL_GUIDE) storeToken(match[1]);
    history.replaceState(null, "", `${location.pathname}${location.search}#install`);
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

  // 굵은 글씨가 섞인 안내문을 innerHTML 없이 만든다: setRich(node, "앞 ", { strong: "강조" }, " 뒤")
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

  // --- Sidebar Tab Navigation ---
  function switchTab(tab) {
    if (!TAB_TITLES[tab]) tab = "install";
    activeTab = tab;
    el.pageTitle.textContent = TAB_TITLES[tab];
    el.navItems.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
    el.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
    el.sidebar.classList.remove("open");
    if (location.hash !== `#${tab}`) {
      history.replaceState(null, "", `#${tab}`);
    }
    if (tab === "logs") {
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
    node.textContent = text;
    node.className = `status-tag ${cls}`.trim();
  }

  function setCardState(card, state) {
    card.classList.remove("active", "done");
    if (state) card.classList.add(state);
  }

  // timeoutMs: 0 이면 기다림 제한 없음 (마우스·키보드 동작은 길 수 있고, 멈추려면 비상 정지를 쓴다)
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
      throw err; // 연결 자체가 안 됨 (에이전트 미실행 등)
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

  function updateUI(status) {
    renderStatus(status);
    applyBusyLocks();
  }

  // 플래싱·드라이버 설치·테스트 중에는 폴링 결과와 상관없이 관련 버튼을 잠근다 (중복 실행 방지)
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
    serverOnline = true;
    serverPaused = Boolean(status.paused);

    el.agentBadge.textContent = status.busy ? "로컬 서버 연결됨 (작업 중)" : "로컬 서버 연결됨";
    el.agentBadge.className = "pill online";
    el.btnEmergencyStop.disabled = false;
    el.agentInstallHint.classList.add("hidden");
    el.tokenBox.classList.add("hidden");
    setTag(el.step3Status, "연결됨", "ok");
    setCardState(el.step3Card, "done");

    el.runBadge.textContent = serverPaused ? "구동: 일시 중지" : "구동: 실행 중";
    el.runBadge.className = serverPaused ? "pill warn" : "pill online";
    setTag(el.runtimeStatusTag, serverPaused ? "일시 중지" : "실행 중", serverPaused ? "warn" : "ok");
    el.btnToggleRun.disabled = false;
    el.btnToggleRun.textContent = serverPaused ? "서비스 시작" : "서비스 중지";
    el.btnQuitAgent.disabled = false;

    const st = status.state;
    const fw = status.firmware_version || "-";
    el.fwBadge.textContent = `펌웨어: ${fw}`;

    el.pillMouse.textContent = `HID 마우스: ${status.hid_mouse ? "정상" : "미인식"}`;
    el.pillMouse.className = `mini-pill ${status.hid_mouse ? "ok" : ""}`;
    el.pillKeyboard.textContent = `HID 키보드: ${status.hid_keyboard ? "정상" : "미인식"}`;
    el.pillKeyboard.className = `mini-pill ${status.hid_keyboard ? "ok" : ""}`;
    el.pillPort.textContent = `포트: ${status.port || "-"}`;
    el.pillPort.className = `mini-pill ${status.port ? "ok" : ""}`;

    // WinUSB 드라이버가 없는 DFU 장치: 자동 설치(에이전트에 wdi-simple 이 있을 때)와 Zadig 수동 안내를 함께 보인다
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
    setTag(el.step4Status, serverPaused ? "서비스 중지됨" : "장치 준비 대기");
    setCardState(el.step4Card, "");

    if (serverPaused) return;

    if (st === "outdated") {
      setTag(el.step1Status, "업데이트 필요", "warn");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "현재 펌웨어(", { strong: `v${fw}` }, ")가 구버전입니다. 아래 버튼으로 자동 업데이트할 수 있습니다.");
      el.jumperDiagram.classList.add("hidden");
      el.btnFlashLocal.disabled = false;
      el.btnRemoteUpdate.classList.remove("hidden");
      return;
    }

    if (st === "port_busy") {
      // 펌웨어는 설치돼 있으니 점퍼·설치 안내 대신 포트를 점유한 프로그램을 알려 준다
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
      setTag(el.step1Status, "점퍼 접촉 필요", "warn");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "순정 Arduino Uno R3가 감지되었습니다. ", { strong: "USB 쪽 2핀(RESET-GND)" }, "을 점퍼선으로 1초간 접촉했다 떼어 주세요.");
      el.btnFlashLocal.disabled = true;
    } else {
      setTag(el.step1Status, "보드 미연결");
      setCardState(el.step1Card, "active");
      setRich(el.step1Desc, "Arduino Uno R3를 USB 포트에 연결해 주세요.");
      el.btnFlashLocal.disabled = true;
    }
  }

  function disableAgentControls() {
    serverOnline = false;
    el.fwBadge.textContent = "펌웨어: -";
    el.runBadge.className = "pill muted";
    el.driverHint.classList.add("hidden");
    setCardState(el.step3Card, "active");
    el.btnToggleRun.disabled = true;
    el.btnQuitAgent.disabled = true;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnFlashLocal.disabled = true;
    el.btnInstallDriver.disabled = true;
    el.btnRemoteUpdate.classList.add("hidden");
    el.btnEmergencyStop.disabled = true;
  }

  function updateOfflineUI() {
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버 미실행";
    el.agentBadge.className = "pill offline";
    el.runBadge.textContent = "구동: 미연결";
    el.agentInstallHint.classList.remove("hidden");
    el.tokenBox.classList.add("hidden");
    setTag(el.step3Status, "미연결", "warn");
    setTag(el.runtimeStatusTag, "미연결", "warn");
  }

  // 에이전트는 떠 있지만 응답이 없거나(시간 초과) 오류로 답한 상태: 설치 안내 대신 상태를 그대로 알려 준다
  function updateAgentErrorUI(message) {
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버 응답 오류";
    el.agentBadge.className = "pill warn";
    el.runBadge.textContent = "구동: 확인 필요";
    el.agentInstallHint.classList.add("hidden");
    el.tokenBox.classList.add("hidden");
    setTag(el.step3Status, "응답 오류", "warn");
    setTag(el.runtimeStatusTag, "응답 오류", "warn");
    setInlineMsg(el.sidebarMsg, message, "warn");
  }

  // 에이전트는 실행 중이지만 토큰이 없거나 틀린 상태
  function updateAuthRequiredUI() {
    disableAgentControls();
    el.agentBadge.textContent = "로컬 서버: 토큰 필요";
    el.agentBadge.className = "pill warn";
    el.runBadge.textContent = "구동: 인증 대기";
    el.agentInstallHint.classList.add("hidden");
    el.tokenBox.classList.remove("hidden");
    setTag(el.step3Status, "토큰 필요", "warn");
    setTag(el.runtimeStatusTag, "토큰 필요", "warn");
  }

  async function fetchServerLogs() {
    if (!serverOnline) {
      el.serverLogBox.textContent = "로컬 서버에 연결되어 있지 않습니다. (설치하기 탭 3단계를 확인하세요)";
      return;
    }
    try {
      const data = await apiFetch("/logs");
      const lines = data.lines || [];
      el.serverLogBox.textContent = lines.length ? lines.slice().reverse().join("\n") : "아직 기록된 서버 로그가 없습니다.";
    } catch (err) {
      el.serverLogBox.textContent =
        err instanceof AuthRequiredError ? "API 토큰이 필요합니다. 설치하기 탭 3단계에서 토큰을 입력하세요." : `서버 로그를 불러올 수 없습니다: ${err.message}`;
    }
  }

  async function pollStatus() {
    // 에이전트가 긴 동작(플래싱·타이핑)으로 바쁠 때 요청이 쌓이지 않게 한 번에 하나만 보낸다
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      const status = await apiFetch("/status");
      // 연결이 돌아오면 '응답 오류' 같은 경고만 지운다 ('비상 정지 완료' 같은 안내는 남긴다)
      if (el.sidebarMsg.classList.contains("warn")) setInlineMsg(el.sidebarMsg, "");
      updateUI(status);
      if (activeTab === "logs") {
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

  // --- Install Actions ---
  // 플래싱은 수십 초 걸릴 수 있다: 진행·결과를 1단계 카드에 바로 보여 주고, 끝날 때까지 버튼을 잠근다
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

  // WinUSB 드라이버 자동 설치: 사용자가 이 버튼을 누를 때만 요청하고, UAC 확인 창에서 [예]를 눌러야 진행된다
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
      // 설치는 끝났지만 장치에 아직 적용되지 않은 경우(verified=false)는 주의 색으로 보인다
      const kind = res.ok && res.verified !== false ? "ok" : "warn";
      setInlineMsg(el.driverMsg, text, kind);
      // 설치되면 안내 상자가 사라지므로 결과를 1단계 메시지에도 남긴다
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

  // --- Mouse Live Click Test ---
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

  // 비상 정지: 서버가 진행 중인 동작을 끊고, 그 전에 줄 서 있던 요청도 취소한 뒤 눌린 버튼·키를 모두 해제한다
  async function emergencyStop() {
    stopRequested = true;
    try {
      await apiFetch("/action", { method: "POST", body: JSON.stringify({ action: "release_all" }) });
      log("비상 정지: 진행 중인 동작을 끊고 눌린 버튼·키를 모두 해제했습니다.");
      setInlineMsg(el.sidebarMsg, "비상 정지 완료", "ok");
    } catch (err) {
      const msg = `비상 정지 요청 실패: ${err.message} (USB 케이블을 뽑으면 즉시 멈춥니다)`;
      log(msg);
      setInlineMsg(el.sidebarMsg, msg, "warn");
    }
  }

  el.btnStopTest.addEventListener("click", emergencyStop);
  el.btnEmergencyStop.addEventListener("click", emergencyStop);

  // 마우스로 직접 누른 클릭인지: 키보드(Enter·Space)나 스크립트로 누르면 좌표가 0이라 화면 위치를 맞출 수 없다
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

  // --- Keyboard Scenario Test ---
  function markKbdStep(stepIdx, state) {
    el.kbdSteps.forEach((li) => {
      const idx = Number(li.dataset.step);
      if (idx < stepIdx) {
        li.className = "done";
      } else if (idx === stepIdx) {
        li.className = state;
      } else {
        li.className = "";
      }
    });
  }

  // 키를 보내기 전에 매번 확인: 이 창이 포커스를 갖고 있고 입력창이 선택돼 있어야 한다.
  // 아니면 Ctrl+A·Backspace 가 다른 앱의 내용을 지울 수 있으므로 키를 보내지 않고 멈춘다.
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

  el.btnQuitAgent.addEventListener("click", async () => {
    if (!confirm("VirtualMouse 트레이 에이전트를 완전히 종료할까요?")) return;
    try {
      await apiFetch("/control/quit", { method: "POST", body: "{}" });
      setInlineMsg(el.runtimeMsg, "에이전트를 종료했습니다.", "ok");
      setTimeout(pollStatus, 600);
    } catch (err) {
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

  // Register minimal Service Worker for PWA address-bar install button
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch((err) => {
      console.warn("Service worker registration failed:", err);
    });
  }

  // Initial route from URL hash
  const initialHash = location.hash.replace("#", "");
  if (TAB_TITLES[initialHash]) {
    switchTab(initialHash);
  }

  // 뒤로 가기·주소 직접 입력으로 # 이 바뀌면 탭을 따라 바꾸고, #token= 이면 토큰을 받는다
  window.addEventListener("hashchange", () => {
    if (takeTokenFromHash()) {
      switchTab("install");
      pollStatus();
      return;
    }
    const tab = location.hash.replace("#", "");
    if (TAB_TITLES[tab] && tab !== activeTab) switchTab(tab);
  });

  function schedulePoll() {
    setTimeout(async () => {
      await pollStatus();
      schedulePoll();
    }, serverOnline ? POLL_INTERVAL_MS : POLL_INTERVAL_IDLE_MS);
  }

  pollStatus().finally(schedulePoll);
})();
