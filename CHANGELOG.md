# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/ko/).

## [1.1.0] - 2026-11-24
### Added
- Arduino Uno R3 (`ATmega16U2`) MultiReport USB HID 마우스 + 키보드 통합 펌웨어 (`VER`, 소프트웨어 `BOOT` DFU 진입 지원)
- 사람 움직임 엔진 (3차 베지어 곡선, Minimum-Jerk 가감속, 미세 손떨림, 오버슈트, DPI 실시간 좌표 보정, 랜덤 타이핑 간격)
- 로컬 HTTP JSON API 서버 (`127.0.0.1:18080`, `POST /action`, `GET /status`, `CORS` + Chrome `Private Network Access`)
- 원격 펌웨어 자동 업데이터 (`latest.json` 버전 비교, SHA-256 검증, `BOOT` → DFU 자동 갱신)
- 웹 가이드 및 라이브 자동 클릭/키보드 테스트 UI (`https://virtual-mouse.iseohyun.com`)
- 단일 실행 파일 패키징 (`VirtualMouse-Agent.exe`)
