# Plan — SWE Light Analytics Engine Audit & Refinement

## Goal
Audit and refine the VoiceFi analytics and developer statistics system (`vifi stats` in `src/voicefi/analytics/`) to eliminate inflated time-saved and turn counts, accurately de-duplicate tool invocations and speech events, and implement a rigorous Human-AI Interaction (HAI) framework tied to distinct developer use cases.

## Execution Sequence
1. **Implementer**: Dispatch `teamwork_preview_implementer` to analyze `src/voicefi/analytics/` (`store.py`, `queries.py`, `telemetry.py`, `terminal.py`), fix double-counting, implement HAI modalities & empirical models, update CLI dashboard and JSON/CSV exporters, and add comprehensive unit tests in `tests/test_analytics_engine.py`.
2. **Reviewer Round 1**: Dispatch `teamwork_preview_reviewer` to review the diff, run tests, adversarial-test edge cases, and report open issues.
3. **Reviewer Round 2**: Dispatch `teamwork_preview_reviewer` with updated open-issues ledger to verify fixes and edge cases.
4. **Reviewer Round 3**: Dispatch `teamwork_preview_reviewer` to ensure zero remaining issues and full requirement conformance.
5. **Independent Victory Audit**: Dispatch `teamwork_preview_victory_auditor` for blocking confirmation.
6. **Handoff & Reporting**: Write `handoff.md` and message caller / Sentinel with summary.
