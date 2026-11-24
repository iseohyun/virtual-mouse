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
│       └── uno_16u2_mouse.ino     # [FW 1.1.0] MultiReport USB HID Mouse + Keyboard + VER + BOOT
├── host/
│   ├── server.py                  # 에이전트 진입점 (인자 처리, 토큰 준비, 트레이, 종료)
│   ├── http_api.py                # 로컬 HTTP JSON API (Origin·Host 검사, Bearer 토큰, 라우팅, /guide 서빙)
│   ├── dispatcher.py              # 액션 실행기 (COM 잠금·재연결, 요청 상한, 비상 정지, 로그 가리기)
│   ├── auth.py                    # API 토큰 생성·저장·검사
│   ├── tray.py                    # 시스템 트레이 아이콘 (대시보드 보기 / API 토큰 복사 / 종료)
│   ├── cli.py                     # gh 스타일 명령줄 도구 `vm` (scripts\vm.cmd)
│   ├── mouse_client.py            # 저수준 시리얼(COM) 통신 클라이언트
│   ├── keycodes.py                # USB HID Usage ID 키코드 매핑 테이블
│   ├── human_motion.py            # 베지어 곡선 + Minimum-Jerk + 손떨림 + 오버슈트 + DPI 피드백 엔진
│   ├── device_status.py           # USB 상태 자동 판별 (ready/outdated/dfu_ready/stock_uno/no_device)
│   ├── updater.py                 # 원격 펌웨어 자동 체크·다운로드·SHA-256 검증·DFU 갱신 (단독 CLI 지원)
│   ├── driver_install.py          # DFU 장치 WinUSB 드라이버 설치 (wdi-simple + UAC, 사용자 요청 때만)
│   ├── test_mouse.py              # [수동·실기기] 직접 시리얼 연결 테스트
│   ├── test_api.py                # [수동·실기기] 로컬 HTTP API 통합 테스트
│   ├── requirements.txt           # 런타임 의존성 (버전 고정)
│   └── requirements-dev.txt       # 빌드 의존성 (버전 고정)
├── web/
│   ├── index.html                 # 대시보드 (설치 1~3단계, 테스트, 로그·구동, API 안내)
│   ├── styles.css                 # 단일 중앙 스타일시트
│   ├── app.js                     # /status 폴링, 토큰 입력, 자동 클릭·키보드 데모
│   └── sw.js, manifest.webmanifest, icon*  # PWA 설치용
├── tests/                         # 하드웨어 없이 도는 단위 테스트 (python -m unittest discover -s tests)
├── scripts/
│   ├── setup.ps1                  # 새 PC 원클릭 개발 환경 세팅 (버전·SHA-256 고정)
│   ├── flash_mouse_firmware.ps1   # 펌웨어 컴파일 + DFU 직접 플래싱
│   ├── restore_stock_uno.ps1      # 순정 Arduino Uno R3 복구
│   ├── provision_uno.ps1          # 새 Uno R3 원클릭 프로비저닝
│   ├── build_release.ps1          # 원격 배포용 .hex + SHA-256 latest.json 생성
│   ├── build_wdi.ps1              # WinUSB 드라이버 설치 도구 wdi-simple(libwdi) 재현 빌드 (소스·툴체인 고정)
│   ├── build_agent.ps1            # 단일 실행 파일(dist/VirtualMouse-Agent.exe) 빌드
│   ├── bump_build_tag.ps1         # 웹 캐시 버스팅 태그(YYYYMMDDvN) 갱신
│   └── vm.cmd                     # `vm` CLI 실행기 (.venv 사용)
├── .github/workflows/             # deploy.yml(Pages), release.yml(태그 릴리즈), test.yml(단위 테스트)
├── .agents/rules/                 # 프로젝트 규칙 (CSS·버전·보안·릴리즈)
├── docs/
│   └── MILESTONES.md              # 개발 마일스톤
└── .gitignore                     # .venv/, tools/, firmware_bins/, build/, dist/ 제외
```

---

## 2. 사전 준비 (Prerequisites) 및 의존성

### 하드웨어
* **Arduino Uno R3 (`ATmega16U2` 탑재 정품 계열, `VID_2341` / `PID_0043`)**
  * *저가형 CH340 칩 사용 호환 보드는 USB HID 모드를 지원하지 않습니다.*
* **점퍼선 1개** (최초 1회 DFU 모드 진입용; 이후 업데이트는 소프트웨어 `BOOT` 명령으로 점퍼 불필요)

### 소프트웨어 의존성 (`.\scripts\setup.ps1` 자동 설치, 모두 버전 고정)
외부에서 받는 파일은 SHA-256을 검사하며, 값이 다르거나 설치 명령(winget·arduino-cli·pip)이 실패하면 그 자리에서 멈춥니다. 사용자 전역 arduino-cli 설정은 바꾸지 않습니다(HoodLoader2 보드 인덱스는 명령마다 `--additional-urls`로 넘김). 버전을 올릴 때는 `scripts/setup.ps1`과 `.github/workflows/release.yml`의 값을 함께 바꿉니다(`tests/test_versions.py`가 두 파일이 같은지 확인).

| 구분 | 도구 / 패키지 | 고정 버전 / 출처 | 용도 |
| :--- | :--- | :--- | :--- |
| 런타임 | Python | 3.12 | 로컬 서버 및 매크로 클라이언트 |
| Python 패키지 | `pyserial`, `pystray`, `Pillow` | `3.5`, `0.19.5`, `13.0.0` | COM 통신, 트레이 아이콘 |
| 빌드 도구 | `pyinstaller`, `pyinstaller-hooks-contrib` | `6.22.3`, `2026.10` | 단일 `VirtualMouse-Agent.exe` 패키징 |
| Arduino CLI | `arduino-cli` | `1.6.0` (winget `ArduinoSA.CLI`) | 펌웨어 컴파일 |
| Arduino 코어 | `arduino:avr`, `HoodLoader2:avr` | `1.8.8` / `2.0.5` (보드 인덱스는 커밋 고정) | `ATmega16U2` 빌드 환경 |
| Arduino 라이브러리 | `HID-Project` | `2.8.4` | MultiReport USB HID 마우스+키보드 |
| DFU 도구 | `dfu-programmer`, `Zadig` | `v1.1.0` / `2.9` (SHA-256 검사) | `ATmega16U2` 플래싱 및 `WinUSB` 드라이버 (Zadig는 수동 설치용) |
| 드라이버 설치 도구 | libwdi `wdi-simple` | `v1.5.1` 커밋 고정, `scripts/build_wdi.ps1`로 빌드 | 에이전트의 `WinUSB` 드라이버 자동 설치 (WDK 8 재배포 코인스톨러, WinLibs GCC `16.2.0` 툴체인 모두 SHA-256 고정) |
| 펌웨어 원본 | HoodLoader2 / 순정 16U2 `.hex` | 커밋·태그 고정 (SHA-256 검사) | 부트로더·순정 복구 |

---

## 3. 빠른 시작 (Quick Start)

### A. 개발 환경 세팅 및 최초 플래싱
```powershell
# 1) 모든 의존성/도구 자동 설치
.\scripts\setup.ps1

# 2) Uno R3 USB 포트 바로 옆 6핀 헤더 중 가장 가까운 2핀(RESET-GND)을 점퍼선으로 1초 접촉
# 3) 최초 1회 WinUSB 드라이버: 대시보드 1단계 [드라이버 자동 설치] 또는 `vm driver-install` (UAC 창에서 [예])
#    수동 설치: tools\zadig.exe -> Options -> List All Devices -> Unknown Device #1 (03EB:2FEF) -> WinUSB 설치
# 4) USB HID 마우스+키보드 펌웨어 컴파일 및 플래싱
.\scripts\flash_mouse_firmware.ps1

# 5) USB 케이블을 뺐다가 다시 연결 (HID 마우스 + HID 키보드 + COM 포트 자동 인식)
```

### B. 로컬 API 서버 & 웹 가이드 실행
```powershell
.\.venv\Scripts\python.exe host\server.py --open-guide
```
* 기본 주소: `http://127.0.0.1:18080`
* 웹 가이드 & 라이브 클릭 테스트: `http://127.0.0.1:18080/guide` (트레이 **대시보드 보기**나 `--open-guide`로 열면 API 토큰이 자동 입력됩니다)

### C. 단일 실행 파일(`VirtualMouse-Agent.exe`) 빌드
```powershell
.\.venv\Scripts\python.exe -m pip install -r host\requirements-dev.txt
.\scripts\build_release.ps1   # 펌웨어 .hex
.\scripts\build_wdi.ps1       # WinUSB 드라이버 설치 도구 (처음 한 번 툴체인 약 280MB를 받아 tools\wdi-build\에 풂)
.\scripts\build_agent.ps1
# -> dist\VirtualMouse-Agent.exe 생성 (실행하면 CMD 창 없이 트레이 VM 아이콘으로 상주, 우클릭 메뉴로 대시보드 열기)
```
* `build_wdi.ps1`은 관리자 권한이 필요 없고 드라이버를 설치하지 않습니다. 같은 입력이면 같은 exe가 나오며(재현 가능 빌드), 결과 SHA-256도 스크립트에 고정돼 있습니다.

### WinUSB 드라이버 자동 설치 (DFU 장치 `03EB:2FEF`)
* 대시보드 1단계에 DFU 장치가 보이고 WinUSB 드라이버가 없을 때만 **[드라이버 자동 설치]** 버튼이 나옵니다. 에이전트가 스스로 설치하지는 않습니다.
* 버튼(또는 `vm driver-install`)을 누르면 Windows **사용자 계정 컨트롤** 창이 뜹니다. **[예]**를 눌러야 설치가 진행됩니다. 에이전트는 앞 창이 아니므로 창이 작업 표시줄의 깜빡이는 방패 아이콘으로만 뜰 수 있습니다.
* 설치에는 libwdi `wdi-simple`을 씁니다(Zadig와 같은 라이브러리). 드라이버 카탈로그를 서명하려고 `USB\VID_03EB&PID_2FEF (libwdi autogenerated)` 자체 서명 인증서를 이 PC의 신뢰할 수 있는 루트·게시자 저장소에 추가하고, 서명 뒤 개인 키는 지웁니다.
* 이미 다른 드라이버(예: libusb0)가 붙어 있으면 WinUSB로 바뀝니다. 자동 설치가 안 되면 대시보드의 Zadig 수동 안내를 쓰면 됩니다.
* `VirtualMouse-Agent.exe`와 `wdi-simple.exe`는 코드 서명이 없어 UAC 창에 "알 수 없는 게시자"로 보이고, 백신이 의심 파일로 볼 수 있습니다.

### D. 테스트 & 명령줄 도구
```powershell
# 하드웨어 없이 도는 단위 테스트 (CI에서도 같은 명령 실행)
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# vm CLI (에이전트 토큰을 자동으로 읽음)
.\scripts\vm.cmd status
.\scripts\vm.cmd token        # 외부 스크립트에 쓸 API 토큰 출력
.\scripts\vm.cmd release-all  # 비상 정지
.\scripts\vm.cmd driver-install  # DFU 장치에 WinUSB 드라이버 설치 (UAC 확인 창)
```
* `vm` 종료 코드: `1` 요청 오류, `2` 에이전트에 연결 안 됨, `3` 토큰 없음·틀림, `4` 응답 시간 초과(에이전트는 동작을 계속하고 있을 수 있으니 `vm logs`로 확인)

---

## 4. 로컬 HTTP JSON API 명세 (`http://127.0.0.1:18080`)

PC에서 실행하는 외부 프로그램(Python, C#, Node.js, PowerShell, AutoHotkey 등)은 `POST /action`에 **JSON(`{...}`)**만 전달하면 됩니다. 모든 이동·클릭·타이핑은 기본값(`"human": true`)으로 사람처럼 자연스럽게 실행됩니다.

### 인증 (API 토큰)
모든 API 요청에는 `Authorization: Bearer <토큰>` 헤더가 필요합니다. 토큰이 없거나 틀리면 `401`을 돌려줍니다.
* 에이전트가 처음 실행될 때 토큰을 만들어 `%LOCALAPPDATA%\VirtualMouse\api-token`에 저장합니다.
* 토큰 꺼내기: 트레이 메뉴 **API 토큰 복사**, `vm token`, 또는 위 파일 읽기.
* 공개 대시보드(https://virtual-mouse.iseohyun.com)에서는 3단계 카드에 토큰을 한 번 붙여 넣으면 그 브라우저에 저장됩니다.
* 토큰을 바꾸려면 파일을 지우고 에이전트를 다시 시작합니다. 환경 변수 `VMOUSE_API_TOKEN`으로 직접 지정할 수도 있습니다(32자 이상).

```powershell
$token = Get-Content "$env:LOCALAPPDATA\VirtualMouse\api-token"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:18080/action" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"action": "click_at", "x": 800, "y": 500, "button": "L"}'
```

### 보안 규칙과 요청 한도
* 브라우저에서는 `https://virtual-mouse.iseohyun.com`과 로컬 가이드(`http://127.0.0.1:18080`, `http://localhost:18080`)만 호출할 수 있습니다. **다른 웹페이지의 요청은 거부**됩니다(Origin·Host 검사).
* POST는 `Content-Type: application/json`이어야 합니다.
* 한도: 요청 하나에 `actions` 200개·본문 64KB, 동작 하나에 `sleep` 10초·`text` 2,000자·`scroll` ±100틱·`duration` 5초·`hotkey` 키 8개까지 받습니다. 버튼은 `L`/`R`/`M`만, 좌표·이동량은 ±32767까지입니다.
* 타이핑은 ASCII 글자와 줄바꿈·탭만 됩니다. 지원하지 않는 글자가 있으면 **한 글자도 입력하지 않고** `400`을 돌려줍니다.
* **비상 정지** `{"action": "release_all"}`은 진행 중인 동작을 끊고, 그 전에 줄 서 있던 요청도 취소(`409`)한 뒤 즉시 실행됩니다. 대시보드 사이드바와 트레이 메뉴의 **비상 정지**, `vm release-all`도 같습니다. 일시 중지·에이전트 종료도 진행 중인 동작을 먼저 끊습니다.
* 긴 동작(타이핑·플래싱) 중에도 `/status`·`/health`는 바로 답합니다(`"busy": true`와 마지막 상태).
* 에이전트는 포트를 독점으로 엽니다. 이미 실행 중이면 두 번째 실행은 안내 창을 띄우고 끝납니다.
* 서버 로그(대시보드 로그 탭)에는 타이핑한 글자를 남기지 않습니다.
* 펌웨어 매니페스트 주소는 요청으로 바꿀 수 없습니다(환경 변수 `VMOUSE_MANIFEST_URL`만 사용).

| 엔드포인트 / 액션 | 요청 예시 (`JSON`) | 설명 |
| :--- | :--- | :--- |
| `GET /health` | - | 아두이노 PING, 펌웨어 버전, 커서 좌표 |
| `GET /status` | - | USB 상태 자동 판별 (`ready` / `outdated` / `dfu_ready` / `stock_uno` / `port_busy`(장치는 보이지만 COM 포트를 다른 프로그램이 사용 중) / `paused` / `no_device`) |
| `GET /logs` | - | 서버 로그 (최근 250줄) |
| `POST /firmware/check` | `{}` | 원격 `latest.json`(최신 GitHub Release)과 현재 버전 비교 |
| `POST /firmware/update` | `{"use_local": true}` 또는 `{}` | SHA-256 검증 후 소프트웨어 `BOOT` → DFU 자동 갱신 |
| `POST /driver/install` | `{}` | DFU 장치(`03EB:2FEF`)에 WinUSB가 없을 때만 UAC로 `wdi-simple` 실행. 결과 `status`: `installed` / `already_installed` / `cancelled`(UAC 거부) / `failed` / `timeout` / `no_device` / `unavailable`. 펌웨어 업데이트 중이면 `409` |
| `POST /control/pause` · `/control/resume` · `/control/quit` | `{}` | 제어 일시 중지 / 재개 / 에이전트 종료 |
| `POST /action` (상대 이동) | `{"action": "move", "dx": 150, "dy": -80}` | 베지어 곡선 + 가감속 + 미세 손떨림 |
| `POST /action` (절대 이동) | `{"action": "move_to", "x": 800, "y": 500}` | DPI/가속 보정 포함 목표 픽셀 안착 |
| `POST /action` (클릭) | `{"action": "click", "button": "L"}` | 자연스러운 누름 유지 시간 (`L`/`R`/`M`) |
| `POST /action` (이동+클릭) | `{"action": "click_at", "x": 800, "y": 500}` | 곡선 이동 → 짧은 정지 → 클릭 |
| `POST /action` (드래그) | `{"action": "drag", "from_x": 300, "from_y": 300, "to_x": 600, "to_y": 400}` | 자연스러운 드래그 앤 드롭 |
| `POST /action` (스크롤) | `{"action": "scroll", "delta": -3}` | 자연스러운 간격으로 휠 스크롤 |
| `POST /action` (타이핑) | `{"action": "type", "text": "Hello HID!"}` | 사람 같은 랜덤 간격으로 물리 키보드 입력 (ASCII와 줄바꿈·탭, `"human": false`는 줄바꿈·탭도 불가) |
| `POST /action` (단축키) | `{"action": "hotkey", "keys": ["ctrl", "c"]}` | 모디파이어 순차 누름 → 역순 해제 |
| `POST /action` (연속 실행) | `{"actions": [{"action": "move_to", "x": 500, "y": 500}, {"action": "click"}]}` | 다중 액션 순차 실행 |
| `POST /action` (비상 정지) | `{"action": "release_all"}` | 진행·대기 중인 동작을 끊고 눌린 모든 버튼·키 즉시 해제 |

---

## 5. 원격 펌웨어 릴리즈 & 순정 복구

* **릴리즈**: `vX.Y.Z` 태그를 올리면 `.github/workflows/release.yml`이 테스트 → 펌웨어 `.hex` + `latest.json` → `wdi-simple` → `VirtualMouse-Agent.exe`를 빌드해 GitHub Release에 올립니다. exe에 들어 있는 `wdi-simple`(LGPL-3.0)의 소스 사본(`libwdi-<커밋>.tar.gz`)도 함께 올립니다.
* **원격 릴리즈 패키지 생성(로컬)**: `.\scripts\build_release.ps1` → `dist\releases\uno_16u2_mouse_<FW_VERSION>.hex` + `latest.json` 생성
  * 펌웨어 버전은 앱 릴리즈 태그와 따로 관리합니다. `.ino`의 `FW_VERSION`과 `host\device_status.py`의 `EXPECTED_FW_VERSION`이 같아야 빌드됩니다.
* **Guide 없이 단독 업데이터 CLI 실행**: `.\.venv\Scripts\python.exe host\updater.py --check` / `--update`
* **순정 Arduino Uno R3 원복**: DFU 모드 진입 후 `.\scripts\restore_stock_uno.ps1` 실행

---

## 6. 개발 규칙

CSS 구조, 버전·캐시 태그 갱신, 보안 규칙, 릴리즈 절차는 [`.agents/rules/project_architecture.md`](.agents/rules/project_architecture.md)를 따릅니다.
