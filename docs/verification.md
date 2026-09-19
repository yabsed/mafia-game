# Verification notes — 2026-09-19

## Executed locally

- Python 3.13.5: `python -m unittest discover -s tests -v` — 38 tests passed, including 300 complete deterministic demo simulations (100 seeds each for 5, 6, 7 players).
- Python bytecode compilation: `python -m compileall -q mafia run.py` — passed.
- Node 22.16.0: `node --check web/app.js` — passed.
- Chromium / Playwright: desktop (1440 px) and mobile (390 px), no horizontal overflow and no JavaScript page errors. Exercised new demo game, auto-play, pause, speed, resident selection, suspicion marker, director-mode reveal/hide, secret diary tab and JSON download. Inspected both screenshots.
- HTTP tests use the real loopback server, not a stub: Host/Origin/session-token validation, static allowlist, no API-key disclosure, create/step/load/export, concurrent-step rejection and pause during an in-flight action.

The execution sandbox blocks Chromium's direct loopback navigation (`ERR_BLOCKED_BY_ADMINISTRATOR`). For the browser check, the actual HTML/CSS/JS was loaded into an in-memory page and a Playwright binding relayed its API calls through Python to the real local HTTP server. Browser transport, native origin enforcement and CSP were therefore tested by HTTP/header tests and code review rather than a full direct-navigation browser end-to-end run in this environment. `tools/browser_smoke.py` normally uses direct navigation; `--bridge` reproduces the restricted-environment renderer check without changing browser policy.

## Not verified

No live API credentials were available. DeepSeek responses and error cases were simulated in tests; no paid request was made. Actual provider connectivity, latency, generation quality, tokenizer counts and billing have not been measured.

The code is intended for Fedora/Linux with Python 3.11+, but this container is not the user's Fedora 44 laptop. Python 3.11/3.14 and the GitHub Actions matrix were configured, not run locally. Firefox was not available for a separate browser test.

## Important limits

Budget amounts are conservative local estimates at configured peak rates, not provider-enforced payment caps. Unknown billing outcomes retain their reservation. No automatic paid retries. Do not remove or change the ledger directory to reset spending.

Agent prompts use a strict private-view allowlist. Spectator director mode is intentionally omniscient; it is not a security boundary against the local user. Fictional diaries are not provider reasoning traces.
