# Tallnum 计算器与自动玩

[English](README.md) | 简体中文

Tallnum 的本地计算与辅助工具，提供 Windows 桌面计算器、C++ 状态枚举和值迭代、PETSc 策略评估，以及 Python 路线规划、模拟验证和网页自动玩。

本仓库保留运行、构建所需的源码、资源、回归测试与精简验证记录。大型预计算概率表、完整逐局回放、运行检查点及浏览器资料不随源码发布。小规模计算可直接从源码开始；大目标的状态空间和定式库可能很大，需要较长计算时间和足够内存、磁盘空间。

## 本轮进展

已整合通用概率表路线规划器及桌面界面：可指定容量、任意整数目标及允许使用的定式规格（至少五格、目标至少24），先规划结构，再核对概率表。优化顺序为先降低最高阶五格定式，再减少其主路线调用次数；缺表、预算不足与已绑定候选路线分别报告。计算器输出两枚可见待出数对应的36种状态成功概率。

路线执行加入真实开局衔接、空余容量利用、回退和EDGE残留连接修复。相同100个种子的概率表测试结果为：十格8192为94/100（308阶段，最高五格60），10240为87/100（426阶段，最高五格64、主路线14次），12288为91/100（448阶段，最高五格80、主路线10次）。这些是指定版本的有限样本结果，不是任意路线的胜率保证。

使用入口、数据缺口、逐局摘要和验证范围见[进展与验证记录](docs/PROGRESS.zh-CN.md)、[通用规划器说明](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md)及[桌面说明](desktop/README.zh-CN.md)。五格64上限仅属于10240低阶路线约定，不是通用规划器的限制。

## 目录

```text
automation/                       Python 规划、策略认证、模拟与网页控制
  vendor/tallnum.mjs               固定版本的游戏规则参考
  build.ps1                       五格/六格策略桥、生成器与 PETSc 图评估器
  build-pending.ps1               动态搜索所需的期望值查询程序
aggressive-version/               带激进度参数的 C++ 核心与构建脚本
desktop/                          Electron + React 桌面应用
  assets/tray.png                  托盘图标
  scripts/build-native.ps1         统一原生构建入口
  src/                            主进程、界面及进程通信
tallnum_reachable.cpp              状态枚举与转移表生成
tallnum_vi.cpp                     值迭代与表读取
tallnum_policy_eval.cpp            PETSc 固定策略评估
export_replay_128_a001_no_death.cpp 自动化桥复用的动作还原代码
start-dynamic10240.cmd             已备好数据的十格动态模式启动入口
docs/VALIDATION.zh-CN.md            本机实际构建与运行验证记录
```

`export_replay_128_a001_no_death.cpp` 虽然沿用历史名称，但会被原生策略桥和动态查询程序直接引用，是构建依赖。`validation.py`、`validate_buffer_rescue.py`、`validate_entry_bridge.py` 和规则核对用的 `.mjs` 文件属于运行功能，用于检查策略是否可执行。

## 获取源码

```powershell
git clone https://github.com/Crazy-Bull/tallnum-ai.git
cd tallnum-ai
```

## 一、准备环境

目前支持并验证的构建目标是 **Windows x64**。需要：

- **PowerShell**：以下命令在 PowerShell 中执行，MSYS2 安装命令除外。
- **Node.js 18.17 或更新版本**，附带 npm；桌面依赖版本由 `desktop/package-lock.json` 锁定。
- **Python 3.11 或更新版本**；NumPy、SciPy、Playwright、websocket-client、ijson 由 requirements 安装。
- **MSYS2 UCRT64**：提供 GCC、pkg-config 和 PETSc。使用 sequential double precision 的 `petsc-dso` 配置。
- 网页自动玩另需安装 **Chrome 或 Edge**，并允许远程调试连接。

先检查 Node.js 与 Python：

```powershell
node --version
npm --version
python --version
```

安装 MSYS2 后，打开 **MSYS2 UCRT64** 终端执行：

```sh
pacman -Syu
# 如果提示关闭终端，关闭并重新打开 UCRT64 后继续。
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-petsc mingw-w64-ucrt-x86_64-pkgconf
pkg-config --modversion petsc-dso
```

后续 PowerShell 命令默认从解压或克隆得到的**项目根目录**执行。

## 二、安装 Python 依赖

建议为项目创建独立环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\automation\requirements.txt
$env:TALLNUM_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
$env:PATH = (Join-Path $PWD '.venv\Scripts') + ';' + $env:PATH
```

这些环境变量对当前 PowerShell 及其启动的子进程有效。之后从这个窗口执行 `python`、启动桌面程序即可使用该环境。重新打开 PowerShell 时需再次设置环境变量，也可直接执行 `.\.venv\Scripts\python.exe`。

桌面自动玩后端优先使用 `TALLNUM_PYTHON` 指定的程序，未设置时使用 PATH 中的 `python`。单纯使用已打包桌面的计算器功能不需要 Python；自动玩和路线规划需要它。

## 三、构建并运行桌面程序

### 1. 构建原生核心

```powershell
$env:TALLNUM_MSYS_ROOT = 'C:\msys64'  # 改为你的 MSYS2 安装根目录
.\desktop\scripts\build-native.ps1
```

未设置 `TALLNUM_MSYS_ROOT` 时使用项目内的 `.tools/msys64`。脚本会构建原版和激进度求解器、五格/六格自动化桥、PETSc 图评估器和动态期望值程序，并复制所需 DLL。输出主要位于 `desktop/native/`、`aggressive-version/bin/`，动态程序位于 `automation/`；中间文件写入 `.build-tmp/`。这些目录和二进制均已配置为忽略提交。

### 2. 安装桌面依赖

```powershell
cd desktop
npm ci
```

首次安装会下载 Electron 运行程序，需要联网。不要使用 `ELECTRON_SKIP_BINARY_DOWNLOAD=1` 跳过下载后直接尝试启动；该选项仅适用于已有独立 Electron 运行环境的构建场景。

### 3. 运行

开发模式（界面源码修改可热更新）：

```powershell
npm run dev
```

生产构建后本地启动：

```powershell
npm run typecheck
npm run build
npm start
```

关闭主窗口会收起到托盘；完整退出请使用托盘菜单的“保存并退出”。

### 4. 打包

生成无需安装的目录版：

```powershell
npm run dist:dir
& '.\release\win-unpacked\Tallnum 计算器.exe'
```

生成 Windows 安装包：

```powershell
npm run dist:win
```

安装包输出为 `desktop/release/Tallnum-Calculator-0.3.0-win-x64.exe`；打包时可能需要下载 NSIS 等工具。目录版必须保留整个 `win-unpacked/`，不能只复制其中的 EXE。安装包内的计算核心和 DLL 已配齐，运行计算器不需要 MSYS2；自动玩仍需可用的 Python 环境。当前构建未配置代码签名和自动更新。

## 四、使用桌面计算器

1. 打开“新建计算”，选择数据保存目录，填写空格数、目标数字、最大出现数字、目标占格上限、允许的基和成功位置。
2. 设置激进度：`0` 使用原概率目标；非零值会为未成功出数引入风险，使策略偏向较快成功。它不等于指定平均步数。
3. 设置值迭代（VI）与 PETSc 阶段的轮数、误差阈值和求解预算，创建任务。
4. 在任务页查看状态数、阶段进度、概率、残差和日志；可暂停、继续或取消，多个任务串行执行。
5. 在结果对比页选择任务及阶段，按需导出 JSON 或 CSV。

首次检查建议使用小参数：**3 格、目标 16、最大出现数字 32、目标最多占 1 格、基 1/3/5/15、成功位置 above**，VI 先运行 20 轮。不要用大目标作为安装是否成功的首次检查。

每个任务在所选目录下创建独立子目录，保存 `spec.json`、`transitions.bin`、检查点、阶段结果与日志。暂停和续算需要匹配的规则与文件指纹；旧规则数据可能需要重新生成。VI 是近似值，PETSc 评估的是固定策略，两者都不自动构成全局最优证明。

## 五、命令行计算

先完成原生构建，然后回到项目根目录。以下小规模示例将结果写入单独目录：

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

`values.bin`、`policy.bin` 必须与对应转移表配套使用。上面的计算示例不等于已准备好网页自动玩的策略库，自动玩还要求合适的出口、认证结果和路线验证。

## 六、路线规划、验证与网页自动玩

### 五格定式组合流程

在项目根目录执行，所有步骤使用同一个数据目录和目标：

```powershell
python -m automation plan --directory automation/runs/<run-directory> --target 768
python -m automation prepare --directory automation/runs/<run-directory> --target 768
python -m automation validate --directory automation/runs/<run-directory> --target 768 --candidate-limit 1 --attempts 100
```

- `plan` 生成拆解并列出缺失定式，首次没有策略数据时出现缺失列表是正常状态。
- `prepare` 生成、求解并认证缺失策略；大目标耗时可能很长。中断后在同目录重跑可复用已完成的结果。
- `validate` 在模拟中验证候选路线。`--candidate-limit 1 --attempts 100` 是低预算检查，不代表全面评估或长期胜率保证。

桌面“自动玩”页也提供检查、补算和验证入口。结果通过验证且文件没有变化后，再连接游戏。

### 新版七格/十格路线规划器

新版入口为 `python -m automation route`，结果使用独立的 `route-*.json`：

```powershell
python -m automation route plan --directory automation/runs/route192 --cells 7 --target 192 --node-limit 10000
python -m automation route continue --directory automation/runs/route192 --node-limit 10000
python -m automation route prepare --directory automation/runs/route192
python -m automation route validate --directory automation/runs/route192 --attempts 100
```

`--node-limit` 限制本次新增搜索预算，`0` 表示不设这个限制；达到预算后的结果可能不完整。十格需要显式设置 `--cells 10`。`--max-value` 控制中间数字上限；完整参数以 `python -m automation route --help` 为准。

### 连接已有游戏

先在 Chrome 的 `chrome://inspect/#remote-debugging` 中启用远程调试，打开游戏标签页，并接受浏览器的连接提示。也可通过 `--cdp-endpoint` 指定已启用调试的浏览器端点。Edge 使用 `--browser msedge`。

```powershell
python -m automation play --directory automation/runs/<run-directory> --target 768
# 新版路线使用对应入口及目录：
python -m automation route play --directory automation/runs/route192
```

推荐通过桌面页控制暂停、单步和连续运行。命令行模式通过数据目录下的 `control.json` 控制，例如：

```powershell
'{"mode":"paused"}' | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
@{mode='step';token=[DateTime]::UtcNow.Ticks} | ConvertTo-Json -Compress | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
'{"mode":"run"}'    | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
'{"mode":"stop"}'   | Set-Content automation/runs/<run-directory>/control.json -Encoding ascii
```

每次单步命令的 `token` 必须变化，上面的命令会自动生成新值。

程序使用正常键鼠输入并核对盘面，不修改游戏存档和 RNG。识别不一致或输入结果不确定时会暂停并记录现场。`--resume-current-game` 用于根据已确认记录恢复当前局；`--finish-current-game` 会将当前盘面继续投放至结束，含义不同。仅在已有记录与当前游戏相符时使用恢复功能。

### 高级功能

- `python -m automation.expected_routes --help`：按认证定式的期望成本构建权重与规划。
- `python -m automation.seven_routes --help`：七格结构搜索。
- `python -m automation.nonstandard_base --help`：非标准基合成搜索。
- `python -m automation.even_precompute --help`：批量偶数目标预计算。
- `python -m automation.binary_routes --help`：二叉路线搜索；使用前准备对应权重文件。
- `python -m automation.six_template_compute --help`：生成与评估六格定式。
- `python -m automation.prepare_pending_search --help`：从已有路线、策略及值函数生成动态期望缓存。
- `python -m automation.pending_search_mode --help`：准备和验证独立的动态模式。

高级入口需要相应输入库。`start-dynamic10240.cmd` 只适用于已准备完整十格 10240 路线和动态缓存的环境，不是首次安装的一键数据生成器。

## 七、数据、故障排查与更新

运行数据默认在 `automation/runs/`，可通过 `--directory` 指定其他磁盘。共享认证策略库默认 `automation/runs/shared-clean`，可在启动前设置 `TALLNUM_SHARED_LIBRARY`。数据应存放在有写入权限且空间充足的目录，不要写入 Windows 的程序安装目录。

- **MSYS2/GCC/PETSc 找不到**：核对 `TALLNUM_MSYS_ROOT`，确认使用 UCRT64，并在该终端检查 `pkg-config --modversion petsc-dso`。
- **Python 模块缺失**：使用与 `TALLNUM_PYTHON` 一致的解释器重新执行 `-m pip install -r automation/requirements.txt`。
- **Electron 找不到**：确认没有跳过 Electron 下载，重新执行 `npm ci`。
- **npm 缓存无写入权限**：将 `$env:npm_config_cache` 设置为你有权限写入的目录，再执行安装或构建，无需将缓存放在 Program Files。
- **提示缺少原生程序或 DLL**：重新执行统一原生构建；分发目录版时保留整个目录结构。
- **提示缺少策略、路线或哈希不一致**：在相同规则和目录下重新 prepare、validate；不要混用不同目标或旧规则的二进制文件。
- **连接不到浏览器**：确认调试已启用、连接提示已允许，并检查浏览器选择或显式 CDP 端点。
- **计算长时间运行**：先查看阶段日志与残差，大状态空间并非启动失败；先用上述小规模参数检查环境。

更新 C++ 代码后重建原生核心；更新桌面代码后执行 `npm run build` 或重新打包；依赖锁定文件变化后执行 `npm ci`。本机验证的具体范围与结果见 [验证记录](docs/VALIDATION.zh-CN.md)。

## 仓库维护与来源

本目录是仓库根目录。`.gitignore` 排除依赖、工具链、编译输出、计算数据和本机配置。提交前通过 `git status --short` 检查清单；安装包可作为 GitHub Release 附件发布，大型策略数据独立保存。

目前未添加统一开源许可证。第三方游戏规则与依赖的来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
