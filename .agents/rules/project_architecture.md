# VirtualMouse 프로젝트 규칙

이 저장소에서 작업할 때 지키는 규칙입니다. 공개 저장소이므로 개인 정보·로컬 경로·키·토큰을 커밋하지 않습니다.

## 1. CSS 구조 (2026-11-24 결정: 단일 중앙 CSS)
- 스타일은 `web/styles.css` 한 파일에 둡니다. 컴포넌트별 CSS 파일이나 HTML `style` 속성을 새로 만들지 않습니다.
  - 예외: `web/index.html`의 SVG 보드 도식처럼 그림 자체의 속성.
- 색과 크기는 `:root`의 CSS 변수(`--bg`, `--primary` 등)를 씁니다.

## 2. 버전 관리 (이원화)
| 종류 | 위치 | 언제 바꾸나 |
| :--- | :--- | :--- |
| 앱 SemVer `SW_VERSION` (`vX.Y.Z`) | `web/app.js`, `web/index.html` 표시, 릴리즈 태그, `CHANGELOG.md` | **사용자 승인 후에만** |
| 캐시 버스팅 태그 `BUILD_TAG` (`YYYYMMDDvN`) | `web/app.js`, `web/index.html`의 `?v=`와 표시 | `web/` 파일을 바꾸면 배포 전에 **자동 갱신** |
| 펌웨어 버전 `FW_VERSION` | `firmware/.../uno_16u2_mouse.ino`, `host/device_status.py`의 `EXPECTED_FW_VERSION` | 펌웨어 코드가 바뀔 때만, 두 곳을 함께 |

- 캐시 태그는 `.\scripts\bump_build_tag.ps1`로 올립니다. 같은 날이면 N을 1 올리고, 날이 바뀌면 v1부터 시작합니다.
- SemVer까지 바꿀 때(승인 후): `.\scripts\bump_build_tag.ps1 -SwVersion vX.Y.Z`
- 펌웨어 버전은 앱 태그와 별개입니다. `scripts/build_release.ps1`은 두 펌웨어 버전 값이 다르면 빌드를 멈춥니다.
- 세 종류의 값이 서로 맞는지는 `tests/test_versions.py`가 확인합니다.
- `CHANGELOG.md`는 초안을 대화창에서 승인받은 뒤 기록합니다.

## 3. 로컬 API 보안 규칙 (`host/http_api.py`)
- 브라우저 허용 출처는 공식 대시보드(`https://virtual-mouse.iseohyun.com`)와 로컬 가이드(`127.0.0.1`·`localhost`의 같은 포트)뿐입니다. 목록을 넓히거나 `*`로 바꾸지 않습니다.
- Host 헤더는 루프백 이름만 허용합니다 (DNS rebinding 차단).
- 모든 API는 `Authorization: Bearer <토큰>`이 필요합니다. 예외는 정적 파일(대시보드 화면)과 CORS 프리플라이트(OPTIONS)뿐입니다.
- 토큰은 URL 쿼리나 로그에 넣지 않습니다. 브라우저에 넘길 때는 서버로 전송되지 않는 `#token=` 조각만 쓰고, 대시보드는 **로컬 가이드에서만** 이 조각을 받습니다.
- POST는 JSON만 받고, 요청 상한(`host/dispatcher.py`의 `MAX_*` 상수)과 본문 64KB 제한을 유지합니다.
- 펌웨어 매니페스트 주소는 요청으로 바꿀 수 없습니다 (`VMOUSE_MANIFEST_URL` 환경 변수만).
- 서버 로그에 타이핑 내용이나 사용자 이름이 들어간 경로를 남기지 않습니다 (`redact_action_for_log`).
- 새 엔드포인트는 같은 검사(`_guard`, `_authorized`) 뒤에 두고 `tests/test_http_api.py`에 테스트를 추가합니다.
- 장치로 보내는 값은 `host/mouse_client.py`에서 검사합니다: 버튼 `L/R/M`, 16비트 범위, 줄바꿈 없는 한 줄 명령. 펌웨어는 줄 단위로 명령을 읽으므로 이 검사를 빼지 않습니다.
- 정지(비상 정지·일시 중지·종료·플래싱)는 `_request_stop()`으로 시작합니다: 진행 중인 동작을 끊고 그 전에 줄 서 있던 요청을 취소합니다. 장치를 쓰는 긴 루프에는 `_check_abort()`를 넣습니다.
- 잠금(`_lock`)을 쥔 채 네트워크를 쓰지 않고, 외부 프로그램 실행에는 시간 제한을 둡니다.
- 서버는 포트를 독점으로 엽니다 (`ExclusiveThreadingHTTPServer`).
- WinUSB 드라이버 설치(`POST /driver/install`, `host/driver_install.py`)는 사용자가 버튼·명령으로 요청할 때만 합니다.
  에이전트가 시작·상태 조회 때 스스로 실행하지 않고, 권한 상승은 UAC(`runas`)로만 합니다. 펌웨어 업데이트와 같은 잠금(`_update_lock`)을 씁니다.
- `wdi-simple`에 넘기는 인수는 ASCII만 씁니다 (작업 폴더 기준 상대 경로). 실행 파일 경로와 작업 폴더는 유니코드 API(`ShellExecuteExW`)로만 넘깁니다.

### 공개 대시보드 신뢰 범위
- 공개 대시보드 출처는 사용자의 키보드를 조작할 수 있는 출처입니다. 이 출처를 바꿀 수 있는 사람(저장소 쓰기 권한, Pages·DNS 관리)은 곧 그 권한을 가집니다.
- 그래서 `web/index.html`의 CSP(스크립트·스타일은 자기 출처, 통신은 자기 출처와 로컬 에이전트만)를 유지하고, 인라인 스크립트·스타일·이벤트 속성과 외부 스크립트를 넣지 않습니다.
- `main` 배포는 단위 테스트를 통과해야 진행됩니다 (`deploy.yml`이 `test.yml`을 먼저 실행).
- 더 강하게 막으려면 공개 출처를 허용 목록에서 빼고 로컬 가이드만 쓰는 방법이 있습니다 (사용자 결정 사항).

## 4. 의존성 고정
- 외부 도구는 버전(또는 커밋)과 SHA-256으로 고정합니다. `scripts/setup.ps1`과 `.github/workflows/release.yml`의 값을 **함께** 바꿉니다.
- `wdi-simple` 빌드 입력(libwdi 소스, WDK 8 재배포 MSI, MinGW-w64 툴체인, 런타임 고지 파일)과 결과 exe의 SHA-256은
  `scripts/build_wdi.ps1`에만 둡니다 (`release.yml`은 그 스크립트를 그대로 부릅니다). 입력을 바꾸면 결과 해시도 새 값으로 바꿉니다.
- 사용자 전역 arduino-cli 설정을 바꾸지 않습니다. 보드 인덱스 주소는 명령마다 `--additional-urls`로 넘깁니다.
- PowerShell 스크립트의 외부 명령은 종료 코드를 확인합니다 (`setup.ps1`의 `Invoke-Native`).
- 시스템 프로그램(PowerShell, clip)은 이름이 아니라 시스템 경로로 실행합니다.
- GitHub Actions는 커밋 SHA로 고정하고, 줄 끝 주석에 태그 이름을 적습니다.
- Python 패키지는 `host/requirements*.txt`에 `==`로 고정합니다.

## 5. 테스트와 빌드
- 커밋 전:
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests` 통과
  - `node --check web/app.js` 통과
- 릴리즈·주요 마일스톤 전: `scripts/build_release.ps1`, `scripts/build_wdi.ps1`, `scripts/build_agent.ps1`이 오류 없이 끝나야 합니다.
- 드라이버 설치·UAC 창이 뜨는 시험은 자동 테스트에 넣지 않습니다 (`tests/vm_test_support.py`의 `FakeLauncher` 사용). 실기기 시험은 사용자 승인 뒤에만 합니다.
- 단위 테스트는 실제 장치·COM 포트·화면 커서에 접근하지 않습니다. `tests/vm_test_support.py`의 가짜 장치를 씁니다.
- 실기기 확인용 수동 스크립트(`host/test_mouse.py`, `host/test_api.py`)는 자동 테스트에 넣지 않습니다.

## 6. 릴리즈 절차
1. 테스트·빌드 통과
2. CHANGELOG 초안 승인 → 기록
3. SemVer 승인 → `bump_build_tag.ps1 -SwVersion vX.Y.Z`
4. 커밋 (사용자 승인 후, 변경 파일만 경로를 지정해 추가)
5. 푸시와 `vX.Y.Z` 태그 (사용자 요청 시)
6. Actions 결과(Pages 배포·Release)와 `releases/latest/download/latest.json` 확인
