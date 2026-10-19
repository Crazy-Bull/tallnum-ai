# Tallnum AI

English | [简体中文](README.zh-CN.md)

**Understand a template. Plan a route. Check it against the real game.**

Tallnum AI is a local toolkit for [Tallnum](https://pku2048.cn/tallnum): a desktop probability-table calculator, route planners, complete-game validation and browser autoplay. Use the graphical interface, explore constructions with Python, or work directly with the C++ solvers.

The desktop source now supports **English and Simplified Chinese**. Select **Language / 语言** in the sidebar. Your choice is remembered in the current app profile; changing language does not change model parameters, stored inputs, paths, raw logs or probability files.

This repository contains source, assets, regression tests, and compact validation evidence. Large precomputed probability tables, full game replays, runtime checkpoints, browser profiles, and build dependencies are excluded. Small calculations can start from source; large targets may require substantial memory, disk space, and computation time.

## A real game: 18,476

![Original Tallnum game-over screenshot showing a board total of 18,476](docs/images/tallnum-live-18476.png)

This original screenshot was saved at the end of our October 14, 2026 browser run. The game reached an ordinary **12,288** tile, then continued with the bottom tile treated as a **virtual 6,144 inside the planner**, while its real value stayed unchanged. Final board total: **18,476**; **38,009 drops and 58,824 actions**.

**18,476 is the board sum, not a single tile.** The largest ordinary tile was 12,288; a residual Group worth 6,144 contributes to the total. The screenshot was taken while the site was checking/uploading the score, so it does not establish a verified leaderboard placement. See the [evidence summary](docs/validation/live-18476.json).

## Where should I start?

- **Just exploring:** read the results below, then try the no-table structural example in [General route planning](#general-route-planning-current-workflow).
- **Using the GUI:** follow sections 1–4. The calculator, comparison view, both planners and autoplay support English/Chinese.
- **Running real games:** first prepare and validate the matching library. A generated structure is not yet an executable, tested player.
- **Developing algorithms:** use the module guide and regression commands near the end.

Commands are grouped by workflow. The general planner, integer planner, original template workflow and v2 workflow produce different files; their launch commands are not interchangeable.

## Recorded results

The desktop application now includes a general probability-table route planner. Users can choose capacity, integer target, and allowed template contracts (at least five cells and target 24). Structural planning is separate from table binding, with distinct results for missing tables and incomplete searches. The objective first minimizes the highest five-cell template target, then its main-route call count. Calculator output contains success probabilities for all 36 pairs of visible previews.

Execution improvements cover opening connections, spare workspace, recovery, and residual EDGE alignment. Tests using the same 100 seeds achieved 94/100 for ten-cell 8192 (308 stages, five-cell peak 60), 87/100 for 10240 (426 stages, five-cell peak 64 called 14 times on the main route), and 91/100 for 12288 (448 stages, five-cell peak 80 called 10 times). These are finite-sample results for specific versions, not guarantees for arbitrary routes.

All three tests used the same 100 seeds, two visible previews, Standard draw-pool unlocking, no forced draws, recovery enabled and a 100,000-action budget per game. No games were unfinished. The original engine checked 794,191 / 2,041,549 / 3,185,745 actions respectively. Additional recovery calls are recorded separately from main-route counts.

These results do not prove a future success probability of at least 85%. New routes inherit no measurement unless route, catalog and execution-source fingerprints match. The earlier **13-call structural 10240 construction** and the current **14-call, 87/100 executable route** are different results. An older 89/100 run used a fixed-policy opening and is not a probability-only baseline.

See the [progress notes](docs/PROGRESS.zh-CN.md), [compact 300-game evidence](docs/validation/route-execution-2026-10/manifest.json), [planner guide](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md), and [desktop guide](desktop/README.zh-CN.md). Verify published identities without computing tables:

```powershell
python tools/verify-release-evidence.py
```

## Concepts worth knowing

- **Template:** a reusable task with a capacity, target, entry assumptions and exit. New templates require at least **five cells** and target **24**. The five-cell target-64 ceiling applies to the low-order 10240 route, not to the general calculator/planner.
- **F:** the protected segment outside the template workspace. Capacity counts physical cells; one Group can occupy several cells.
- **`single` / `match` / `extend`:** produce an ordinary single tile, match an existing boundary, or extend a boundary with a limited-span result. Identical target numbers do not make these exits interchangeable.
- **Group / EDGE:** real grouping and boundary merging operations. Residual tiles, protected IDs and automatic merge cascades must fit the next stage.
- **Probability table:** state success values used to choose actions dynamically. Calculator output contains all **36 `(q1,q2)` preview pairs**; their average is not a substitute for the matrix. Historical fixed-action tables are different artifacts.
- **Bases vs draws:** allowed bases constrain intermediate values, not the draw distribution. The calculator's six possible previews and actual game unlocking need to be distinguished.
- **Candidate vs measured route:** fitting ideal exits is only a structural check. Full randomized games and original-engine replay are separate checks.

The repository includes **catalog metadata, not the large binary table library**. Catalog paths refer to the original machine and usually do not exist on a fresh clone. Generate/import matching local files and use your own catalog. Missing files mean a data gap, not an impossibility proof. Never bypass fingerprints to reuse unrelated data. The name `peak13-assets` is historical and does not promise 13 calls for every current route.

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
- **Python 3.11 or newer**. NumPy, SciPy, Playwright and websocket-client are installed from requirements.
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

The desktop automation backend uses `TALLNUM_PYTHON` when set, otherwise `python` from PATH. The two planner managers currently invoke `python` from PATH, so set both variables as above. The packaged calculator can run native calculations without Python; route planning and browser automation require Python. Requirements currently list NumPy, SciPy, Playwright and websocket-client; native builds additionally need MSYS2/PETSc. Structural examples do not require native compilation.

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

Choose **English** or **简体中文** in the sidebar. The calculator, job comparison, both planners and autoplay share this choice. Raw logs, JSON/code displays and user input retain their original contents. Closing the main window minimizes the app to its tray icon. Use the tray menu's **保存并退出** (“Save and exit”) action to quit completely.

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

The installer name uses the version in `desktop/package.json` (currently 0.4.0) and is written under `desktop/release/`. Packaging may download NSIS tools. Keep the entire `win-unpacked/` directory when distributing the unpacked app; its executable alone is insufficient. This source/documentation update does not publish a new installer; existing installed copies need rebuilding/repackaging to receive the language switch.

The package includes the native solvers and DLLs, so calculator users do not need MSYS2. Automation still needs a working Python environment. Code signing and automatic updates are not configured.

## 4. Use the calculator

1. Open **New calculation**, select a writable absolute data directory, and name the job. Set workspace **5–255 cells**, target **24–65535**, maximum intermediate value, goal span **1–5**, allowed bases, and success side. Each job has its own subdirectory.
2. Set aggressiveness. `0` uses the original probability objective; a nonzero value adds risk to unsuccessful drops and favors faster success. It does not specify an average number of moves.
3. Select a template exit preset or custom rules. `single` requires one goal cell; `extend` permits at most four. Presets require clean success above F. Six-cell single boundary guards/tidy exits only apply to their corresponding six-cell clean models.
4. Configure **probability-table VI stages**, iteration budgets and maximum-change tolerances. Add/reorder stages, repeat the pipeline or save a preset. New tasks cannot use historical fixed-policy stages.
5. Monitor state count, iterations, residuals and the **6×6 preview probability matrix**. Jobs run sequentially and support pause/resume/cancel. A final stage that has not converged is not marked formally completed.
6. Compare different jobs or stages of the same job; JSON/CSV exports include individual preview pairs and probabilities. Read the rule differences before comparing numbers.

For an initial workflow check, use the default five-cell target 48 or a valid smaller target such as 24 with a modest VI budget. This is a smoke test, not a guarantee of convergence within that budget. Start with a small model before attempting five-cell 128 or six-cell enumeration.

Each job stores `spec.json`, `transitions.bin`, metadata, generation/VI checkpoints, `stage-N.values.bin`, `stage-N.pending.csv`, events and logs. The job index is in Electron's app-data directory. Rules and SHA-256 fingerprints must match for resuming. Historical PETSc tools evaluate fixed policies; their presence does not mean new desktop jobs use fixed-policy stages. See the [calculator guide](desktop/README.zh-CN.md).

## 5. Native command-line quick start

After building the native programs, return to the repository root:

```powershell
New-Item -ItemType Directory -Force .\automation\runs\quickstart | Out-Null
$native = (Resolve-Path .\desktop\native).Path
Push-Location .\automation\runs\quickstart
try {
    & "$native\tallnum_reachable.exe" --cells 5 --target 24 --max-value 48 --max-goal-cells 1 --output transitions.bin
    & "$native\tallnum_vi_aggressive.exe" transitions.bin 20 1e-9 values.bin --aggressiveness 0
    & "$native\tallnum_policy_eval.exe" -tallnum_table transitions.bin -tallnum_values values.bin -tallnum_aggressiveness 0 -tallnum_result result.json -tallnum_save_policy policy.bin -tallnum_save_values evaluated.bin -ksp_type gmres -ksp_rtol 1e-10 -ksp_max_it 2000
} finally {
    Pop-Location
}
```

This is an advanced solver/evaluation example, not the new GUI job pipeline. A short VI run may not converge, and PETSc's subsequent fixed-policy evaluation does not turn it into a certified probability-only autoplay policy. All files must match their transition table. Prefer the desktop calculator for current probability-table tasks.

## General route planning: current workflow

The general planner separates structural contracts from probability-table binding. It accepts capacities **1–255** and integer targets **2–65535**, including nonstandard-base targets. Accepting an input does not guarantee reachability or completion within a finite search budget.

Try this on a fresh clone, without tables:

```powershell
python -m automation.probability_route_planner 96 --cells 7 --allow-template 7:96:single --out automation/runs/example-seven
```

Expect a structural result reporting missing tables. With your own complete catalog:

```powershell
python -m automation.probability_route_planner 10240 --cells 10 --catalog C:/TallnumData/catalog.json --out automation/runs/my-10240 --node-limit 3000
python -m automation.probability_route_planner 80 --cells 6 --catalog C:/TallnumData/catalog.json --allow-template 6:40:single --out automation/runs/my-80
```

Replace the example catalog path with a real file. Repeat `--allow-template cells:target:exit` to choose exact contracts; omit it to use all suitable catalog entries. Contracts may have **5–255 cells**, targets **24–65535**, and exits `single`, `match` or `extend`. A missing contract can be requested without automatically triggering a large calculation.

The objective first lowers the **highest five-cell target**, then its main-route call count. It does not prohibit six-cell or larger templates. `--maximum`, `--edge-depth` and `--node-limit` bound numeric values, EDGE nesting and subproblem work. Run `--help` for the exact interface.

Read `planning-report.json` before using the output:

- **`candidate`:** writes `route.json` with bound table contracts; full-game success has not been measured yet.
- **`missing-probability-tables`:** writes `structural-route.json` and lists gaps; not executable yet.
- **`incomplete`:** the budget left the answer unresolved; increase it to continue.
- Other statuses distinguish capacity limits, directly drawn goals, impossible ordinary targets and no construction in the chosen scope. Read the reason and scope rather than equating every failure with “the game is unsolvable.”

The desktop **Probability route planner** exposes the same settings, default/custom template selection and missing-table reports. Execution binding checks physical space, complete entry/exit boards, residuals, startup and recovery. Only exact fingerprint matches display historical 100-game measurements. See the [planner guide](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md).

### Structural bounds: a separate desktop page

The **Structural planner** is the older integer/DP pipeline for seven or ten cells. It shows an incumbent upper bound, independent lower bound, peak-minimality status, call distribution and step trace. Use automatic or explicit ceilings, numeric/EDGE limits and search budgets. Equal bounds prove a call count within that model; they do not certify real-game draws or win rates. Draw-unlocking warnings matter. Matching parameters can reuse cached work.

### Probability-only simulation

The historical runner is `automation.probability_route_validate`. It requires matching binary tables and native query programs, plus the original seed ledger at `automation/runs/six-strict-single-002/validation-100-entry-gate-fix/main-ledger.jsonl`. That ledger and full replays are not distributed; published configurations contain the seeds. The command below is for a prepared experiment, not a fresh-clone quick start:

```powershell
python -m automation.probability_route_validate --route path/to/route.json --catalog path/to/catalog.json --out automation/runs/my-validation --attempts 100
```

The runner supports 1–100 attempts, journals per-seed games, checks run identity before resuming, and checks compressed replays with the pinned real engine. Keep changed versions in new directories. Structural verification, randomized full-game simulation and original-engine replay are three distinct checks; compact published summaries cannot replace the full action logs for replaying a game. Evidence-registration scripts only record completed matching tests.

## 6. Route planning and browser automation

### Five-cell template composition

This is the **original library workflow**, not the general planner above. It retains historical policy-evaluation machinery; its older results must not be presented as the current probability-only benchmark. `prepare` can trigger expensive enumeration. Use the same prepared library and validation files throughout.

Use the same directory and target throughout the workflow:

```powershell
python -m automation plan --directory automation/runs/legacy-demo --target 768
python -m automation prepare --directory automation/runs/legacy-demo --target 768
python -m automation validate --directory automation/runs/legacy-demo --target 768 --candidate-limit 1 --attempts 100
```

`plan` writes the decomposition and lists missing policies. A missing-policy result is expected on the first run. `prepare` generates, solves and certifies them; large calculations can take a long time. Rerunning in the same directory reuses completed results. `validate` simulates candidate routes. One candidate and 100 attempts are a low-budget check, not an exhaustive comparison or a long-term win-rate guarantee.

The desktop automation page provides the same planning, preparation and validation steps. Connect to the game after validation passes and the input files remain unchanged.

### Version 2 planner: seven or ten cells

This earlier staged workflow writes `route-*.json`. Its player expects that workflow's validated files, not an arbitrary `route.json` produced by the general planner.

The `automation route` commands use separate `route-*.json` outputs:

```powershell
python -m automation route plan --directory automation/runs/route192 --cells 7 --target 192 --node-limit 10000
python -m automation route continue --directory automation/runs/route192 --node-limit 10000
python -m automation route prepare --directory automation/runs/route192
python -m automation route validate --directory automation/runs/route192 --attempts 100
```

`--node-limit` caps newly explored subproblems for the current run; `0` removes that cap. Budget-limited results can be incomplete. Ten-cell planning requires `--cells 10`. `--max-value` sets the intermediate-value limit. See `python -m automation route --help` for all options.

### Connect to an existing game

Open the intended game and enable remote debugging as required by your Chrome build; current builds may expose it at `chrome://inspect/#remote-debugging`. Manually allow its connection prompt. Supply `--cdp-endpoint` when discovery cannot find the correct profile. For Edge, use `--browser msedge`. Avoid manually moving tiles while the controller is running.

```powershell
python -m automation play --directory automation/runs/legacy-demo --target 768
# For a version 2 route, use its corresponding entry point and directory:
python -m automation route play --directory automation/runs/route192
```

The desktop controls provide pause, single step and continuous play. For CLI control, write `control.json` in the data directory:

```powershell
'{"mode":"paused"}' | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
@{mode='step';token=[DateTime]::UtcNow.Ticks} | ConvertTo-Json -Compress | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
'{"mode":"run"}'    | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
'{"mode":"stop"}'   | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
```

Every single-step request needs a new `token`; the command above generates one automatically.

The player uses ordinary keyboard/mouse input, checks the board and reconciles uncertain input before any resend. It does not modify game saves/RNG or read invisible future draws. Disconnecting preserves the browser. `--resume-current-game` requires matching confirmed records. **`--finish-current-game` is not a harmless resume flag:** it can finish/drain the current round and restart according to the workflow. Virtual-half continuation requires a compatible continuation contract and only changes the planner's interpretation, not game data.

Prefer the desktop controls. If editing a live `control.json` manually, publish it by atomic temporary-file replacement; the simplified examples above illustrate its contents, not a substitute for safe concurrent writing.

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

### Module guide: inputs, outputs and when to use them

- **`automation.integer_planner`:** structural construction, peak-call optimization and independent lower bounds. Example: `python -m automation.integer_planner 10240 --cells 10 --directory automation/runs/integer-demo --node-limit 3000`. Writes `integer-result.json`, `binary-plan.json` and `ideal-connection-trace.json`. Bounds apply to the displayed synthesis scope, not randomized play. See [minimum-call method](automation/MINIMUM64_METHOD.zh-CN.md).
- **`automation.binary_routes`:** reusable single/match/extend/buffer contract search for seven/ten cells. Accepts optional measured weights, intermediate/EDGE limits and a node budget. It reuses subproblems and records constructions/caches. Local independent-retry costs are not whole-game restart costs. See [binary routes](automation/BINARY_ROUTES.zh-CN.md).
- **`automation.expected_routes`:** `prepare`, `weights`, `plan`, `score` commands using compatible template statistics and additive expected-cost estimates. Do not average conditional subtask durations and call the result a whole-game expectation. See [expected costs](automation/EXPECTED_ROUTES.zh-CN.md).
- **`automation.seven_routes`:** searches one or more ordinary targets with `--target`, shared cache directory and candidate/node limits; optional JSON export. See [seven-cell search](automation/SEVEN_ROUTES.zh-CN.md).
- **`automation.nonstandard_base`:** bounded primitive synthesis of an odd base or exact target; accepts initial tiles, allowed inputs, numeric bounds and action/drop objectives. A chosen input sequence is not a random-draw autoplay policy. See [nonstandard bases](automation/NONSTANDARD_BASE.zh-CN.md).
- **`automation.even_precompute`:** precomputes bounded constructions for even targets and supports `--lookup`. Reuse the same rule parameters and cache directory. See [batch precomputation](automation/EVEN_PRECOMPUTE.zh-CN.md).
- **`automation.six_template_compute`:** sequential six-cell generation, solving and evaluation; `--strict-single` requests guarded/tidy single exits. Set `--data-root` explicitly to your own writable large disk; historical defaults refer to the original machine. Some evaluation stages are historical fixed-policy research, not substitutes for probability-only acceptance. See [six-cell contracts](automation/SIX_STRICT_SINGLE.zh-CN.md).
- **`automation.prepare_pending_search`:** builds pending-state query data from an existing source run. Optional five-cell exits, six-cell singles and rescue-buffer definitions can be expensive. `pending_search_mode` prepares/validates the associated isolated 10240 experiment. See [pending values](automation/PENDING_VALUES.zh-CN.md).
- **`automation.probability_route_execution`:** common physical execution binding: spare workspace, valid strict producers, opening connections, residual handling and recovery. Used automatically by the general planner; it does not itself prove a win rate.
- **`automation.probability_route_validate` and record scripts:** full probability-only randomized experiments, original-engine checks and identity-based result registration. See the prerequisites above; registration cannot manufacture validation.
- **`automation/browser.py`, `existing_browser.py`, `resume.py`, `execution.py`:** input/observation reconciliation, existing-tab connection, confirmed-log replay and virtual continuation. Their session journals/checkpoints are runtime data, not shipped browser profiles.
- **`tallnum_reachable.cpp` / `tallnum_vi.cpp`:** state enumeration and probability value iteration. Normal users should let the desktop manage rules, checkpoints and 36-state exports.
- **`tallnum_policy_eval.cpp`, `aggressive-version/`, `petsc_graph_eval.cpp`:** PETSc evaluation, alternative objectives and historical diagnostics. Artificial-risk probabilities, fixed-policy evaluations and new probability-table action selection are distinct. See [solver notes](aggressive-version/README.zh-CN.md).

Specialized `no80_*`, `peak_*` and variant-recalculation modules preserve research history and frequently depend on unshipped experiment directories. They are not first-run setup commands. The [success-rate optimization notes](automation/SUCCESS_RATE_OPTIMIZATIONS.zh-CN.md) explain why opening, draw-pool and physical-boundary behavior can make an apparently cheap structural route play badly.

## Development checks

From the repository root, after installing the appropriate dependencies:

```powershell
python tools/verify-release-evidence.py
python -m unittest automation.tests.test_probability_route_planner automation.tests.test_probability_route_execution automation.tests.test_connection_alignment automation.tests.test_boundary_rewind automation.tests.test_opening128_40 automation.tests.test_entry_recovery -v
node desktop/scripts/test-calculator-rules.cjs
node desktop/scripts/test-localization.cjs
npm --prefix desktop run typecheck
npm --prefix desktop run build
```

The localization test audits Chinese literals/fragments across all five frontend modules, renders them in English, checks saved-language initialization/dynamic messages, and preserves input values, callbacks and raw logs. Native/browser/large-data tests have extra prerequisites; these checks do not mean every historical integration test passed.

The main process owns files/processes; the renderer uses preload/IPC. Preserve atomic checkpoint writes, pause/cancel/exit semantics and SHA-256/rule identity checks. Runtime source/route bytes with published fingerprints intentionally retain their recorded line endings. See [progress and validation scope](docs/PROGRESS.zh-CN.md).

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
