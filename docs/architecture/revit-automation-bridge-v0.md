# Revit Automation Bridge v0 - Architecture Proposal

Status: Proposal (awaiting recommendation approval before implementation)
Scope: PR #19 - establish the communication boundary between **Axiom outside Revit**
and **Axiom inside Revit** for autonomous validation.

## 1. The actual problem

The strategic problem is **not** launching Revit, opening UI, or driving the screen.
It is:

```
How does Axiom outside Revit communicate with Axiom inside a running Revit?
```

Target flow (no human interaction after workflow dispatch):

```
GitHub Actions -> Validation Loop -> Automation Bridge -> Running Revit Add-in
    -> Capability Execution -> Evidence -> Pass / Fail
```

v0 success definition: a running Revit instance receives an execution request from an
external process and executes **one** Axiom capability, producing evidence. The specific
capability does not matter; the bridge does.

## 2. Current state (what already exists)

This is critical context, because most of the bridge is already built (PR #2) and the
right move is to *reuse*, not duplicate.

| Component | Location | Role |
| --- | --- | --- |
| `AxiomPipeServer` | `src/axiom_revit/Axiom.Core/Bridge/AxiomPipeServer.cs` | Named-pipe server **running inside Revit**. Length-prefixed JSON framing; `execute_tool` JSON-RPC; marshals every Revit API call onto the main thread via `ExternalEvent`; wraps non-simulate execution in a `Transaction` (rollback on FAILED). |
| Startup wiring | `src/axiom_revit/Axiom.RevitAddin/App.cs:78-88` | `OnStartup` builds a `ToolRegistry` (Grid, Level, InventoryModel, SetParameterValue) and calls `_pipeServer.Start()`. `OnShutdown` stops it. The server is **already live whenever the add-in is loaded**. |
| `PipeClient` | `src/axiom_core/pipe_client.py` | Python client. `is_available()` probes `\\.\pipe\axiom`; `execute_tool(...)` sends the JSON-RPC request and parses the structured `ToolResult`. Mock fallback off-Windows / in simulate. |
| Wire contract | `contracts/pipe_message_schema.json` | JSON-RPC 2.0 request / success / error schema (`execute_tool`, `tool_name`, `args_json`, `simulate`, `transaction_name`; result `status/created_ids/warnings/errors/duration_ms/output_data`). |
| `PromptDispatcher` | `src/axiom_revit/Axiom.Core/Bridge/PromptDispatcher.cs` | In-Revit prompt -> capability routing (used by the interactive button). |
| Validation Loop | `src/axiom_core/validation_loop.py` | Phased runner (context/git/tests/deploy/evidence-scan/classify) writing `artifacts/validation_runs/<run_id>/`. Bounded retry (`--max-attempts`). |

**Gap analysis.** The transport boundary already works for the interactive path. What is
missing for *autonomous* validation is narrow:

1. A **non-interactive external entry point** the Validation Loop / GitHub Actions can call
   to send exactly one capability request over the existing bridge (no Revit UI dialog,
   no human click).
2. **Durable request/response evidence** (request sent, request received, capability
   executed, result returned, pass/fail) captured as artifacts, consistent with the
   existing evidence model.

So v0 is mostly *connecting existing pieces*, plus a thin, well-tested external driver.

## 3. Options

### Option A - Named Pipe Bridge

```
Validation Loop -> \\.\pipe\axiom -> AxiomPipeServer (in Revit) -> Capability
```

- **Pros:** Already implemented and wired (PR #2); synchronous request/response with a
  correlation `id`; structured `ToolResult`; localhost-only by OS design (a named pipe is
  not network-exposed); no new dependency; transaction + ExternalEvent semantics already
  correct; off-Windows mock path already exists for CI Python tests.
- **Cons:** Windows-only (acceptable - Revit is Windows-only; the runner is Axiom-01);
  single-instance server (`maxNumberOfServerInstances = 1`) so one in-flight request at a
  time (fine for v0); requires Revit to be running with the add-in loaded (true for every
  option that executes inside Revit).
- **Complexity:** Low. The transport exists; we add an external driver + evidence capture.
- **Reliability:** High. In-process to the OS, deterministic framing, explicit timeouts,
  no polling races.
- **Revit API compatibility:** Excellent. The server already marshals onto the Revit main
  thread via `ExternalEvent` and uses `Transaction` correctly.
- **Suitability for autonomous validation:** High. Synchronous result + correlation id maps
  directly onto "request sent / received / executed / result / pass-fail" evidence.

### Option B - Job Queue (file-based)

```
external writes validation_jobs/job_001.json -> Revit polls dir -> executes -> writes result_001.json
```

- **Pros:** Maximally durable (request and result are files = built-in evidence); fully
  decoupled (Revit can pick the job up whenever it is ready); trivially captured by CI
  artifact upload; no Windows-specific transport.
- **Cons:** Requires a **new** in-Revit file watcher/poller on a timer/`Idling` loop (new
  surface area, new failure modes: partial writes, lock contention, stale jobs, poll
  latency); asynchronous, so the external side must poll for completion (race conditions,
  timeout bookkeeping); duplicates routing/dispatch that the pipe already does; weaker
  back-pressure / liveness signal (you cannot tell "Revit not running" from "Revit slow").
- **Complexity:** Medium-High (new watcher, atomic write protocol, lifecycle management).
- **Reliability:** Medium. Robust to crashes, but polling and partial-file hazards add
  edge cases that must be engineered and tested.
- **Revit API compatibility:** Good (execution still goes through ExternalEvent), but the
  poller itself is extra in-Revit machinery.
- **Suitability for autonomous validation:** Good for *durability*, weaker for *determinism*
  and *liveness*. Best as an evidence/queue layer **on top of** a synchronous transport, not
  as the transport itself in v0.

### Option C - Local HTTP Endpoint

```
Validation Loop -> http://localhost:<port> -> HttpListener in Revit add-in -> Capability
```

- **Pros:** Familiar request/response; language-agnostic; easy to curl for debugging.
- **Cons:** Opens a **listening socket** inside Revit - a real security surface (port,
  binding, auth) that a named pipe avoids entirely; `HttpListener`/Kestrel adds dependency
  and ACL/urlacl friction on Windows; port collisions; firewall prompts; more to harden to
  avoid "public runner exposure". No advantage over the pipe for localhost-only IPC.
- **Complexity:** Medium-High (hosting + security hardening).
- **Reliability:** Medium. More moving parts than a pipe for the same synchronous semantics.
- **Revit API compatibility:** Same as A/B (still needs ExternalEvent marshalling).
- **Suitability for autonomous validation:** Adequate but strictly worse than A on security
  and simplicity for a same-machine bridge.

### Option D - Revit ExternalEvent-driven bridge

- **What it is:** Use Revit `ExternalEvent` as the **execution boundary** - the mechanism
  that hops work onto the Revit main thread.
- **Key point:** This is **not a transport** and is not mutually exclusive with A/B/C. It is
  *already* how `AxiomPipeServer` executes every request (`AxiomPipeServer.cs:54-55,
  170-228`). Whatever transport delivers the request, it must hand off to an ExternalEvent
  to touch the Revit API legally.
- **Pros:** Mandatory and correct for Revit API access; already implemented.
- **Cons:** By itself it answers "how do we run on the Revit thread", not "how does an
  external process reach Revit". Needs a transport (A/B/C) in front of it.
- **Complexity:** Already paid for.
- **Reliability / API compatibility:** Excellent - it is the sanctioned pattern.
- **Suitability:** Necessary substrate for all options; not a standalone choice.

## 4. Comparison matrix

| Criterion | A: Named Pipe | B: Job Queue | C: Local HTTP | D: ExternalEvent |
| --- | --- | --- | --- | --- |
| Already built | Yes (PR #2) | No | No | Yes (inside A) |
| New in-Revit surface | None | Watcher/poller | HTTP host | None |
| Transport security | Localhost by OS design | File ACLs | Open socket (hardening) | n/a |
| Determinism / liveness | High (sync + id) | Medium (poll) | High | n/a |
| Crash durability | Add via evidence | Built-in | Add via evidence | n/a |
| Revit-thread correctness | Built-in | Needs it | Needs it | Is the mechanism |
| Complexity to v0 | Low | Med-High | Med-High | Paid |
| Standalone transport? | Yes | Yes | Yes | No |

## 5. Recommendation

**Adopt Option A (Named Pipe) as the transport, executing through Option D (ExternalEvent)
inside Revit - i.e. reuse the existing PR #2 bridge - and add a thin external driver plus
durable evidence capture.** Do **not** build B or C in v0.

Rationale:
- The pipe bridge already exists, is wired into `App.OnStartup`, already marshals onto the
  Revit main thread, and already returns a structured, correlated result. It is the lowest-
  risk, most deterministic path to the v0 success definition.
- A named pipe is localhost-only by construction, satisfying "no public runner exposure"
  with zero extra hardening (unlike Option C's listening socket).
- Option B's real value is *durability/evidence*, which we get by recording the request and
  the pipe response as artifacts - without taking on a new in-Revit poller and async race
  handling. B remains a sensible **future** evolution for multi-job batching; it is out of
  scope for v0.
- Option D is not a competing choice; it is the required execution substrate and is already
  in place.

### Proposed v0 implementation (for approval - not yet built)

Minimal, single capability, single execution path:

1. **External driver (Python):** a non-interactive entry point - e.g.
   `axiom bridge-execute --capability InventoryModel --args-json '{...}' --run-id <id>
   [--simulate]` - that calls the existing `PipeClient.execute_tool(...)` (no UI, no human),
   with an explicit timeout and a clear non-zero exit on FAILED/unavailable so CI propagates
   status. Reuses `PipeClient` verbatim; no new transport.
2. **Evidence (reuse existing model):** write a bridge run under
   `artifacts/validation_runs/<run_id>/bridge/`:
   - `bridge_request.json` (what was sent: capability, args, id, timestamp),
   - `bridge_response.json` (raw `ToolResult`: status/ids/warnings/errors/duration),
   - `bridge_result_summary.md` (request sent / received / executed / result / pass-fail),
   - `pass_fail.json` (classification reusing the validation-loop taxonomy, plus a new
     `bridge_unavailable` reason when Revit/add-in is not running).
3. **Validation scenario:** one controlled scenario (e.g.
   `bridge_inventory_summary` or `bridge_set_comments_preview`) wired so the existing
   `windows-revit-validation.yml` (`workflow_dispatch`, Axiom-01) can drive it after the
   add-in is loaded. v0 may default to a **read-only / preview** capability so the
   acceptance test needs no model mutation.
4. **Tests (off-Windows, deterministic):** unit-test the driver and evidence/classifier
   against a **mock** `PipeClient` (success, FAILED, pipe-unavailable). No live Revit needed
   in CI; the live proof is the manual `workflow_dispatch` on Axiom-01.

### Acceptance test (v0)

A GitHub-dispatched workflow on Axiom-01, with Revit running and the add-in loaded, runs the
external driver, which sends one `execute_tool` over the pipe; the in-Revit server executes
one capability via ExternalEvent and returns a result; the driver writes evidence proving:
request sent -> request received -> capability executed -> evidence produced -> pass/fail
classified, with no human interaction after dispatch.

## 6. Explicit non-goals (v0)

No discovery loop, no autonomous bug-fixing, no code generation, no auto-PR, no multi-
capability orchestration, no multi-product adapters, no Autodesk Assistant / MCP, and no UI
automation of any kind (no SendKeys, AutoHotkey, image/OCR, coordinate clicking, screen
scraping). The bridge communicates only through software interfaces.

## 7. Open questions for approval

1. Confirm **Option A** (named pipe, reuse PR #2) as the v0 transport.
2. Preferred v0 capability for the acceptance scenario: **read-only `InventoryModel` summary**
   (no model mutation) vs. **`SetParameterValue` preview** (read-only preview path)?
3. Should the external driver live as a new `axiom` CLI subcommand (recommended) or as a
   standalone script under `scripts/local/`?

## 8. Implementation status (v0 - delivered)

Decisions confirmed: **Option A** (named pipe, reuse PR #2) as the transport; **read-only
`InventoryModel` summary** as the acceptance capability; the external driver ships as a new
`axiom` CLI subcommand.

Delivered in this PR:

- **Driver:** `src/axiom_core/automation_bridge.py` - `execute_capability_via_bridge(...)`
  sends one `execute_tool` request through the existing `PipeClient` (injectable for tests),
  with pure, I/O-free `classify_outcome(...)` logic separated from evidence writing.
- **CLI:** `axiom bridge-execute --capability InventoryModel [--simulate] [--args-json ...]
  [--run-id ...] [--output-dir ...]`. Non-interactive; exits `0` on `pass`, `1` on
  fail/unavailable/error, `2` on bad `--args-json`. InventoryModel defaults to safe summary
  mode (`{"SummaryOnly": true, "ScanMode": "summary"}`) - no full scan, no model mutation.
- **Evidence:** written under `artifacts/validation_runs/<run_id>/bridge/`:
  - `bridge_request.json` - id, method, capability, args, simulate, transaction_name, sent_at
  - `bridge_response.json` - raw `ToolResult` (status/ids/warnings/errors/duration/output_data)
  - `bridge_result_summary.md` - ASCII, PowerShell-safe; the five checkpoints + result
  - `pass_fail.json` - classification, reason, passed, simulate, checkpoints, classified_at
- **Classification taxonomy:** `pass`, `capability_failed`, `bridge_unavailable`
  (Revit/add-in not running), `bridge_error` (transport/driver exception). Evidence is written
  for every outcome, including unavailable/error.
- **Checkpoints (acceptance proof):** request_sent -> request_received -> capability_executed
  -> result_returned -> evidence_produced.
- **Workflow wiring:** `windows-revit-validation.yml` gains opt-in `workflow_dispatch` inputs
  `run_bridge`, `bridge_simulate`, `bridge_capability`, adding a bridge step that runs
  `axiom bridge-execute` after the add-in is loaded (live) or via the mock path (simulate).
- **Tests:** `tests/test_automation_bridge.py` - classifier + driver + CLI against a mock
  `PipeClient` (success / FAILED / pipe-unavailable / transport-exception / simulate). No live
  Revit required; the live proof is the manual `workflow_dispatch` on Axiom-01.

Live acceptance (Axiom-01, no human interaction after dispatch): start Revit with the Axiom
add-in loaded, then dispatch **Windows Revit Validation (Axiom-01)** with `run_bridge=true`
(and `bridge_simulate=false`). The bridge sends one `InventoryModel` summary request over the
pipe; the in-Revit server executes it via ExternalEvent and returns a result; evidence is
written and uploaded as a workflow artifact.

**Status: VALIDATED.** The full chain ran green on Axiom-01 against Revit 2027 with no human
interaction after dispatch: GitHub Actions -> Axiom-01 self-hosted runner -> validation
workflow -> Automation Bridge -> named pipe -> running Revit 2027 -> InventoryModel capability
-> evidence collection -> artifact upload. (A first live attempt surfaced a PowerShell
empty-argument bug in the workflow step - `$simArg=''` was passed as an extra positional arg
when `bridge_simulate=false`; fixed by building the CLI args as a PowerShell array and
appending `--simulate` only when requested.)
