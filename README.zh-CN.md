# Tallnum 计算器与自动玩

[English](README.md) | 简体中文

**算清一个定式，规划一条路线，再到真实游戏中检验。**

Tallnum AI 是面向 [Tallnum](https://pku2048.cn/tallnum) 的本地计算与辅助工具：既能在桌面界面里计算成功概率、规划路线，也能通过 Python 分析构造、验证完整对局，以及用正常键鼠操作真实网页。

当前桌面源码支持**简体中文和英文**，可在侧栏的 **Language / 语言** 中切换，并记住当前应用配置中的选择。切换只影响显示，不改动任务参数、用户输入、路径、原始日志或概率表。

本仓库保留运行、构建所需的源码、资源、回归测试与精简验证记录。大型预计算概率表、完整逐局回放、运行检查点及浏览器资料不随源码发布。小规模计算可直接从源码开始；大目标的状态空间和定式库可能很大，需要较长计算时间和足够内存、磁盘空间。

## 真实实战：18,476

![实战结束时的原始截图：终局盘面和18,476](docs/images/tallnum-live-18476.png)

这是2026年10月14日实机结束时直接保存的截图，没有重构盘面。程序先合成普通块 **12,288**，再把底层块**仅在规划器内部视作6,144**继续游玩，真实块值始终不变。最终盘面和 **18,476**，累计 **38,009次投放、58,824个动作**。

**18,476是盘面总和，不是单块数值。** 最大普通块为12,288，残留的6,144组合块也计入总和。截图当时网站仍在校验、上传成绩，因此它不用于宣称排行榜已认证名次。可核对[实战证据摘要](docs/validation/live-18476.json)。

## 我应该从哪里开始？

- **先了解成果**：看下面的实测记录，不需要安装任何工具。
- **只想规划结构**：从“通用路线规划器”的无表例子开始，只需Python及相关依赖，不必先编译原生程序。
- **想使用图形界面**：按第一至四节准备环境，界面包含计算器、对比、两类规划器和自动玩。
- **想复现实测或真实游玩**：先准备相应概率表、查询程序和验证数据。刚生成的结构不能直接等同于已实测的玩家。
- **想研究算法**：看后面的高级模块、原生入口和回归检查。

本项目保留了通用概率表规划、整数结构规划、原版定式组合和v2阶段规划几套入口。它们的数据文件与启动命令不同，下面会分别说明。

## 已达成的结果

已整合通用概率表路线规划器及桌面界面：可指定容量、任意整数目标及允许使用的定式规格（至少五格、目标至少24），先规划结构，再核对概率表。优化顺序为先降低最高阶五格定式，再减少其主路线调用次数；缺表、预算不足与已绑定候选路线分别报告。计算器输出两枚可见待出数对应的36种状态成功概率。

路线执行加入真实开局衔接、空余容量利用、回退和EDGE残留连接修复。相同100个种子的概率表测试结果为：十格8192为94/100（308阶段，最高五格60），10240为87/100（426阶段，最高五格64、主路线14次），12288为91/100（448阶段，最高五格80、主路线10次）。这些是指定版本的有限样本结果，不是任意路线的胜率保证。

三组测试使用相同100个种子、两个可见待出数、Standard发牌池解锁、无强制发牌、保命回退开启，每局预算100000动作，均无未完成局。原引擎分别核对794191、2041549、3185745个动作；回退增加的调用与主路线次数分开统计。

这些有限样本不等于已经统计证明未来成功率至少85%。新生成的路线只有与受测路线、定式目录和执行源码指纹一致，才可显示对应成绩。此前的**13次五格64结构构造**与当前**14次、87/100的可执行10240路线**属于不同模型/版本，不能拼成一个结论。旧89/100路线包含固定策略开局，也不能作为当前纯概率表基线。

可查看[进展说明](docs/PROGRESS.zh-CN.md)、[300局精简证据](docs/validation/route-execution-2026-10/manifest.json)、[通用规划器说明](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md)及[桌面说明](desktop/README.zh-CN.md)。无需补算大型概率表即可检查公开证据的身份：

```powershell
python tools/verify-release-evidence.py
```

## 先认识几个概念

- **定式**：有明确入口、容量、目标与出口的可复用子任务。新定式至少五格、目标至少24。五格目标不超过64只属于10240低阶路线约定，不是通用计算器或规划器限制。
- **F与格数**：F是定式工作区之外的保护段；格数按实际物理占位计算，一个Group虽然显示为一块，仍可能占多格。
- **single / match / extend**：分别是生成普通单块、匹配保护边界、延伸边界的出口。不能只因目标相同就互换。
- **Group / EDGE**：真实的组合与边界合并动作。残留块、保护身份、自动连锁合并和下一阶段的容量必须一起核对。
- **概率表**：在状态上保存成功概率，再据此选动作。计算器按两个可见待出数输出36种状态，平均概率不能代替逐状态结果。历史固定动作表是另一类数据。
- **允许的基与发牌**：基限制中间数的规则，并不改变发牌；定式模型中的六种待出数与真实游戏的解锁过程还需区分。
- **结构候选与实测路线**：理想出口能拼接，只是第一层检查；还需随机整局验证和原引擎回放核对。

仓库包含的是**目录元数据，不是完整二进制概率表库**。现有目录保留原机器的数据路径，新克隆通常没有这些文件。执行前请生成或导入自己的匹配表及目录；缺表不等于无解，不要修改指纹来绕过兼容性检查。`peak13-assets`也是历史目录名，不表示每条当前路线都只用13次。

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
- **Python 3.11 或更新版本**；NumPy、SciPy、Playwright、websocket-client由requirements安装。
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

桌面自动玩后端优先使用`TALLNUM_PYTHON`，未设置时使用PATH中的`python`；两个规划器管理器目前直接调用PATH中的`python`，因此请像上面一样同时设置PATH。已打包的本地计算器无需Python，规划与自动玩仍需要。仅试结构规划可以跳过原生编译。运行隔离的Playwright浏览器测试时，另执行`python -m playwright install chromium`；连接已有Chrome则使用本机Chrome。

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

安装包文件名使用`desktop/package.json`版本（目前0.4.0），输出至`desktop/release/`；打包可能下载NSIS。目录版必须保留整个`win-unpacked/`，不能只复制EXE。原生核心与DLL随包分发，计算器用户无需MSYS2，自动玩仍需Python。当前没有代码签名或自动更新。本次源码与本地化更新不等于已发布新安装包，已安装副本需要重新构建/打包才有语言切换。

## 四、使用桌面计算器

1. 打开“新建计算”，选择可写的绝对数据目录并命名任务。空格数为5–255、目标24–65535、最终占格1–5；可配置最大中间数、基与成功位置。每个任务独立占用一个子目录。
2. 设置激进度：`0` 使用原概率目标；非零值会为未成功出数引入风险，使策略偏向较快成功。它不等于指定平均步数。
3. 选择定式出口预设或自定义规则。single目标占一格，extend最多四格；预设要求F上方的干净出口。六格single边界保护与整洁出口只适用于对应的六格干净模型。
4. 配置**概率表值迭代阶段**：轮数预算与单轮最大变化阈值。可添加、排序、重复流程或保存预设；历史固定策略阶段不能用于新任务。
5. 在任务页查看状态数、迭代、残差和**6×6待出数状态概率表**；支持暂停、继续、取消，多个任务串行执行。最后阶段未收敛时不会标记为正式完成。
6. 结果对比可选择不同任务或同一任务的不同阶段；先核对规则差异，再比较逐状态概率。JSON/CSV均包含待出数与概率。

首次可用默认五格48，或五格24等合规小目标，配合适当VI预算检查流程；这不是保证该预算内收敛的正式算表配置。不要一开始就用五格128或六格状态枚举判断是否安装成功。

任务目录包含`spec.json`、`transitions.bin`、元数据、生成/VI检查点、`stage-N.values.bin`、`stage-N.pending.csv`、事件与日志；任务索引在Electron应用数据目录中。规则和SHA-256必须匹配才能续算。历史PETSc工具仍用于固定策略评估，不表示新桌面任务采用固定策略阶段。详见[计算器说明](desktop/README.zh-CN.md)。

侧栏的Language / 语言可切换English或简体中文，当前应用配置会记住选择。计算器、任务对比、两类规划器和自动玩共用此设置；原始日志、代码/JSON及用户输入不被改写。关闭主窗口会收起到托盘，彻底保存退出请用托盘菜单“保存并退出”。源码变化不会自动更新已安装程序，需重新构建或打包。

## 五、命令行计算

先完成原生构建，然后回到项目根目录。以下小规模示例将结果写入单独目录：

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

这是原生命令行计算/评估示例，不是新的桌面任务流程。短轮数VI可能未收敛，后续PETSc固定策略评估也不能替代新概率表实战验收。所有文件必须匹配转移表。普通用户建议通过桌面计算器管理概率表任务。

## 通用路线规划器：当前主入口

通用规划器将结构合同与概率表绑定分开，接受1–255格容量与2–65535整数目标，支持非标准基目标；接受输入不表示所有目标都可达，也不保证有限预算内求解完成。

新克隆无需概率表即可试：

```powershell
python -m automation.probability_route_planner 96 --cells 7 --allow-template 7:96:single --out automation/runs/example-seven
```

预期得到结构及缺表报告。有自己的完整目录后：

```powershell
python -m automation.probability_route_planner 10240 --cells 10 --catalog C:/TallnumData/catalog.json --out automation/runs/my-10240 --node-limit 3000
python -m automation.probability_route_planner 80 --cells 6 --catalog C:/TallnumData/catalog.json --allow-template 6:40:single --out automation/runs/my-80
```

请把示例目录换成真实文件。`--allow-template 格数:目标:出口`可重复指定；省略时使用目录中所有合适规格。定式可为5–255格、目标24–65535，出口single、match或extend；也能先请求无表的合同，由程序报告缺口，不自动启动昂贵补算。

优化顺序是先降低**最高阶五格目标**，再减少该阶主路线次数，并不排斥六格及更大规格。`--maximum`限制中间值、`--edge-depth`限制EDGE嵌套、`--node-limit`限制子问题预算；完整参数见`--help`。

先阅读`planning-report.json`：

- **candidate**：已绑定结构和现有表合同，写入`route.json`；还没有整局随机胜率。
- **missing-probability-tables**：写入`structural-route.json`并列出缺口，目前不可执行。
- **incomplete**：预算内未确定，可以增大预算继续，不是无解证明。
- 其他状态区分容量不足、可直接发出的目标、无法作为普通单块的目标及选定范围内找不到构造。应看reason和scope，不要把所有失败都理解为游戏绝对无解。

桌面“概率表路线规划”提供同样的输入、默认/自选列表和缺表报告；执行绑定检查真实工作格、完整入口出口、残留、开局与回退。只有指纹匹配时才显示历史百局成绩。详见[规划器说明](automation/PROBABILITY_ROUTE_PLANNER.zh-CN.md)。

### 单独的“结构路线规划”页面

这是较早的七格/十格整数与动态规划流程，用于研究五格构造与调用界限。可设自动/手动上限、数值范围、EDGE深度及预算；输出候选次数上界、独立下界、最高阶是否最低、调用分布和逐步盘面。上下界相等仅证明该模型范围内的次数，不认证真实发牌和胜率，应留意发牌解锁风险提示。相同参数可复用缓存。

### 概率表整局模拟

历史复测程序为`automation.probability_route_validate`。它需要匹配的二进制表、原生查询程序，以及未随仓库分发的原始种子账本`automation/runs/six-strict-single-002/validation-100-entry-gate-fix/main-ledger.jsonl`；公开配置里保留了种子列表。下列命令用于已恢复实验环境，不能当作新克隆开箱即用命令：

```powershell
python -m automation.probability_route_validate --route path/to/route.json --catalog path/to/catalog.json --out automation/runs/my-validation --attempts 100
```

程序支持1–100局，逐种子记账、续算前核对身份，生成压缩回放并用固定真实引擎核对。版本变化请另用新目录。结构核验、随机整局模拟、原引擎回放是三个不同检查；公开精简摘要不能代替完整动作日志进行原引擎重放。成绩登记脚本只登记完整匹配的已完成测试。

## 六、路线规划、验证与网页自动玩

### 五格定式组合流程

这是**原版目录工作流**，不是前面的通用规划器；仍保留历史策略评估机制，不能将旧成绩当作当前纯概率表基线。prepare可能启动昂贵枚举，请始终使用同一已准备目录和匹配验证文件。

在项目根目录执行，所有步骤使用同一个数据目录和目标：

```powershell
python -m automation plan --directory automation/runs/legacy-demo --target 768
python -m automation prepare --directory automation/runs/legacy-demo --target 768
python -m automation validate --directory automation/runs/legacy-demo --target 768 --candidate-limit 1 --attempts 100
```

- `plan` 生成拆解并列出缺失定式，首次没有策略数据时出现缺失列表是正常状态。
- `prepare` 生成、求解并认证缺失策略；大目标耗时可能很长。中断后在同目录重跑可复用已完成的结果。
- `validate` 在模拟中验证候选路线。`--candidate-limit 1 --attempts 100` 是低预算检查，不代表全面评估或长期胜率保证。

桌面“自动玩”页也提供检查、补算和验证入口。结果通过验证且文件没有变化后，再连接游戏。

### 新版七格/十格路线规划器

这是较早的v2阶段流程，写入`route-*.json`。其网页执行入口只接受该工作流的已验证文件，不能把通用规划器的任意`route.json`直接交给它。

新版入口为 `python -m automation route`，结果使用独立的 `route-*.json`：

```powershell
python -m automation route plan --directory automation/runs/route192 --cells 7 --target 192 --node-limit 10000
python -m automation route continue --directory automation/runs/route192 --node-limit 10000
python -m automation route prepare --directory automation/runs/route192
python -m automation route validate --directory automation/runs/route192 --attempts 100
```

`--node-limit` 限制本次新增搜索预算，`0` 表示不设这个限制；达到预算后的结果可能不完整。十格需要显式设置 `--cells 10`。`--max-value` 控制中间数字上限；完整参数以 `python -m automation route --help` 为准。

### 连接已有游戏

打开目标游戏，按所用Chrome版本要求启用远程调试；当前版本可能在`chrome://inspect/#remote-debugging`提供入口，连接提示请手动允许。自动发现无法定位配置时，可用`--cdp-endpoint`指定真实端点；Edge使用`--browser msedge`。程序运行时避免手动移动方块。

```powershell
python -m automation play --directory automation/runs/legacy-demo --target 768
# 新版路线使用对应入口及目录：
python -m automation route play --directory automation/runs/route192
```

推荐通过桌面页控制暂停、单步和连续运行。命令行模式通过数据目录下的 `control.json` 控制，例如：

```powershell
'{"mode":"paused"}' | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
@{mode='step';token=[DateTime]::UtcNow.Ticks} | ConvertTo-Json -Compress | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
'{"mode":"run"}'    | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
'{"mode":"stop"}'   | Set-Content automation/runs/legacy-demo/control.json -Encoding ascii
```

每次单步命令的 `token` 必须变化，上面的命令会自动生成新值。

程序使用正常键鼠输入、核对盘面，结果不确定时先对账再考虑重发；不改写存档/RNG、不读取不可见未来发牌，断开不关闭用户浏览器。`--resume-current-game`要求确认记录与当前局一致。**`--finish-current-game`不是无害的“续玩”开关**：它可能将当前局继续投放至结束，并按该流程重开。虚拟半值续玩需要匹配的continuation合同，只改变规划器解释，不改游戏数据。

优先使用桌面控制。上面的Set-Content示例展示控制内容；对正在运行的会话，实际写入应采用临时文件再原子替换，避免读取半写文件。

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

### 各模块应该什么时候用？

- **automation.integer_planner**：结构构造、最高阶次数优化与独立下界。例：`python -m automation.integer_planner 10240 --cells 10 --directory automation/runs/integer-demo --node-limit 3000`。输出`integer-result.json`、`binary-plan.json`、`ideal-connection-trace.json`；证明限于其合成模型，不是随机胜率。[最少调用方法](automation/MINIMUM64_METHOD.zh-CN.md)。
- **automation.binary_routes**：七格/十格single、match、extend、buffer合同搜索，接受可选实测权重、中间数/EDGE限制与节点预算，复用子问题和缓存。局部独立重试成本不能当作整局失败重开的期望。[二分构造说明](automation/BINARY_ROUTES.zh-CN.md)。
- **automation.expected_routes**：prepare、weights、plan、score四类操作，将匹配定式统计转为期望成本并规划/评分。不能平均子任务条件均值来代替整局期望。[成本说明](automation/EXPECTED_ROUTES.zh-CN.md)。
- **automation.seven_routes**：用`--target`指定一个或多个普通目标，配置共享目录、候选与节点限制，可导出JSON。[七格规划说明](automation/SEVEN_ROUTES.zh-CN.md)。
- **automation.nonstandard_base**：在有界初始块、允许输入与中间数范围内寻找非标准奇数基或精确目标的原语构造，可按动作或投放计成本。能选定输入序列的构造不等于随机发牌实战策略。[非标准基说明](automation/NONSTANDARD_BASE.zh-CN.md)。
- **automation.even_precompute**：批量预计算有界偶数目标，之后用`--lookup`查询；规则参数和缓存目录必须匹配。[批量预计算说明](automation/EVEN_PRECOMPUTE.zh-CN.md)。
- **automation.six_template_compute**：串行生成、求解、评估六格定式，`--strict-single`要求保护与整洁出口。请显式设置自己的大容量可写`--data-root`，历史默认路径属于原机器。部分评估步骤是历史固定策略研究，不能替代新概率表验收。[严格single说明](automation/SIX_STRICT_SINGLE.zh-CN.md)。
- **automation.prepare_pending_search**：从已有运行目录构建待出数查询数据；可选五格出口、六格single和保命buffer，可能很大。pending_search_mode用于对应10240隔离实验的prepare/validate。[待出数说明](automation/PENDING_VALUES.zh-CN.md)。
- **automation.probability_route_execution**：通用规划器自动调用的执行绑定修复，处理空余工作格、严格生产定式、开局衔接、残留与回退；本身不证明胜率。
- **automation.probability_route_validate及成绩登记脚本**：概率表整局实验、原引擎核对和基于身份的成绩登记。前置数据见前文，登记不会凭空产生验证结果。
- **browser.py、existing_browser.py、resume.py、execution.py**：分别承担输入/观测核对、连接已有标签页、确认日志恢复与虚拟半值续玩。会生成会话日志/检查点，不随源码分发浏览器配置。
- **tallnum_reachable.cpp / tallnum_vi.cpp**：状态/转移枚举及概率值迭代。一般使用桌面管理参数、检查点及36状态导出即可。
- **tallnum_policy_eval.cpp、aggressive-version/、petsc_graph_eval.cpp**：PETSc评估、替代目标及历史诊断。人工风险概率、固定策略评估与新概率表动作选择是不同结论。[原生求解器说明](aggressive-version/README.zh-CN.md)。

no80_*、peak_*及各变体重算模块保留了研究过程，常依赖未公开的运行目录，不是首次安装命令。关于“结构便宜但实战差”的原因，可读[成功率优化记录](automation/SUCCESS_RATE_OPTIMIZATIONS.zh-CN.md)，其中涵盖开局、发牌池、物理边界与回退。

## 开发与回归检查

在仓库根目录、装好相应依赖后：

```powershell
python tools/verify-release-evidence.py
python -m unittest automation.tests.test_probability_route_planner automation.tests.test_probability_route_execution automation.tests.test_connection_alignment automation.tests.test_boundary_rewind automation.tests.test_opening128_40 automation.tests.test_entry_recovery -v
node desktop/scripts/test-calculator-rules.cjs
node desktop/scripts/test-localization.cjs
npm --prefix desktop run typecheck
npm --prefix desktop run build
```

本地化回归核对五个前端模块的中文文案及动态片段、英文渲染、保存语言的初始化和动态提示，并确认输入值、回调与原始日志不被改写。原生、浏览器及大数据测试还需额外环境；以上检查不代表所有历史集成测试都通过。

主进程负责文件和子进程，界面通过preload/IPC调用。修改时保留检查点原子写入、暂停/取消/退出语义、SHA-256和规则身份核对。已有指纹的执行源码与路线按其原始字节保留，不能仅因换行转换使测量身份失效。详见[进展与验证范围](docs/PROGRESS.zh-CN.md)。

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
