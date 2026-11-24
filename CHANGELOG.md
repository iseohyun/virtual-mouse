# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/ko/).

## [1.2.1] - 2026-11-24
### Fixed
- 본문을 읽기 전에 거부한 요청(401·403·413·415)에서 클라이언트가 오류 응답 대신 연결 끊김을 받을 수 있던 문제
  (남은 본문을 최대 1MB까지 읽은 뒤 응답, 느린 연결은 10초 뒤 정리)
- 위 문제로 CI에서 간헐적으로 실패하던 HTTP 테스트 (재현 테스트 3개 추가)

## [1.2.0] - 2026-11-24
### Changed
- **호환성 주의**: 로컬 API의 모든 요청에 `Authorization: Bearer <토큰>`이 필요합니다. 기존 외부 스크립트는 헤더를 추가해야 합니다 (토큰: `%LOCALAPPDATA%\VirtualMouse\api-token`, 트레이 'API 토큰 복사', `vm token`)
- 에이전트 코드를 `server.py`·`http_api.py`·`dispatcher.py`·`auth.py`로 분리
- 외부 도구·GitHub Actions·Python 패키지 버전과 SHA-256 고정
- 에이전트가 없거나 토큰을 기다리는 동안 상태 조회 간격을 늘림
- 긴 동작(타이핑·플래싱) 중에도 `/status`·`/health`가 바로 응답 (`busy`)
- `setup.ps1`이 사용자 전역 arduino-cli 설정을 바꾸지 않음
### Added
- 대시보드 토큰 입력·저장·지우기, 트레이 '대시보드 보기'로 열면 토큰 자동 전달
- 대시보드 사이드바·트레이 메뉴의 비상 정지
- WinUSB 드라이버 설치 안내, COM 포트 사용 중(`port_busy`) 안내
- 하드웨어 없이 도는 단위 테스트 94개와 CI(Tests 워크플로, 배포·릴리즈 전 실행)
- 웹 캐시 태그 갱신 스크립트 `scripts/bump_build_tag.ps1`, 프로젝트 규칙 문서
### Security
- 비상 정지·일시 중지·종료가 진행 중인 동작과 그 전에 대기하던 요청까지 취소
- 장치 명령 값 검사 (버튼 `L/R/M`, 16비트 범위, 한 줄 명령) — `button`을 통한 펌웨어 명령 주입 차단
- 에이전트 포트 독점 사용 (중복 실행 차단)
- 대시보드 CSP, `main` 배포 전 테스트, Pages 쓰기 권한을 배포 작업으로 한정
- 서버 로그에서 타이핑 내용·사용자 이름이 들어간 경로 가리기
- PowerShell·clip을 시스템 경로로 실행, 릴리즈 워크플로 입력값 스크립트 주입 차단
- `#token=`은 로컬 가이드에서만 받음
### Fixed
- 지원하지 않는 글자가 섞이면 앞부분만 입력되던 문제 (입력 전에 전체 검사)
- ping 실패 뒤 다시 연결되지 않던 문제, 응답이 한 줄씩 밀리던 문제
- 장치가 없을 때 상태 조회마다 PowerShell이 실행되던 문제
- dfu-programmer·대시보드 요청·CLI에 시간 제한과 안내 추가
- 키보드 시나리오가 입력창 포커스를 확인하지 않던 문제
- `setup.ps1`이 설치 실패를 알아채지 못하던 문제
- 플래싱 도중 종료하면 플래싱이 끊길 수 있던 문제
- 대시보드 안내문 `innerHTML` 제거, 실패를 조용히 넘기던 버튼, 플래싱 중 버튼 중복 실행, 트레이 실패 시 서버 이중 실행

## [1.1.3] - 2026-11-24
### Security
- 로컬 API를 공식 대시보드·로컬 가이드 출처만 호출할 수 있게 제한 (Origin·Host 검사, JSON 외 POST 거부)
- 펌웨어 매니페스트 주소를 요청으로 바꿀 수 없게 고정
- raw 타이핑에서 줄바꿈 등 제어 문자 차단 (펌웨어 명령 주입 방지)
### Fixed
- 원격 매니페스트 주소를 GitHub Release latest.json으로 수정
- 펌웨어 버전을 앱 태그와 분리해 업데이트 무한 반복 방지
- sleep·actions·text·scroll·duration·본문 크기 상한, release_all 즉시 중단

## [1.1.2] - 2026-11-24
### Added
- gh 스타일 명령줄 도구 `vm` (`host/cli.py`, `scripts/vm.cmd`)
- 대시보드 사이드바에 SW 버전·빌드 태그 표시
### Changed
- 사이드바를 화면 높이에 고정하고 본문만 스크롤

## [1.1.1] - 2026-11-24
### Added
- 콘솔 창 없는 시스템 트레이 에이전트(VM 아이콘)와 4탭 사이드바 대시보드(설치·테스트·로그·안내)
- PWA 설치 지원 (manifest, 서비스 워커)
- 태그를 올리면 exe·펌웨어를 빌드해 올리는 릴리즈 워크플로
### Fixed
- 클릭 시점 화면 좌표 보정과 클릭 디버그 로그 (라이브 클릭 테스트 정확도)
- 하위 프로세스 콘솔 창 깜박임, Pages 2단계 배포 오류
- USB 상태 조회 캐시(10초), 종료 시 프로세스가 남지 않게 보장

## [1.1.0] - 2026-11-24
### Added
- Arduino Uno R3 (`ATmega16U2`) MultiReport USB HID 마우스 + 키보드 통합 펌웨어 (`VER`, 소프트웨어 `BOOT` DFU 진입 지원)
- 사람 움직임 엔진 (3차 베지어 곡선, Minimum-Jerk 가감속, 미세 손떨림, 오버슈트, DPI 실시간 좌표 보정, 랜덤 타이핑 간격)
- 로컬 HTTP JSON API 서버 (`127.0.0.1:18080`, `POST /action`, `GET /status`, `CORS` + Chrome `Private Network Access`)
- 원격 펌웨어 자동 업데이터 (`latest.json` 버전 비교, SHA-256 검증, `BOOT` → DFU 자동 갱신)
- 웹 가이드 및 라이브 자동 클릭/키보드 테스트 UI (`https://virtual-mouse.iseohyun.com`)
- 단일 실행 파일 패키징 (`VirtualMouse-Agent.exe`)
