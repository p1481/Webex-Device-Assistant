# Webex Device Assistant App Manual

This file is now a pointer page so the top-level documentation stays accurate as the code changes.

## Read these manuals

- [ARCHITECTURE.md](ARCHITECTURE.md), current module boundaries, request flow, execution modes, Webex webhook flow, cloud xAPI transport, persistence boundary, and limitations
- [INSTALL.md](INSTALL.md), environment setup, local run, mock mode, real Webex setup, real device setup, and validation commands
- [USER_MANUAL.md](USER_MANUAL.md), current user-facing behavior, approval flow, admin APIs, admin page, and supported action areas including matrix control
- [MANUAL_KO.md](MANUAL_KO.md), 한국어 아키텍처/사용 가이드, 현재 구현 범위, 흐름, 관리자 표면, mock-vs-real 동작 요약

## Current scope in one page

Today this repository contains a FastAPI-based Webex Device Assistant with:

- LLM-first orchestration in both separated and all-LLM execution modes
- local debug routes plus real Webex webhook ingress
- approval-card generation and real attachment-action handling
- admin JSON APIs and a thin `/admin-page` browser UI
- mock-first defaults with optional real Webex messaging and Webex cloud xAPI device execution

## Accuracy notes

- The real device path is Webex cloud xAPI and device configuration APIs, not local RoomOS transport.
- Approved device-action requests do execute after real Webex card clicks when the webhook is configured.
- Admin login approval currently updates in-memory session state only. `/admin-page` itself is not gated, but protected `/admin/*` data access requires the browser admin session cookie.
- For the exact current action set and limits, use the manuals above instead of older prose or product-spec intent docs.
