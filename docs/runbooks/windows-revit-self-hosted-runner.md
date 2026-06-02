# Windows / Revit Self-Hosted Runner (Axiom-01) - Runbook

This runbook explains how to turn **Axiom-01** (the Windows machine with Revit
2027 installed and licensed) into a **controlled, manual** GitHub Actions
self-hosted runner for Axiom validation jobs.

This is the **foundation** (v0): manual trigger only, Python tests + ruff +
the Validation Loop `pre` phase, and an **optional add-in build** (no deploy,
no live Revit model mutation). It moves validation execution onto the real
Windows/Revit machine without Plamen manually pulling/building/checking every
time.

> Strategic context: PR #16 added the Axiom Validation Automation Loop v0. The
> next bottleneck is running that loop on the actual Windows/Revit machine
> through a controlled self-hosted runner. This runbook + the
> `windows-revit-validation.yml` workflow are that foundation. The
> discovery/bounded-retry/promotion-scoring machinery is a later target and is
> out of scope here.

---

## Security warnings (read first)

- **Keep this repository PRIVATE.** Self-hosted runners must never run code
  from untrusted pull requests. A self-hosted runner executes whatever the
  workflow says - a malicious fork PR could run arbitrary code on Axiom-01.
- **Do not enable this workflow for forks / untrusted contributors.** It is
  `workflow_dispatch`-only precisely so it never auto-runs on PRs.
- **Never print or commit secrets/tokens.** The runner registration token is
  one-time and obtained interactively from GitHub; it must not be stored in
  the repo. The provided `scripts/local/setup-github-runner-notes.ps1` only
  prints guidance and probes prerequisites - it contains no secrets.
- **No public exposure.** The runner makes an outbound connection to GitHub;
  it does not need any inbound ports. Do not expose it to the internet.

---

## What the workflow does

File: `.github/workflows/windows-revit-validation.yml`

- **Trigger:** `workflow_dispatch` only (manual).
- **Runner labels:** `self-hosted`, `windows`, `axiom-01`, `revit-2027`.
- **Inputs:**
  - `build_revit_addin` (boolean, default `false`) - run
    `scripts/deploy-revit-2027.ps1 -BuildOnly` (build, **no** copy to the
    Addins folder).
  - `revit_version` (string, default `2027`).
- **Steps:**
  1. Checkout the repo.
  2. Confirm runner machine/user/admin context.
  3. Confirm repo path + current branch/commit.
  4. Ensure Poetry is available.
  5. `poetry install`.
  6. `poetry run pytest tests/test_validation_loop.py tests/test_local_runner.py tests/test_set_parameter_value.py`.
  7. `poetry run ruff check .`.
  8. *(optional)* Build the Revit 2027 add-in via `-BuildOnly`.
  9. *(optional)* Print built DLL `LastWriteTime` timestamps.
  10. `poetry run axiom validation-run --scenario set_parameter_preview_apply_wall_comments --phase pre --revit-version 2027 --tests --no-deploy`.
  11. Upload `artifacts/validation_runs/**` as a workflow artifact.

It does **not** copy DLLs into the Revit Addins folder, launch Revit, or run
any prompt inside Revit. Live deploy + the live Revit step stay manual (see
`docs/runbooks/validation-loop-runbook.md`).

---

## Prerequisites on Axiom-01

Run the readiness check first (guidance only, no secrets):

```powershell
.\scripts\local\setup-github-runner-notes.ps1
```

Required tooling:

- **Git** for Windows.
- **Python 3.10+** (3.12 recommended) on `PATH`.
- **Poetry** on `PATH` (the workflow will `pip install poetry` if missing, but
  having it preinstalled is cleaner).
- **.NET 10 SDK** - only needed if you will use `build_revit_addin`.
- **Revit 2027** installed + licensed - only needed for the optional build
  (the build references `RevitAPI.dll` / `RevitAPIUI.dll` under
  `C:\Program Files\Autodesk\Revit 2027\`).

---

## Installing the self-hosted runner

GitHub generates the exact download commands + a one-time token for you. Always
copy them from the repo page rather than hard-coding anything.

1. In GitHub, go to the repo -> **Settings -> Actions -> Runners -> New
   self-hosted runner**. Choose **Windows** / **x64**.
2. On Axiom-01, open PowerShell **as the Revit-licensed user** (see user-context
   notes below) and create a runner folder, e.g.:
   ```powershell
   mkdir C:\actions-runner; cd C:\actions-runner
   ```
3. Run the **download** commands shown on that GitHub page (they pin a specific
   runner version + checksum).
4. Run the **config** command shown on the page, appending the required labels:
   ```powershell
   .\config.cmd --url https://github.com/<owner>/<repo> --token <ONE_TIME_TOKEN> --labels axiom-01,revit-2027
   ```
   - `self-hosted` and `windows` are applied automatically; add `axiom-01` and
     `revit-2027` explicitly.
   - The `<ONE_TIME_TOKEN>` comes from the GitHub page and expires quickly.
     **Do not** store it in the repo or in any script.
5. Start the runner:
   - Interactive (recommended for Revit licensing): `.\run.cmd`
   - Or install as a service: `.\svc.cmd install` then `.\svc.cmd start`
     (see service-user caveats below).

### Where to register it

Register at the **repository** level (Settings -> Actions -> Runners) for this
single repo. Avoid org-level registration so the Revit machine is only used by
this private repo.

### Required labels

The workflow targets `runs-on: [self-hosted, windows, axiom-01, revit-2027]`.
All four labels must be present or the job will stay queued.

---

## Service user / Windows user considerations

- **Revit licensing is per-user / interactive.** If you ever extend this beyond
  `-BuildOnly` to launch Revit, the runner must run as the **interactive,
  Revit-licensed Windows user** - not as `LocalSystem` or a headless service
  account, which typically cannot check out a Revit license or resolve the
  correct `%LOCALAPPDATA%`.
- For the current foundation (tests + ruff + BuildOnly + `pre` phase), running
  `.\run.cmd` interactively as the Revit-licensed user is the safest choice.
- If you install the runner as a Windows **service**, set the service "Log on
  as" account to that same Revit-licensed user, and be aware a non-interactive
  session may still fail Revit licensing for future live steps.

### Admin vs non-admin deployment warning

- **Run the runner non-elevated** for tests, ruff, BuildOnly, and the `pre`
  phase. None of these need admin.
- **Deploy is the only step that needs admin** (copying DLLs into
  `C:\Program Files\Autodesk\Revit\Addins\2027`). This workflow intentionally
  does **not** deploy. When you do a real deploy, do it manually with
  `scripts/deploy-revit-2027.ps1` (optionally `-ForceCloseRevit`) from an
  elevated shell, or use `scripts/local/run-validation-loop.ps1 -Deploy
  -ElevateDeploy` which elevates only the deploy step.
- Do not run the whole runner as admin just to enable deploy - keep elevation
  scoped to the deploy action.

---

## How to manually trigger the workflow

1. In GitHub: **Actions** tab -> **Windows Revit Validation (Axiom-01)**.
2. Click **Run workflow**.
3. Choose the branch, optionally toggle **build_revit_addin** and set
   **revit_version**, then **Run workflow**.

The job will pick up on Axiom-01 if the runner is online and idle (the
`concurrency` group serializes runs so only one executes at a time).

---

## Interpreting success / failure

- **Green run:** Python tests + ruff passed; the Validation Loop `pre` phase
  produced an artifact bundle. Download it from the run's **Artifacts**
  (`validation-run-artifacts`) and inspect `result_summary.md` /
  `manual_revit_steps.md`. A `pre` run ends at `revit_manual_step_pending`,
  which is the expected handoff - perform the live Revit step, then run the
  `scan` phase locally (`validation-run --phase scan --run-id <id>`).
- **Red run - tests/ruff step failed:** a Python/lint regression. Read the
  failing step log; fix on a branch and re-run.
- **Red run - build step failed:** check the `.NET 10 SDK` / `RevitAPI.dll`
  prerequisites in the readiness check; this only runs when
  `build_revit_addin` is enabled.
- **Job stuck "Queued":** the runner is offline or missing a label. Confirm the
  runner shows **Idle** in Settings -> Actions -> Runners with all four labels.

The CLI exits non-zero on a non-pass classification (except the expected
pre-phase `revit_manual_step_pending`), so a failing validation surfaces as a
red step.

---

## Disabling / removing the runner

- **Pause temporarily:** stop `.\run.cmd` (Ctrl+C) or `.\svc.cmd stop`. The
  workflow simply won't pick up until it's back.
- **Disable the workflow:** GitHub -> Actions -> select the workflow -> **Disable
  workflow** (... menu). It can no longer be dispatched.
- **Remove the runner cleanly:**
  ```powershell
  cd C:\actions-runner
  .\config.cmd remove --token <ONE_TIME_REMOVE_TOKEN>
  ```
  Get the remove token the same way (Settings -> Actions -> Runners -> the runner
  -> Remove). If the machine is gone, delete the runner entry directly in the
  GitHub UI.
- If installed as a service: `.\svc.cmd stop; .\svc.cmd uninstall` before
  `config.cmd remove`.

---

## Out of scope (intentionally)

- New Revit capabilities; Selection/Filter Engine.
- Automatic Revit validation on every PR.
- Live Revit model mutation / automatic prompt execution inside Revit.
- Autodesk Assistant / MCP integration.
- Any change to CreateGrids / CreateLevels / InventoryModel / SetParameterValue
  behavior.
