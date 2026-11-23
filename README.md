# VirtualMouse — Arduino USB HID Mouse & Keyboard Automation

**Arduino Uno R3 (`ATmega16U2`) 기반 물리 USB HID Mouse & Keyboard + 사람 움직임 엔진 + 로컬 JSON API 서버 + All-in-One 웹 가이드 프로젝트**입니다.

OS와 보안 프로그램 입장에서 **100% 실제 물리 USB 마우스·키보드(`mouhid` / `kbdhid`)**로 인식되며, Windows 드라이버 서명이나 `testsigning` 모드 없이 안전하게 동작합니다.

> **Service URL**: https://virtual-mouse.iseohyun.com  
> **Keywords**: `HID`, `Mouse`, `Keyboard`, `Arduino`, `Uno R3`, `ATmega16U2`, `Human-like Motion`, `Local JSON API`, `Virtual Mouse`

---

## 1. 프로젝트 구조 & Git 관리 전략 (Monorepo)

아두이노 펌웨어(C++), PC 로컬 API 서버 및 사람 움직임 엔진(Python), 웹 가이드(HTML/CSS/JS), 자동화 스크립트(PowerShell)를 **단일 저장소(Monorepo)**로 관리합니다.  
외부 바이너리·가상환경·빌드 산출물은 `.gitignore`로 제외되며, 새 PC에서는 `.\scripts\setup.ps1` 한 번으로 동일 환경을 재현할 수 있습니다.

```text
VirtualMouse/
├── firmware/
│   └── uno_16u2_mouse/
│       └── uno_16u2_mouse.ino     # [v1.1.0] MultiReport USB HID Mouse + Keyboard + VER + BOOT
├── host/
│   ├── mouse_client.py            # 저수준 시리얼(COM) 통신 클라이언트
│   ├── keycodes.py                # USB HID Usage ID 키코드 매핑 테이블
│   ├── human_motion.py            # 베지어 곡선 + Minimum-Jerk + 손떨림 + 오버슈트 + DPI 피드백 엔진
│   ├── device_status.py           # USB 상태 자동 판별 (ready/outdated/dfu_ready/stock_uno/no_device)
│   ├── updater.py                 # 원격 펌웨어 자동 체크·다운로드·SHA-256 검증·DFU 갱신 (단독 CLI 지원)
│   ├── server.py                  # 로컬 HTTP JSON API 서버 (127.0.0.1:18080, CORS/PNA, /guide 서빙)
│   ├── test_mouse.py              # 직접 시리얼 연결 테스트
│   ├── test_api.py                # 로컬 HTTP API 통합 테스트
│   ├── requirements.txt           # 런타임 의존성 (pyserial==3.5)
│   └── requirements-dev.txt       # 빌드 의존성 (pyinstaller>=6.0.0)
├── web/
│   ├── index.html                 # Auto Clicker Guide (1~4단계 스텝퍼 + SVG 핀 도식 + 라이브 테스트)
│   ├── styles.css                 # 단일 중앙 스타일시트
│   └── app.js                     # /status 폴링, 1·2단계 자동 스킵, 랜덤 버튼 자동 클릭 데모
├── scripts/
│   ├── setup.ps1                  # 새 PC 원클릭 개발 환경 세팅
│   ├── flash_mouse_firmware.ps1   # 펌웨어 컴파일 + DFU 직접 플래싱
│   ├── restore_stock_uno.ps1      # 순정 Arduino Uno R3 복구
│   ├── provision_uno.ps1          # 새 Uno R3 원클릭 프로비저닝
│   ├── build_release.ps1          # 원격 배포용 .hex + SHA-256 latest.json 생성
│   └── build_agent.ps1            # 단일 실행 파일(dist/VirtualMouse-Agent.exe) 빌드
├── docs/
│   └── MILESTONES.md              # 1~6단계 개발 마일스톤
└── .gitignore                     # .venv/, tools/, firmware_bins/, build/, dist/ 제외
```

---

## 2. 사전 준비 (Prerequisites) 및 의존성

### 하드웨어
* **Arduino Uno R3 (`ATmega16U2` 탑재 정품 계열, `VID_2341` / `PID_0043`)**
  * *저가형 CH340 칩 사용 호환 보드는 USB HID 모드를 지원하지 않습니다.*
* **점퍼선 1개** (최초 1회 DFU 모드 진입용; 이후 업데이트는 소프트웨어 `BOOT` 명령으로 점퍼 불필요)

### 소프트웨어 의존성 (`.\scripts\setup.ps1` 자동 설치)
| 구분 | 도구 / 패키지 | 버전 / 출처 | 용도 |
| :--- | :--- | :--- | :--- |
| 런타임 | Python | 3.12+ | 로컬 서버 및 매크로 클라이언트 |
| Python 패키지 | `pyserial` | `3.5` | PC ↔ Arduino COM 포트 통신 |
| 빌드 도구 | `pyinstaller` | `6.x` (`requirements-dev.txt`) | 단일 `VirtualMouse-Agent.exe` 패키징 |
| Arduino CLI | `arduino-cli` | `ArduinoSA.CLI` (winget) | 펌웨어 컴파일 |
| Arduino 코어 | `arduino:avr`, `HoodLoader2:avr` | `1.8.8` / `2.0.5` | `ATmega16U2` 빌드 환경 |
| Arduino 라이브러리 | `HID-Project` | `2.8.4` | MultiReport USB HID 마우스+키보드 |
| DFU 도구 | `dfu-programmer`, `Zadig` | `v1.1.0` / `v2.9` | `ATmega16U2` 플래싱 및 `WinUSB` 드라이버 |

---

## 3. 빠른 시작 (Quick Start)

### A. 개발 환경 세팅 및 최초 플래싱
```powershell
# 1) 모든 의존성/도구 자동 설치
.\scripts\setup.ps1

# 2) Uno R3 USB 포트 바로 옆 6핀 헤더 중 가장 가까운 2핀(RESET-GND)을 점퍼선으로 1초 접촉
# 3) 최초 1회: tools\zadig.exe -> Options -> List All Devices -> Unknown Device #1 (03EB:2FEF) -> WinUSB 설치
# 4) USB HID 마우스+키보드 펌웨어 컴파일 및 플래싱
.\scripts\flash_mouse_firmware.ps1

# 5) USB 케이블을 뺐다가 다시 연결 (HID 마우스 + HID 키보드 + COM 포트 자동 인식)
```

### B. 로컬 API 서버 & 웹 가이드 실행
```powershell
.\.venv\Scripts\python.exe host\server.py --open-guide
```
* 기본 주소: `http://127.0.0.1:18080`
* 웹 가이드 & 라이브 클릭 테스트: `http://127.0.0.1:18080/guide`

### C. 단일 실행 파일(`VirtualMouse-Agent.exe`) 빌드
```powershell
.\.venv\Scripts\python.exe -m pip install -r host\requirements-dev.txt
.\scripts\build_agent.ps1
# -> dist\VirtualMouse-Agent.exe 생성 (더블클릭 시 서버 기동 + 브라우저 가이드 자동 오픈)
```

---

## 4. 로컬 HTTP JSON API 명세 (`http://127.0.0.1:18080`)

외부 프로그램(Python, C#, Node.js, PowerShell, AutoHotkey, 웹페이지 등)은 `POST /action`에 **JSON(`{...}`)**만 전달하면 됩니다. 모든 이동·클릭·타이핑은 기본값(`"human": true`)으로 사람처럼 자연스럽게 실행됩니다.

| 엔드포인트 / 액션 | 요청 예시 (`JSON`) | 설명 |
| :--- | :--- | :--- |
| `GET /health` | - | 아두이노 PING, 펌웨어 버전, 커서 좌표 |
| `GET /status` | - | USB 상태 자동 판별 (`ready` / `outdated` / `dfu_ready` / `stock_uno` / `no_device`) |
| `POST /firmware/check` | `{"manifest_url": "..."}` | 원격 `latest.json`과 현재 버전 비교 |
| `POST /firmware/update` | `{"use_local": true}` 또는 `{}` | SHA-256 검증 후 소프트웨어 `BOOT` → DFU 자동 갱신 |
| `POST /action` (상대 이동) | `{"action": "move", "dx": 150, "dy": -80}` | 베지어 곡선 + 가감속 + 미세 손떨림 |
| `POST /action` (절대 이동) | `{"action": "move_to", "x": 800, "y": 500}` | DPI/가속 보정 포함 목표 픽셀 안착 |
| `POST /action` (클릭) | `{"action": "click", "button": "L"}` | 자연스러운 누름 유지 시간 (`L`/`R`/`M`) |
| `POST /action` (이동+클릭) | `{"action": "click_at", "x": 800, "y": 500}` | 곡선 이동 → 짧은 정지 → 클릭 |
| `POST /action` (드래그) | `{"action": "drag", "from_x": 300, "from_y": 300, "to_x": 600, "to_y": 400}` | 자연스러운 드래그 앤 드롭 |
| `POST /action` (스크롤) | `{"action": "scroll", "delta": -3}` | 자연스러운 간격으로 휠 스크롤 |
| `POST /action` (타이핑) | `{"action": "type", "text": "Hello HID!"}` | 사람 같은 랜덤 간격으로 물리 키보드 입력 |
| `POST /action` (단축키) | `{"action": "hotkey", "keys": ["ctrl", "c"]}` | 모디파이어 순차 누름 → 역순 해제 |
| `POST /action` (연속 실행) | `{"actions": [{"action": "move_to", "x": 500, "y": 500}, {"action": "click"}]}` | 다중 액션 순차 실행 |
| `POST /action` (비상 해제) | `{"action": "release_all"}` | 눌린 모든 마우스 버튼·키보드 키 즉시 해제 |

---

## 5. 원격 펌웨어 릴리즈 & 순정 복구

* **원격 릴리즈 패키지 생성**: `.\scripts\build_release.ps1 -Version "1.1.0" -BaseUrl "https://virtual-mouse.iseohyun.com/releases"` → `dist\releases\uno_16u2_mouse_1.1.0.hex` + `latest.json` 생성
* **Guide 없이 단독 업데이터 CLI 실행**: `.\.venv\Scripts\python.exe host\updater.py --check` / `--update`
* **순정 Arduino Uno R3 원복**: DFU 모드 진입 후 `.\scripts\restore_stock_uno.ps1` 실행
