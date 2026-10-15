# Tallnum AI

English | [简体中文](README.zh-CN.md)

A local Tallnum solver and automation toolkit: a Windows desktop calculator, C++ state enumeration and value iteration, PETSc policy evaluation, and Python route planning, simulation, and browser control.

This repository contains source, assets, regression tests, and compact validation evidence. Large precomputed probability tables, full game replays, runtime checkpoints, browser profiles, and build dependencies are excluded. Small calculations can start from source; large targets may require substantial memory, disk space, and computation time.

## Integrated progress

The desktop application now includes a general probability-table route planner. Users can choose capacity, integer target, and allowed template contracts (at least five cells and target 24). Structural planning is separate from table binding, with distinct results for missing tables and incomplete searches. The objective first minimizes the highest five-cell template target, then its main-route call count. Calculator output contains success probabilities for all 36 pairs of visible previews.

Execution improvements cover opening connections, spare workspace, recovery, and residual EDGE alignment. Tests using the same 100 seeds achieved 94/100 for ten-cell 8192 (308 stages, five-cell peak 60), 87/100 for 10240 (426 stages, five-cell peak 64 called 14 times on the main route), and 91/100 for 12288 (448 stages, five-cell peak 80 called 10 times). These are finite-sample results for specific versions, not guarantees for arbitrary routes.

See the [progress and validation notes](docs/PROGRESS.zh-CN.md), [planner guide](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md), and [desktop guide](desktop/README.zh-CN.md). The five-cell target-64 cap belongs to the low-order 10240 route, not the general planner.

## Source layout

```text
automation/                       Planning, certification, simulation and browser control
  vendor/tallnum.mjs               Pinned reference game engine
  build.ps1                       Policy bridges, generator and PETSc graph evaluator
  build-pending.ps1               Pending-value worker for dynamic action search
aggressive-version/               C++ cores with the aggressiveness parameter
desktop/                          Electron + React desktop application
  assets/tray.png                  Tray icon
  scripts/build-native.ps1         Unified native build entry point
  src/                            Main process, renderer and IPC
tallnum_reachable.cpp              State enumeration and transition-table generation
tallnum_vi.cpp                     Value iteration and table reader
tallnum_policy_eval.cpp            PETSc fixed-policy evaluation
export_replay_128_a001_no_death.cpp Action recovery shared by native automation
start-dynamic10240.cmd             Launcher for an already prepared dynamic route
docs/VALIDATION.zh-CN.md            Local build and runtime verification record
```

Despite its historical name, `export_replay_128_a001_no_death.cpp` is directly included by the native policy bridge and pending-value worker. It is a required build dependency. The retained `validation.py`, `validate_buffer_rescue.py`, `validate_entry_bridge.py`, and engine-checking `.mjs` files are runtime features that verify executable policies and routes.

## Get the source

```powershell
git clone https://github.com/Crazy-Bull/tallnum-ai.git
cd tallnum-ai
```

The commands below run from the repository root unless stated otherwise.

## 1. Requirements

The supported and locally verified build target is **Windows x64**.

- **PowerShell** for the commands below, except the MSYS2 installation commands.
- **Node.js 18.17 or newer**, including npm. Desktop dependencies are pinned in `desktop/package-lock.json`.
- **Python 3.11 or newer**. NumPy, SciPy, Playwright, websocket-client and ijson are installed from requirements.
- **MSYS2 UCRT64**, including GCC, pkg-config and PETSc. The native build uses the sequential, double-precision `petsc-dso` configuration.
- Browser automation additionally requires **Chrome or Edge** with remote debugging enabled.

Check Node.js and Python:

```powershell
node --version
npm --version
python --version
```

After installing MSYS2, open its **UCRT64 terminal** and run:

```sh
pacman -Syu
# If instructed to close the terminal, reopen UCRT64 before continuing.
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-petsc mingw-w64-ucrt-x86_64-pkgconf
pkg-config --modversion petsc-dso
```

## 2. Python environment

Create a dedicated environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\automation\requirements.txt
$env:TALLNUM_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
$env:PATH = (Join-Path $PWD '.venv\Scripts') + ';' + $env:PATH
```

These variables apply to the current PowerShell session and its child processes. Run Python commands and launch the desktop app from that session. Set them again after opening a new terminal, or invoke `.\.venv\Scripts\python.exe` directly.

The desktop automation backend uses `TALLNUM_PYTHON` when set, otherwise `python` from PATH. The packaged calculator can run native calculations without Python; route planning and browser automation require Python.

## 3. Build and run the desktop app

### Build the native programs

```powershell
$env:TALLNUM_MSYS_ROOT = 'C:\msys64'  # Replace with your MSYS2 installation root
.\desktop\scripts\build-native.ps1
```

If `TALLNUM_MSYS_ROOT` is unset, the scripts use `.tools/msys64` inside the repository. The unified build compiles the original and aggressive solvers, five/six-cell policy bridges, PETSc graph evaluator, and pending-value worker, then copies the required DLLs.

Outputs are placed in `desktop/native/`, `aggressive-version/bin/`, and, for pending-value programs, `automation/`. Temporary compiler files go to `.build-tmp/`. Generated files are ignored by Git.

### Install desktop dependencies

```powershell
cd desktop
npm ci
```

The initial installation downloads Electron and requires internet access. Do not set `ELECTRON_SKIP_BINARY_DOWNLOAD=1` when you intend to run this app without an independently supplied Electron runtime.

### Start the app

Development mode with renderer hot reload:

```powershell
npm run dev
```

Build and run the production version locally:

```powershell
npm run typecheck
npm run build
npm start
```

Closing the main window minimizes the app to its tray icon. Use the tray menu's **保存并退出** (“Save and exit”) action to quit completely. The desktop interface currently uses Chinese.

### Package for Windows

Build an unpacked application directory:

```powershell
npm run dist:dir
& '.\release\win-unpacked\Tallnum 计算器.exe'
```

Build the installer:

```powershell
npm run dist:win
```

The installer is written to `desktop/release/Tallnum-Calculator-0.3.0-win-x64.exe`. Packaging may download NSIS tools. Keep the entire `win-unpacked/` directory when distributing the unpacked app; its executable alone is insufficient.

The package includes the native solvers and DLLs, so calculator users do not need MSYS2. Automation still needs a working Python environment. Code signing and automatic updates are not configured.

## 4. Use the calculator

1. Open **新建计算** (“New calculation”), select a data directory, and set the cell count, target, maximum intermediate value, maximum goal span, allowed bases, and success side.
2. Set aggressiveness. `0` uses the original probability objective; a nonzero value adds risk to unsuccessful drops and favors faster success. It does not specify an average number of moves.
3. Configure VI and PETSc stages, iteration budgets, and tolerances, then create the job.
4. Monitor states, probabilities, residuals and logs in the job view. Jobs run sequentially and support pause, resume and cancellation.
5. Compare jobs and stages, and export results as JSON or CSV.

For an initial environment check, use **3 cells, target 16, maximum value 32, maximum goal span 1, bases 1/3/5/15, success side above**, and 20 VI rounds. Start with this small job before attempting a large target.

Each job creates a separate subdirectory with `spec.json`, `transitions.bin`, checkpoints, results and logs. Resuming requires compatible rules and file fingerprints; older rule versions may require regeneration. VI produces an approximation and PETSc evaluates a fixed policy. Neither alone proves global optimality.

## 5. Native command-line quick start

After building the native programs, return to the repository root:

```powershell
New-Item -ItemType Directory -Force .\automation\runs\quickstart | Out-Null
$native = (Resolve-Path .\desktop\native).Path
Push-Location .\automation\runs\quickstart
try {
    & "$native\tallnum_reachable_clean.exe" --cells 3 --target 16 --max-value 32 --max-goal-cells 1 --output transitions.bin
    & "$native\tallnum_vi_aggressive.exe" transitions.bin 20 1e-9 values.bin --aggressiveness 0
    & "$native\tallnum_policy_eval.exe" -tallnum_table transitions.bin -tallnum_values values.bin -tallnum_aggressiveness 0 -tallnum_result result.json -tallnum_save_policy policy.bin -tallnum_save_values evaluated.bin -ksp_type gmres -ksp_rtol 1e-10 -ksp_max_it 2000
} finally {
    Pop-Location
}
```

Values and policies must match their transition table. This small calculation is not a complete browser automation policy library: automation also needs compatible exit contracts, certification, and route validation.

## 6. Route planning and browser automation

### Five-cell template composition

Use the same directory and target throughout the workflow:

```powershell
python -m automation plan --directory automation/runs/<run-directory> --target 768
python -m automation prepare --directory automation/runs/<run-directory> --target 768
python -m automation validate --directory automation/runs/<run-directory> --target 768 --candidate-limit 1 --attempts 100
```

`plan` writes the decomposition and lists missing policies. A missing-policy result is expected on the first run. `prepare` generates, solves and certifies them; large calculations can take a long time. Rerunning in the same directory reuses completed results. `validate` simulates candidate routes. One candidate and 100 attempts are a low-budget check, not an exhaustive comparison or a long-term win-rate guarantee.

The desktop automation page provides the same planning, preparation and validation steps. Connect to the game after validation passes and the input files remain unchanged.

### Version 2 planner: seven or ten cells

The `automation route` commands use separate `route-*.json` outputs:

```powershell
python -m automation route plan --directory automation/runs/route192 --cells 7 --target 192 --node-limit 10000
python -m automation route continue --directory automation/runs/route192 --node-limit 10000
python -m automation route prepare --directory automation/runs/route192
python -m automation route validate --directory automation/runs/route192 --attempts 100
```

`--node-limit` caps newly explored subproblems for the current run; `0` removes that cap. Budget-limited results can be incomplete. Ten-cell planning requires `--cells 10`. `--max-value` sets the intermediate-value limit. See `python -m automation route --help` for all options.

### Connect to an existing game

Enable remote debugging at Chrome's `chrome://inspect/#remote-debugging`, open the game tab, and accept the browser connection prompt. You can also supply a debugging endpoint using `--cdp-endpoint`. For Edge, add `--browser msedge`.

```powershell
python -m automation play --directory automation/runs/<run-directory> --target 768
# For a version 2 route, use its corresponding entry point and directory:
python -m automation route play --directory automation/runs/route192
```

The desktop controls provide pause, single step and continuous play. For CLI control, write `control.json` in the data directory:

```powershell
'{"mode":"paused"}' | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
@{mode='step';token=[DateTime]::UtcNow.Ticks} | ConvertTo-Json -Compress | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
'{"mode":"run"}'    | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
'{"mode":"stop"}'   | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
```

Every single-step request needs a new `token`; the command above generates one automatically.

The player uses ordinary keyboard/mouse input and checks the resulting board. It does not modify game saves or RNG state. Uncertain inputs or inconsistent observations cause a pause and save diagnostic evidence. `--resume-current-game` restores a game from confirmed records, while `--finish-current-game` plays the current board to its end. Resume only when the saved records match the current game.

### Advanced tools

- `python -m automation.expected_routes --help`: measured template-cost weights and route planning.
- `python -m automation.seven_routes --help`: seven-cell structural search.
- `python -m automation.nonstandard_base --help`: nonstandard-base synthesis.
- `python -m automation.even_precompute --help`: batch precomputation for even targets.
- `python -m automation.binary_routes --help`: binary route search, requiring prepared weights.
- `python -m automation.six_template_compute --help`: six-cell template generation and evaluation.
- `python -m automation.prepare_pending_search --help`: dynamic pending-value caches from existing routes, policies and value functions.
- `python -m automation.pending_search_mode --help`: prepare and validate an isolated dynamic mode.

These tools require their corresponding input libraries. `start-dynamic10240.cmd` launches a fully prepared ten-cell 10240 mode; it does not generate a complete library on first installation.

## 7. Data, troubleshooting and updates

Runtime data defaults to `automation/runs/`. Choose another disk using `--directory`. The shared certified library defaults to `automation/runs/shared-clean`, overridable with `TALLNUM_SHARED_LIBRARY`. Use a writable directory with enough free space, rather than a Windows application installation directory.

- **Missing MSYS2/GCC/PETSc**: check `TALLNUM_MSYS_ROOT`, the UCRT64 environment, and `pkg-config --modversion petsc-dso`.
- **Missing Python module**: install requirements with the same interpreter selected by `TALLNUM_PYTHON`.
- **Missing Electron**: ensure its download was not skipped, then rerun `npm ci`.
- **Unwritable npm cache**: set `$env:npm_config_cache` to a writable location before installing or building; the cache need not reside in Program Files.
- **Missing native program or DLL**: rerun the unified native build and preserve the complete packaged directory structure.
- **Missing policies/routes or fingerprint mismatch**: prepare and validate using the same rules and directory. Do not mix targets or old rule versions.
- **Browser connection fails**: check debugging, the connection prompt, browser selection, or the explicit CDP endpoint.
- **Long calculation**: inspect stage logs and residuals. A large state space does not indicate a startup failure; verify the environment using the small example first.

Rebuild native programs after C++ changes. Run `npm run build` or repackage after desktop changes, and `npm ci` after lockfile changes. See the [local verification record](docs/VALIDATION.zh-CN.md) for the tested scope and actual results.

## Repository maintenance and provenance

This directory is the repository root. `.gitignore` excludes dependencies, toolchains, compiled outputs, calculation data and local configuration. Inspect `git status --short` before committing. Installers can be published separately as GitHub Release assets; keep large policy libraries outside ordinary Git history.

No project-wide open-source license has been added. Third-party code and dependencies retain their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
