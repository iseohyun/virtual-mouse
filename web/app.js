(() => {
  const API_BASE = "http://127.0.0.1:18080";
  const TOTAL_CLICKS = 5;
  const SW_VERSION = "v1.1.2";
  const BUILD_TAG = "20261124v5";

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
    serverLogBox: document.getElementById("serverLogBox"),
  };

  let activeTab = "install";
  let serverOnline = false;
  let serverPaused = false;
  let testRunning = false;
  let stopRequested = false;
  let clickCount = 0;
  let calibration = null;

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

  async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
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
    serverOnline = true;
    serverPaused = Boolean(status.paused);

    el.agentBadge.textContent = "로컬 서버 연결됨";
    el.agentBadge.className = "pill online";
    el.agentInstallHint.classList.add("hidden");
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

    if (st === "ready" && !serverPaused) {
      setTag(el.step1Status, "자동 스킵", "ok");
      setTag(el.step2Status, "완료", "ok");
      setCardState(el.step1Card, "done");
      setCardState(el.step2Card, "done");
      el.step1Desc.innerHTML = `최신 펌웨어(<strong>v${fw}</strong>)가 이미 설치되어 있어 1·2단계를 자동으로 건너뛰었습니다.`;
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
      el.step1Desc.innerHTML = `현재 펌웨어(<strong>v${fw}</strong>)가 구버전입니다. 아래 버튼으로 자동 업데이트할 수 있습니다.`;
      el.jumperDiagram.classList.add("hidden");
      el.btnFlashLocal.disabled = false;
      el.btnRemoteUpdate.classList.remove("hidden");
      return;
    }

    el.jumperDiagram.classList.remove("hidden");
    el.btnRemoteUpdate.classList.add("hidden");

    if (st === "dfu_ready") {
      setTag(el.step1Status, "DFU 감지됨", "warn");
      setCardState(el.step1Card, "active");
      el.step1Desc.innerHTML = status.dfu_driver_ok
        ? "DFU 모드와 WinUSB 드라이버가 확인되었습니다. <strong>[DFU 펌웨어 설치 실행]</strong>을 눌러 주세요."
        : "DFU 모드가 감지되었으나 WinUSB 드라이버 설치가 필요합니다.";
      el.btnFlashLocal.disabled = !status.dfu_driver_ok;
    } else if (st === "stock_uno") {
      setTag(el.step1Status, "점퍼 접촉 필요", "warn");
      setCardState(el.step1Card, "active");
      el.step1Desc.innerHTML = "순정 Arduino Uno R3가 감지되었습니다. <strong>USB 쪽 2핀(RESET-GND)</strong>을 점퍼선으로 1초간 접촉했다 떼어 주세요.";
      el.btnFlashLocal.disabled = true;
    } else {
      setTag(el.step1Status, "보드 미연결");
      setCardState(el.step1Card, "active");
      el.step1Desc.innerHTML = "Arduino Uno R3를 USB 포트에 연결해 주세요.";
      el.btnFlashLocal.disabled = true;
    }
  }

  function updateOfflineUI() {
    serverOnline = false;
    el.agentBadge.textContent = "로컬 서버 미실행";
    el.agentBadge.className = "pill offline";
    el.fwBadge.textContent = "펌웨어: -";
    el.runBadge.textContent = "구동: 미연결";
    el.runBadge.className = "pill muted";
    el.agentInstallHint.classList.remove("hidden");
    setTag(el.step3Status, "미연결", "warn");
    setCardState(el.step3Card, "active");
    setTag(el.runtimeStatusTag, "미연결", "warn");
    el.btnToggleRun.disabled = true;
    el.btnQuitAgent.disabled = true;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnFlashLocal.disabled = true;
  }

  async function fetchServerLogs() {
    if (!serverOnline) {
      el.serverLogBox.textContent = "로컬 서버가 실행 중이 아닙니다.";
      return;
    }
    try {
      const data = await apiFetch("/logs");
      const lines = data.lines || [];
      el.serverLogBox.textContent = lines.length ? lines.slice().reverse().join("\n") : "아직 기록된 서버 로그가 없습니다.";
    } catch {
      el.serverLogBox.textContent = "서버 로그를 불러올 수 없습니다.";
    }
  }

  async function pollStatus() {
    try {
      const status = await apiFetch("/status");
      updateUI(status);
      if (activeTab === "logs") {
        await fetchServerLogs();
      }
    } catch {
      updateOfflineUI();
    }
  }

  // --- Install Actions ---
  el.btnFlashLocal.addEventListener("click", async () => {
    try {
      el.btnFlashLocal.disabled = true;
      log("로컬 펌웨어 플래싱을 시작합니다...");
      await apiFetch("/firmware/update", { method: "POST", body: JSON.stringify({ use_local: true }) });
      log("플래싱 완료! USB 케이블을 뺐다가 다시 연결해 주세요.");
    } catch (err) {
      log(`플래싱 오류: ${err.message}`);
    }
  });

  el.btnRemoteUpdate.addEventListener("click", async () => {
    try {
      el.btnRemoteUpdate.disabled = true;
      log("원격 최신 펌웨어 업데이트 시작...");
      const res = await apiFetch("/firmware/update", { method: "POST", body: JSON.stringify({ force: false }) });
      log(`업데이트 결과: ${JSON.stringify(res)}`);
    } catch (err) {
      log(`업데이트 오류: ${err.message}`);
    } finally {
      el.btnRemoteUpdate.disabled = false;
    }
  });

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
        const res = await apiFetch("/action", {
          method: "POST",
          body: JSON.stringify({ action: "click_at", x: pos.x, y: pos.y, button: "L" }),
        });
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

  el.btnStopTest.addEventListener("click", async () => {
    stopRequested = true;
    try {
      await apiFetch("/action", { method: "POST", body: JSON.stringify({ action: "release_all" }) });
    } catch {
      // ignore
    }
  });

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

  el.btnKbdTest.addEventListener("click", async (evt) => {
    if (testRunning) return;
    testRunning = true;
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    setTag(el.kbdStatus, "실행 중", "warn");
    el.kbdInput.value = "";
    markKbdStep(0, "");

    try {
      await calibrateFromEvent(evt);
      const pos = getElementScreenCenter(el.kbdInput);

      markKbdStep(1, "active");
      log(`[KBD 1/5] 입력창(${pos.x}, ${pos.y}) 자동 클릭`);
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({ action: "click_at", x: pos.x, y: pos.y, button: "L" }),
      });

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
      setTag(el.kbdStatus, "오류", "warn");
      log(`키보드 시나리오 오류: ${err.message}`);
    } finally {
      testRunning = false;
      pollStatus();
    }
  });

  // --- Runtime Control & Server Logs ---
  el.btnToggleRun.addEventListener("click", async () => {
    try {
      el.btnToggleRun.disabled = true;
      const endpoint = serverPaused ? "/control/resume" : "/control/pause";
      await apiFetch(endpoint, { method: "POST", body: "{}" });
      await pollStatus();
    } catch (err) {
      log(`구동 전환 오류: ${err.message}`);
    }
  });

  el.btnQuitAgent.addEventListener("click", async () => {
    if (!confirm("VirtualMouse 트레이 에이전트를 완전히 종료할까요?")) return;
    try {
      await apiFetch("/control/quit", { method: "POST", body: "{}" });
      setTimeout(pollStatus, 600);
    } catch {
      pollStatus();
    }
  });

  el.btnRefreshLogs.addEventListener("click", fetchServerLogs);

  el.btnClearServerLogs.addEventListener("click", async () => {
    try {
      await apiFetch("/logs/clear", { method: "POST", body: "{}" });
      await fetchServerLogs();
    } catch {
      // ignore
    }
  });

  el.btnCopyServerLogs.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(el.serverLogBox.textContent);
    } catch {
      // ignore
    }
  });

  // --- API Guide Code Copy ---
  document.querySelectorAll(".copy-code").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = document.getElementById(btn.dataset.target);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent);
        const orig = btn.textContent;
        btn.textContent = "복사됨!";
        setTimeout(() => (btn.textContent = orig), 1200);
      } catch {
        // ignore
      }
    });
  });

  // Register minimal Service Worker for PWA address-bar install button
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  // Initial route from URL hash
  const initialHash = location.hash.replace("#", "");
  if (TAB_TITLES[initialHash]) {
    switchTab(initialHash);
  }

  pollStatus();
  setInterval(pollStatus, 1800);
})();
