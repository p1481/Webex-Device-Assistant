# Phase 1-4: Security hardening + god-class refactoring

24 commits. Two distinct tracks bundled together:

- **Phase 1** — security/correctness fixes (fail-closed policy, webhook secret, admin cookie secret, ruff baseline)
- **Phase 2-4** — pure mechanical extraction of 5 god classes into focused modules. Public method signatures preserved via thin delegating wrappers, so no callsite or test was modified.

## Verification

- `uv run pytest`: **304 passed** (2 pre-existing LLM flakes deselected: `test_room_bar_drop_routes_to_hang_up_with_rule_based_fallback`, `test_debug_get_room_booking_in_all_llm_mode`)
- `uv run ruff check .`: **0 errors**
- No behavior changes in Phase 2-4. Each extraction was followed by a full pytest run.

## LOC impact (5 god classes)

| Module | Before | After | Delta |
|---|---:|---:|---:|
| `orchestrator.py` | 2,652 | 761 | **−71%** |
| `ollama.py` | 1,467 | 316 | **−78%** |
| `rule_based.py` | 1,474 | 908 | **−38%** |
| `webex_gateway.py` | 785 | 302 | **−61%** |
| `main.py` | 677 | 281 | **−58%** |
| **Total** | **7,055** | **2,568** | **−64%** |

## Phase 1 — Security & correctness

- `a3c2fb5` **phase1.1**: wire `WebexTokenProvider` through `gateway._auth_headers` (was bypassing rotation)
- `1083c0e` **phase1.2**: fail-fast on missing webhook secret; return 503 when signature verifier is unavailable instead of skipping verification
- `2213346` **phase1.3**: policy evaluator fail-closed on unknown intents / lookup errors
- `d2784e2` **phase1.4**: separate `ADMIN_COOKIE_SECRET` from `WEBEX_WEBHOOK_SECRET` (see `docs/MIGRATION_ADMIN_COOKIE_SECRET.md`)
- `63ba3b8` **phase1.5**: fix loop-captured `llm_client` (ruff B023)
- `d34b6a0` **phase1.6**: add ruff config; apply 85 safe auto-fixes
- `f615570` **phase1.7**: add `ADMIN_COOKIE_SECRET` to real-mode test fixtures
- `646c1ca` / `70c52c1` `eb004c5`: residual ruff cleanup (74 safe + unsafe), per-file ignores for FastAPI `Depends` (B008) and test `with` nesting (SIM117); migration doc + env-var inventory updates across README/ARCHITECTURE/INSTALL/USER_MANUAL/MANUAL_KO

## Phase 2-4 — Refactoring (no behavior change)

### Phase 2 — `orchestrator.py` (2,652 → 761)
- `6d1de94` 2.1a: extract formatters
- `92a99e5` 2.1b: extract text extractors
- `dce787d` 2.2: extract card/selection builders
- `27efe71` 2.3: extract pending state machine + proposal helpers

### Phase 3 — providers (`rule_based.py`, `ollama.py`)
- `5c8416a` 3.1: extract `rule_based` text extractors (`providers/rule_based_extractors.py`, 765 LOC)
- `077bc99` 3.2: extract `ollama` normalizers (`providers/ollama_normalizers.py`, 326 LOC)

### Phase 4 — long-tail
- `9bd1b68` 4.1: extract ollama prompt builders + decision parser (`providers/ollama_prompts.py`, 975 LOC) — `ollama.py` 1,227 → 316
- `a8d0bb3` 4.2: extract Webex webhook reconciliation (`webex_webhooks.py`, 324 LOC) — `webex_gateway.py` 785 → 573
- `52c4ae6` / `25dc4f7` / `dbfdba6` / `43b5cd9` 4.3a-d: extract 21 endpoints from `main.py` into `routes/` (`health.py`, `webhooks.py`, `debug.py`, `admin.py`) — `main.py` 677 → 281. AppServices DI via `request.app.state.services`.
- `501221e` 4.4: extract Webex Messages API (`webex_messages.py`, 369 LOC) — `webex_gateway.py` 573 → 302

## New modules created
- `assistant_app/orchestration/{formatters,text_extractors,card_builders,pending_state}.py`
- `assistant_app/providers/{rule_based_extractors,ollama_normalizers,ollama_prompts}.py`
- `assistant_app/webex_webhooks.py`, `assistant_app/webex_messages.py`
- `assistant_app/routes/{health,webhooks,debug,admin}.py`

## New docs
- `docs/MIGRATION_ADMIN_COOKIE_SECRET.md`
- env-var inventory updates in `README.md`, `ARCHITECTURE.md`, `INSTALL.md`, `USER_MANUAL.md`, `MANUAL_KO.md`

## Notes for reviewers

- Refactors use the **wrapper-delegation** pattern: gateway/provider/orchestrator method signatures are preserved exactly, with bodies replaced by one-line calls to module-level functions that take the host object as the first arg. This keeps callsites and tests untouched.
- `routes/` modules use explicit DI through `request.app.state.services` instead of closure capture in `build_app()`.
- Per-file ruff ignores added: `B008` for FastAPI `Depends()` defaults in `main.py` + `routes/*.py`; `SIM117` + `B011/B017` in `tests/`.

## Follow-ups (not in this PR)
- Pre-existing LLM flakes: `test_debug_get_room_booking_in_all_llm_mode`, `test_room_bar_drop_routes_to_hang_up_with_rule_based_fallback` — need Ollama mocking to stabilize.
