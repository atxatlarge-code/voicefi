---
name: local-uat
description: On-device User Acceptance Testing (UAT), boundary fuzzing, and adversarial chaos engineering. Stresses systems with malicious payloads, resource starvation, concurrency dogpiling, and broken responses to ensure resilience before release.
---

# 💥 Local-UAT: On-Device User Acceptance Testing & Adversarial Chaos

The **`local-uat`** skill represents a distinct, dedicated engineering phase focused on **trying to break things**. While `local-qa` verifies that code compiles and unit tests pass, `local-uat` actively attacks the system with boundary condition fuzzing, resource starvation, concurrency contention, and simulated user chaos.

---

## 🎯 The Distinction: QA vs. UAT

| Attribute | `local-qa` (Verification) | `local-uat` (Break-It Validation) |
| :--- | :--- | :--- |
| **Mindset** | "Does the code satisfy specifications and pass tests?" | "How can I actively crash or corrupt this system?" |
| **Inputs** | Standard unit test mocks, clean syntaxes, known schemas | Emoji bombs, SQL injections, binary garbage, negative numbers |
| **Environment** | Clean, isolated single-threaded test runners | Concurrency dogpiles (8+ workers vs 1 job), starved RAM, thermal heat |
| **Failure Mode** | Assertion failures, lint errors, missing typing | Deadlocks, memory leaks, unhandled exceptions, double-claims |
| **Target Metric** | Line coverage %, green test passing status | 100% Chaos Survival Rate, zero deadlocks, graceful degradation |

---

## 🔬 Core UAT Battlegrounds

```
┌────────────────────────────────────────────────────────┐
│            Local-UAT Adversarial Test Matrix           │
└───────────────────────────────────┬────────────────────┘
                                    │
    ┌───────────────────────────────┼──────────────────────────────┐
    ▼                               ▼                              ▼
1. Input Fuzzing            2. Resource Starvation         3. Concurrency Dogpile
- SQL Injections in prompts - Mocked 500GB RAM ceiling     - 8+ workers on 1 job
- Non-UTF8 binary files     - Thermal SERIOUS triggers     - Zero double-claims
- Negative durations/limits - Abort without deadlocks      - Atomic SQLite WAL locks
```

1. **Hostile Input Fuzzing**:
   - Empty files, massive 100MB inputs, non-UTF8 binary payloads.
   - Injection strings (`'; DROP TABLE ...; --`).
   - Extreme out-of-bound arguments (`limit=-50`, `duration=999999`).
2. **Resource Starvation & Circuit Breakers**:
   - Simulating unified memory depletion using [`ThermalSupervisor`](file:///Users/jaketrigg/Projects/VoiceFi/src/voicefi/local/supervisor.py).
   - Verifying that workers pause, back off, or cleanly abort rather than causing kernel panics or runaway fan spin.
3. **Concurrency Dogpiles & Race Conditions**:
   - Multiple threads/workers furiously contending for a single resource (e.g., atomic queue jobs or speech turn locks).
   - Proving that zero race conditions or double-claims occur.
4. **Model Resilience & Broken JSON Recovery**:
   - Handling LLM hallucination, truncated responses, non-JSON markdown wraps, and sudden daemon timeouts gracefully.

---

## 🛠️ How to Trigger

### 1. Run the Full Adversarial UAT Suite
```bash
uv run python3 scripts/uat_break_it.py
```

### 2. Run Targeted Chaos Probes
```bash
# Run with custom worker contention count
uv run python3 -c "
from scripts.uat_break_it import UATTester
tester = UATTester()
tester.test_concurrency_dogpile()
tester.test_thermal_starvation()
tester.print_summary()
"
```

### 3. Verification Scorecard Format
Every UAT run generates a clean survival scorecard:
```text
=================================================================
💥 VoiceFi UAT & Chaos 'Break-It' Scorecard
=================================================================
✅ PASSED   | Scout Hostile Inputs                (10.939s)
            └─ Handled non-existent, empty, and corrupted binary files cleanly.
✅ PASSED   | Thermal & RAM Starvation            (0.399s)
            └─ Correctly engaged safety circuit breaker and aborted cleanly.
✅ PASSED   | Content Factory Input Fuzzing       (10.385s)
            └─ Defended against SQL injection strings and emoji payloads.
✅ PASSED   | Concurrency Dogpile (8 vs 1)        (0.015s)
            └─ Atomic SQLite claiming held: exactly 1 worker won, 0 errors.
✅ PASSED   | Malformed JSON Recovery             (0.000s)
            └─ Handled non-JSON text and truncated schemas gracefully.
-----------------------------------------------------------------
Overall Result: 5/5 chaos tests survived (100% resilient)
=================================================================
```
