# VirtualMouse (Auto Clicker) 마일스톤

각 작업은 순서대로 진행하며, 이전 작업의 실물/기능 확인이 완료된 후 다음 작업으로 넘어갑니다.

---

## 1번 작업: 펌웨어 v1.1.0 고도화 (`VER` + 키보드 통합 + `BOOT`)
- **목표**: `ATmega16U2` 펌웨어에 버전 조회, USB HID 키보드, 소프트웨어 DFU 진입 기능 통합
- **세부 항목**:
  - `VER` 명령 추가 (`VMOUSE 1.1.0` 응답)
  - USB HID 키보드(`BootKeyboard`) 통합 (문자열 타이핑, 단축키, 키 누르기/떼기) — RAM 512B 안전 범위 유지
  - `BOOT` 명령 추가 (점퍼 없이 소프트웨어 DFU 모드 진입 실물 검증)
- **완료 조건**: 컴파일 성공(Flash/RAM 여유 확인) + 실물 Uno R3 플래싱 + 마우스/키보드/`VER`/`BOOT` 정상 동작 확인
- **상태**: `[x] 완료`

---

## 2번 작업: 로컬 API 서버 고도화 (키보드 API + `/status` 자동 판별 + 웹 CORS/PNA)
- **목표**: 외부 프로그램 및 `virtual-mouse.iseohyun.com` 웹페이지가 바로 연동할 수 있는 완성형 로컬 API 서버 구축
- **세부 항목**:
  - `/action` JSON에 키보드 액션(`type`, `hotkey`, `key_press`, `key_release`) 및 사람 같은 랜덤 타이핑 딜레이 추가
  - `GET /status` 엔드포인트 추가 (USB 장치 자동 판별: `no_device` / `stock_uno` / `dfu_ready` / `outdated` / `ready`)
  - HTTPS 웹페이지 연동을 위한 `CORS` 및 Chrome `Access-Control-Allow-Private-Network: true` 헤더 / `OPTIONS` 지원
- **완료 조건**: `GET /status` 상태 판별 및 마우스/키보드 JSON API 통합 테스트 통과
- **상태**: `[x] 완료`

---

## 3번 작업: 원격 펌웨어 자동 업데이터 (Guide 없이 단독 갱신)
- **목표**: Guide 웹페이지가 없어도 원격 릴리즈 서버에서 최신 펌웨어를 자동 확인·다운로드·갱신
- **세부 항목**:
  - 원격 릴리즈 매니페스트(`latest.json`) 스펙 정의 및 샘플 생성
  - `host/updater.py` 구현 (원격 버전 비교 → `.hex` 다운로드 → SHA-256 무결성 검증 → DFU 자동 플래싱)
  - 로컬 서버 `POST /firmware/check`, `POST /firmware/update` API 연동
- **완료 조건**: 로컬 목업 릴리즈 서버 기준으로 자동 버전 감지 → 다운로드 → 해시 검증 → 갱신 흐름 확인
- **상태**: `[x] 완료`

---

## 4번 작업: All-in-One 웹 가이드 & 라이브 클릭 테스트 페이지 (`web/`)
- **목표**: `virtual-mouse.iseohyun.com`에 바로 배포 가능한 1~4단계 가이드 및 랜덤 버튼 자동 클릭 테스트 UI 구축
- **세부 항목**:
  - 로컬 서버(`/status`) 실시간 폴링 → 최신 펌웨어일 경우 1·2단계 자동 스킵
  - 1~2단계: 점퍼 2개 접촉 안내 도식 + DFU/플래싱 진행 상태 표시
  - 4단계: 화면의 랜덤 위치 버튼을 아두이노 마우스가 사람처럼 따라가며 클릭하는 라이브 데모
- **완료 조건**: 로컬에서 웹페이지 오픈 시 1~4단계 분기 및 실제 물리 마우스 자동 클릭 데모 성공
- **상태**: `[x] 완료`

---

## 5번 작업: 단일 실행 파일 패키징 (`VirtualMouse-Agent.exe`)
- **목표**: Python/도구 설치 없이 새 PC에서 실행 파일 1개로 드라이버·플래싱·로컬 서버를 모두 제공
- **세부 항목**:
  - PyInstaller 빌드 스크립트 작성 (`dfu-programmer`, 펌웨어 `.hex`, 로컬 서버 통합) — 완료
  - 트레이/콘솔 실행 모드 정리 — 완료
  - `wdi-simple` 번들과 UAC 관리자 권한 자동 승격 — **미완료, 7번 작업으로 이동**
- **완료 조건**: 빌드된 단일 `.exe` 실행 시 로컬 API 서버 정상 기동 및 동작 확인
- **상태**: `[x] 완료` (WinUSB 드라이버 자동 설치 제외)

---

## 6번 작업: 최종 문서화, 코드 정리 및 Git 저장소 초기화
- **목표**: 프로젝트 전체 의존성·사전 준비 문서 최종 검수 및 Git 버전 관리 시작
- **세부 항목**:
  - `README.md`, `scripts/setup.ps1`, `.gitignore` 최종 동기화
  - 사용자 승인 후 `git init` 및 초기 커밋 수행
- **완료 조건**: 빌드/테스트 에러 0 + 깔끔한 Git 초기 커밋 완료
- **상태**: `[x] 완료`

---

## 7번 작업: WinUSB 드라이버 자동 설치 (`wdi-simple` + UAC)
- **목표**: Zadig 없이 에이전트가 DFU 장치(`03EB:2FEF`)에 WinUSB 드라이버를 설치
- **세부 항목**:
  - libwdi `wdi-simple` v1.5.1을 고정 소스에서 재현 가능하게 빌드 (`scripts/build_wdi.ps1`) — 완료
    - WDK 전체 대신 WDK 8 재배포 MSI에서 WinUSB 코인스톨러 2개만 꺼냄 (관리자 권한·설치 없이 읽기 전용)
    - MinGW-w64(WinLibs GCC 16.2.0) 툴체인 고정, 결과 exe SHA-256까지 고정 (다른 폴더에서 빌드해도 같은 값 확인)
  - exe 번들(`build_agent.ps1`), 릴리즈 빌드 단계와 LGPL 대응 소스 자산(`release.yml`) — 완료
  - `host/driver_install.py`: DFU 장치가 있고 WinUSB가 없을 때만, 사용자가 요청할 때만 UAC로 실행.
    설치·이미 설치·UAC 거부·실패·시간 초과 구분, UAC 응답 120초·설치 180초 제한 — 완료
  - `POST /driver/install`(출처·토큰 검사 뒤, 펌웨어 업데이트와 같은 잠금), `vm driver-install`, 대시보드 버튼 — 완료
  - 라이선스 고지(libwdi LGPL-3.0, Microsoft WDF 재배포 조건, MinGW-w64 런타임) — 완료
  - 코드 서명·백신 오탐 대응 — **결정 필요** (서명 없는 exe가 UAC 창에 "알 수 없는 게시자"로 보임)
  - 시험 중 발견: `dfu-programmer launch`(워치독 리셋) 뒤 보드가 USB에 다시 나타나지 않음.
    펌웨어가 시작할 때 워치독을 끄지 않아 재시작이 반복되는 것으로 보이며, USB를 뺐다 꽂으면 복구됨.
    펌웨어 업데이트(`host/updater.py`)도 마지막에 같은 명령을 씀 — **별도 작업 필요**
- **완료 조건**: 실제 DFU 장치에서 드라이버 설치 → `dfu_driver_ok` 확인 → 플래싱 성공
- **상태**: `[ ] 플래싱 확인 대기` (2026-11-24 실기기 확인: 대시보드 버튼 → UAC 승인 → WinUSB 설치 `installed`,
  `dfu_driver_ok: true`, `dfu-programmer get bootloader-version` 성공. 플래싱은 아직 안 함. Zadig 수동 안내는 대안으로 유지)

---

## 8번 작업: 보안 강화 (코드 전수 검사 후속)
- **목표**: 다른 웹사이트·다른 사용자가 로컬 에이전트를 조작하지 못하게 하고, 배포 공급망을 고정
- **세부 항목**:
  - Origin·Host 검사, JSON 전용 POST, 요청 상한, 비상 정지 즉시 실행 (v1.1.3)
  - API Bearer 토큰 인증, 트레이 토큰 복사, 대시보드 토큰 입력, 로그에서 입력 내용 가리기
  - 외부 도구·액션·Python 패키지 버전과 SHA-256 고정, 단위 테스트와 CI
  - 재검사 후속: 비상 정지가 대기 요청까지 취소, 일시 중지·종료가 진행 중 동작을 끊음, 장치 명령 값 검사,
    타이핑 전체 사전 검사, 재연결, 포트 독점·포트 점유 안내, USB 조회 캐시, 잠금 범위·시간 제한,
    키보드 시나리오 포커스 확인, CLI 시간 초과 안내, setup 실패 감지, CSP·배포 전 테스트
- **완료 조건**: `python -m unittest discover -s tests` 통과 + 공개 대시보드·로컬 가이드 실동작 확인
- **상태**: `[ ] 커밋·릴리즈 대기` (v1.2.0 예정, Origin·Host 검사 등 일부는 v1.1.3으로 배포됨)
