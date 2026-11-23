(() => {
  const API_BASE = "http://127.0.0.1:18080";
  const TOTAL_CLICKS = 5;

  const el = {
    agentBadge: document.getElementById("agentBadge"),
    fwBadge: document.getElementById("fwBadge"),
    step1Card: document.getElementById("step1Card"),
    step2Card: document.getElementById("step2Card"),
    step3Card: document.getElementById("step3Card"),
    step4Card: document.getElementById("step4Card"),
    step1Status: document.getElementById("step1Status"),
    step2Status: document.getElementById("step2Status"),
    step3Status: document.getElementById("step3Status"),
    step4Status: document.getElementById("step4Status"),
    step1Desc: document.getElementById("step1Desc"),
    step2Desc: document.getElementById("step2Desc"),
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
    logBox: document.getElementById("logBox"),
  };

  let testRunning = false;
  let stopRequested = false;
  let clickCount = 0;
  // 클릭 시점 실시간 캘리브레이션: { winX, winY, clientX, clientY, dpr }
  let calibration = null;

  function log(msg) {
    const ts = new Date().toLocaleTimeString();
    el.logBox.textContent = `[${ts}] ${msg}\n` + el.logBox.textContent;
  }

  // 경량 클라이언트 진단 로그 (7장 방식: 화면 오류를 로그 박스에 기록)
  window.addEventListener("error", (e) => {
    log(`[DIAG:error] ${e.message || "unknown error"}`);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason && e.reason.message ? e.reason.message : String(e.reason);
    log(`[DIAG:promise] ${reason}`);
  });

  // 테스트 중 실제 클릭이 페이지 어디에 떨어졌는지 디버그 추적
  document.addEventListener(
    "click",
    (e) => {
      if (!testRunning) return;
      const targetId = e.target && e.target.id ? `#${e.target.id}` : e.target ? e.target.tagName : "unknown";
      log(`[DEBUG:click] landed on ${targetId} at client=(${Math.round(e.clientX)}, ${Math.round(e.clientY)}) screen=(${Math.round(e.screenX)}, ${Math.round(e.screenY)})`);
    },
    true
  );

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

  /**
   * 클릭 이벤트 시점의 브라우저 client 좌표와 로컬 서버의 Windows 물리 커서 좌표를
   * 1:1 매칭해 툴바·창 보더·DPI·듀얼모니터 오차를 0px로 캘리브레이션합니다.
   */
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
      log(
        `[CALIB] ok: click client=(${Math.round(mouseEvent.clientX)}, ${Math.round(mouseEvent.clientY)}) -> win=(${health.cursor.x}, ${health.cursor.y}), dpr=${dpr}`
      );
      return true;
    }
    calibration = null;
    log(`[CALIB] fallback (server cursor=null), dpr=${dpr}, screen=(${window.screenX},${window.screenY}), outer=(${window.outerWidth}x${window.outerHeight}), inner=(${window.innerWidth}x${window.innerHeight})`);
    return false;
  }

  /**
   * DOM 요소의 정중앙을 Windows 물리 화면 픽셀 좌표(x, y)로 변환합니다.
   * 캘리브레이션 기준점이 있으면 오차 0으로 계산하고, 없으면 창 크기 기반 추정치를 사용합니다.
   */
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
    const cssX = window.screenX + chromeBorderX + elemClientX;
    const cssY = window.screenY + chromeTopY + elemClientY;
    return {
      x: Math.round(cssX * dpr),
      y: Math.round(cssY * dpr),
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
    const nextX = Math.floor(pad + Math.random() * (maxX - pad));
    const nextY = Math.floor(pad + Math.random() * (maxY - pad));
    el.targetBtn.style.left = `${nextX}px`;
    el.targetBtn.style.top = `${nextY}px`;
  }

  function updateUI(status) {
    // Agent online
    el.agentBadge.textContent = "로컬 서버 연결됨";
    el.agentBadge.className = "pill online";
    el.agentInstallHint.classList.add("hidden");
    setTag(el.step3Status, "연결됨", "ok");
    setCardState(el.step3Card, "done");

    const st = status.state;
    const fw = status.firmware_version || "-";
    el.fwBadge.textContent = `펌웨어: ${fw}`;

    el.pillMouse.textContent = `HID 마우스: ${status.hid_mouse ? "정상" : "미인식"}`;
    el.pillMouse.className = `mini-pill ${status.hid_mouse ? "ok" : ""}`;
    el.pillKeyboard.textContent = `HID 키보드: ${status.hid_keyboard ? "정상" : "미인식"}`;
    el.pillKeyboard.className = `mini-pill ${status.hid_keyboard ? "ok" : ""}`;
    el.pillPort.textContent = `포트: ${status.port || "-"}`;
    el.pillPort.className = `mini-pill ${status.port ? "ok" : ""}`;

    if (st === "ready") {
      // 1·2단계 자동 스킵
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
    setTag(el.step4Status, "장치 준비 대기");
    setCardState(el.step4Card, "");

    if (st === "outdated") {
      setTag(el.step1Status, "업데이트 필요", "warn");
      setCardState(el.step1Card, "active");
      el.step1Desc.innerHTML = `현재 펌웨어(<strong>v${fw}</strong>)가 구버전입니다. 아래 버튼으로 점퍼 없이 자동 업데이트할 수 있습니다.`;
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
      el.step1Desc.innerHTML = "순정 Arduino Uno R3가 감지되었습니다. 위 그림의 <strong>USB 쪽 2핀(RESET-GND)</strong>을 점퍼선으로 1초간 접촉했다 떼어 주세요.";
      el.btnFlashLocal.disabled = true;
    } else {
      setTag(el.step1Status, "보드 미연결");
      setCardState(el.step1Card, "active");
      el.step1Desc.innerHTML = "Arduino Uno R3를 USB 포트에 연결해 주세요.";
      el.btnFlashLocal.disabled = true;
    }
  }

  function updateOfflineUI() {
    el.agentBadge.textContent = "로컬 서버 미실행";
    el.agentBadge.className = "pill offline";
    el.fwBadge.textContent = "펌웨어: -";
    el.agentInstallHint.classList.remove("hidden");
    setTag(el.step3Status, "미연결", "warn");
    setCardState(el.step3Card, "active");
    el.btnStartClickTest.disabled = true;
    el.btnKbdTest.disabled = true;
    el.btnFlashLocal.disabled = true;
  }

  async function pollStatus() {
    try {
      const status = await apiFetch("/status");
      updateUI(status);
    } catch {
      updateOfflineUI();
    }
  }

  // --- Event Listeners ---
  el.btnFlashLocal.addEventListener("click", async () => {
    try {
      el.btnFlashLocal.disabled = true;
      log("로컬 펌웨어 플래싱을 시작합니다...");
      const res = await apiFetch("/firmware/update", {
        method: "POST",
        body: JSON.stringify({ use_local: true }),
      });
      log(`플래싱 완료! USB 케이블을 뺐다가 다시 연결해 주세요. (${JSON.stringify(res.target_version || "")})`);
    } catch (err) {
      log(`플래싱 오류: ${err.message}`);
    }
  });

  el.btnRemoteUpdate.addEventListener("click", async () => {
    try {
      el.btnRemoteUpdate.disabled = true;
      log("원격 최신 펌웨어 업데이트를 시작합니다...");
      const res = await apiFetch("/firmware/update", {
        method: "POST",
        body: JSON.stringify({ force: false }),
      });
      log(`업데이트 결과: ${JSON.stringify(res)}`);
    } catch (err) {
      log(`업데이트 오류: ${err.message}`);
    } finally {
      el.btnRemoteUpdate.disabled = false;
    }
  });

  el.targetBtn.addEventListener("click", () => {
    if (!testRunning) {
      moveTargetRandomly();
      return;
    }
    clickCount += 1;
    el.scoreText.textContent = `진행: ${clickCount} / ${TOTAL_CLICKS}`;
    log(`타겟 버튼 클릭 확인! (${clickCount}/${TOTAL_CLICKS})`);
    moveTargetRandomly();
  });

  el.btnCopyLog.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(el.logBox.textContent);
      log("로그를 클립보드에 복사했습니다.");
    } catch {
      log("클립보드 복사 실패 — 로그 박스에서 직접 선택해 복사해 주세요.");
    }
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
    log("자동 클릭 테스트(5회)를 시작합니다...");

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
      await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({ action: "release_all" }),
      });
    } catch {
      // ignore
    }
  });

  el.btnKbdTest.addEventListener("click", async (evt) => {
    try {
      await calibrateFromEvent(evt);
      el.kbdInput.value = "";
      const pos = getElementScreenCenter(el.kbdInput);
      log(`입력창 win=(${pos.x}, ${pos.y}) 클릭 후 물리 키보드 타이핑 테스트...`);
      const res = await apiFetch("/action", {
        method: "POST",
        body: JSON.stringify({
          actions: [
            { action: "click_at", x: pos.x, y: pos.y, button: "L" },
            { action: "sleep", ms: 120 },
            { action: "type", text: "Hello Arduino HID!" },
          ],
        }),
      });
      log(`키보드 타이핑 테스트 완료! (${JSON.stringify(res.results && res.results[0] && res.results[0].cursor)})`);
    } catch (err) {
      log(`키보드 테스트 오류: ${err.message}`);
    }
  });

  pollStatus();
  setInterval(pollStatus, 1800);
})();
