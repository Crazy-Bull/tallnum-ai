# Tallnum 自动游玩成功率优化记录

本文汇总十格 10240 自动游玩中，针对规则正确性、定式出口、阶段衔接和动态选动作所做的优化。重点记录当前路线实际接入的实现、可复核的模拟数据和仍未解决的限制。

## 结论先读

最新严格动态版在固定的 100 局验证集中合成普通单格 10240 **86 局**。每局逐步交由原 JavaScript 引擎回放核对，共 **898,554 个操作**，种子 RNG 一致、没有强制出数；动态搜索没有 `out-of-model-board`，六格 single 出口残留违规为 0。相较较早的 100 局版本，成功数从 81 增至 86；这是特定验证样本的结果，不是长期真实胜率保证。完整统计见 [最终汇总](runs/six-strict-single-002/validation-100-entry-gate-fix/summary.json)、[原引擎核对](runs/six-strict-single-002/validation-100-entry-gate-fix/validation.json.engine-check.json) 和 [测试配置](runs/six-strict-single-002/validation-100-entry-gate-fix/configuration.json)。

## 做过哪些优化

不使用五格80的新路线另见[迭代记录](NO80_ROUTE_ITERATION.zh-CN.md)。该路线正在迁移本文件中的出口、缓冲回退、入口恢复和动态选动作策略；尚未达到85/100，不能套用下述旧路线86/100的成绩。

### 1. 让模型胜利条件与真实盘面一致

旧的定式成功状态可能带着多余组合块结束，后续 match 或 single 定式便会遇到模型未承诺处理的块，甚至在十格盘面尚有空间时快速失败。新计算把“目标出口成立且不留多余组合块”写进生成器的终止条件：single 必须以普通目标块结束；match、buffer、extend 可以留下规定的目标组合块，但不能留下其他组合块。它是搜索和概率计算条件，不是计算后删掉坏终点；新旧表、断点和查询缓存也用不同身份标记，避免混用。

实现说明：[CLEAN_EXIT.md](CLEAN_EXIT.md)；定式表登记与规则元数据：[library.py](library.py) 中的 `table_header`、`register`；生成器规则：[tallnum_reachable.cpp](../tallnum_reachable.cpp)。

### 2. 修正 match 的 EDGE 保护规则

match 定式中，如果 EDGE 操作区域最下方的数去掉个位后与保护边界块去掉个位后的值相同，就禁止 EDGE。这样模型不会假定转向时可以吞并受保护的目标块。该限制仅用于 match；single 和 buffer 仍按各自规则计算。实现也明确以 EDGE 操作时紧邻 `F` 的活动块与 `TARGET` 比较，保护段另一侧的残留不误触发限制。

规则实现：[tallnum_reachable.cpp](../tallnum_reachable.cpp) 的 `applyRightTurn`；单元验证：[match_edge_guard.cpp](tests/match_edge_guard.cpp)；规则版本和策略登记：[library.py](library.py)。

### 3. 收紧六格 32、40、48 single 的 EDGE 和出口

六格 single 新增两条约束：

- **保护边界的 EDGE 限制**：若活动区紧邻保护块的数字去个位后与目标数去个位相同，定式不能做 EDGE，避免 EDGE 意外合并保护块。
- **干净的小残留出口**：目标必须是紧邻保护边界的普通单格；其他残留最多一格，且必须是值不超过 8 的普通块。保护边界两侧的残留都计入；不允许留下组合块。

模型成功判定、执行器出口连接和阶段合同使用相同约束。计算中还修复了“旋转后看见目标便提前算成功”的时序错误：真实游戏会继续投放队列数字，所以现在必须完整模拟旋转及投放后再判定出口。严格规则写进 `TNPEND03` / `TNQUERY5` 等缓存身份，旧缓存不能冒充新规则结果。

实现与设计说明：[SIX_STRICT_SINGLE.zh-CN.md](SIX_STRICT_SINGLE.zh-CN.md)；执行器出口核对：[route_runtime.py](route_runtime.py) 中 `single-exit-residual-exceeds-limit` 检查；动态值文件读取和规则核对：[pending_value.cpp](pending_value.cpp)、[library.py](library.py)。

### 4. 六格阶段改用 single 定式，再做真实的等值连接

高成功率的六格定式不再用 match 定式直接吞掉入口保护块，而是优先用相同目标的 single 定式产出普通单格，再让真实游戏规则完成等值合并。这样保留了可验证的目标块身份，并减少六格定式将边界块、残留块一起吸收的机会。路线合同会核对连接后的目标、占格和残留；如果 single 出口不满足严格条件，执行器不会把它当成成功。

路线转换：[single_six.py](single_six.py) 的 `use_single_six`；等值连接和出口检查：[route_runtime.py](route_runtime.py)；对应的严格定式目录在 [validation-100-entry-gate-fix/catalog.json](runs/six-strict-single-002/validation-100-entry-gate-fix/catalog.json)，十格路线阶段在 [route.json](runs/six-strict-single-002/validation-100-entry-gate-fix/route.json)。

路线中有些数值看起来像“额外块”，但实际上是明确的中间合同。例如第167阶段的60 match 出口产生普通120；紧接着的六格40 single 入口合同保留 `[5120, 120]`。因此120本身不是搜索过程越界，是否有问题要看它是否符合该阶段的 `before/after` 合同。阶段定义记录在 [strict 动态路线快照](runs/six-strict-single-002/validation-100-entry-gate-fix/route.json)；路线设计说明也提醒，不要把策略表内部终点误当成整局目标。

### 5. 给所有 match 配置 buffer 救援和阶段回退

match 定式遇到策略判死、保护段冲突、容量不足或已知危险入口时，执行器可尝试同规格、同十进制头的 buffer 定式。buffer 做出可用于清理的块后，通过 EDGE 消除当前 match 锚块，并按路线边界退回到产生锚块之前，重新执行后续阶段。回退点按路线合同查找，因此像 32→64、40→80 这种多层连接也能退回到正确位置。执行过程中保留真实盘面、队列、已发生投放和 RNG，不伪造出数，也不清盘。

旧路线已配置的映射是 `32→30、40→48、48→40、60→64、64→60、80→84`。buffer 定式的工作区至少五格，出口目标组合块最多占四格；这里的“四格”指组合块占格，不是四格定式。允许的中间最大数不低于48，且经过两轮固定策略概率复核。避开五格80的新路线不使用80→84救援。

实现：[route_runtime.py](route_runtime.py) 的 `_start_buffer_rescue`、`_next_buffer_rescue`；规则说明和映射：[BUFFER_RESCUE.zh-CN.md](BUFFER_RESCUE.zh-CN.md)；最终十格路线中的实际映射：[validation-100-entry-gate-fix/route.json](runs/six-strict-single-002/validation-100-entry-gate-fix/route.json)。

配对验证中，`buffer-rescue-all-007` 的 71 次救援全部完成，100 局成功 49 局；作为前一阶段结果，它比“没有这套救援”的配对路线多 25 局成功、少 2 局成功。见 [buffer-rescue-all-007 汇总](runs/binary10240/min24/buffer-rescue-all-007/summary.json) 及 [详细设计与比较](BUFFER_RESCUE.zh-CN.md)。

### 6. 用待出数状态期望概率在局内搜索动作

固定策略只会沿预先生成的动作走。动态模式离线保存待出数状态的期望完成概率，局内按当前盘面和两枚可见预览枚举免费操作及三个投放方向，比较后继状态的模型概率，再还原成可执行动作。公式和“当前两枚预览参与决策、只对之后揭晓的下一枚数取平均”的解释见 [PENDING_VALUES.zh-CN.md](PENDING_VALUES.zh-CN.md)。

此次还修正了此前造成大量 `out-of-model-board` 的查询入口错误：查询一个六格定式时，不再要求**当前入口盘面本身**也必须是六格概率字典的键；算法真正需要查询的是候选操作和投放之后的状态。仍会检查真实入口的物理占格不超过定式容量，最终后继和动作恢复继续走字典校验。五格字典仍保留原有入口登记方式。

实现：[pending_value.cpp](pending_value.cpp) 的 `query` 入口与 `best` 后继查询；Python 查询接线和缓存身份检查：[library.py](library.py) 的 `PolicyWorker`；执行阶段：[route_runtime.py](route_runtime.py)；更新后的动态目录在 [pending-search](runs/binary10240/min24/pending-search-all-policies-001)。

结果上，早期全路线动态验证为 53/100，之后发现六格当前入口被错误地做字典成员检查：修正前的一轮严格 single 验证有 8,380 次 `out-of-model-board` 查询错误，99 局受影响，成功 81/100；入口修正后错误为 0，成功 86/100。两份报告见 [修正前](runs/six-strict-single-002/validation-100/summary.json) 和 [修正后](runs/six-strict-single-002/validation-100-entry-gate-fix/summary.json)。该对比说明修复消除了这类域外查询，并在该批种子中多完成 5 局；不能单凭 100 局断言长期成功率提高幅度。

### 7. 保留固定开局与真实的 5120 后续路线衔接

验证过的开局结构仍为：**128 → 三次六格 single 40 构造 buffer120 → EDGE24 → 六格 single 40**。后面接入严格动态路线，不重置随机队列或残留。达到目标后，继续模式把底层目标在虚拟搜索盘面中视作一半，计算后续目标；真实盘面、锚块 ID 和两枚预览保持不变，并逐步核验真实/虚拟盘面的一致性。需要时尝试保持锚块的 EDGE 恢复。

开局构造与合同：[opening128_40.py](opening128_40.py)；半目标后续：[play_upgrade640.py](play_upgrade640.py) 的 `with_half_boundary`、[execution.py](execution.py) 的 `VirtualRouteExecutor`；10240 实际路线组合：[play10240.py](play10240.py)。路线结构和完整路线核对输入：[validation-100-entry-gate-fix/route.json](runs/six-strict-single-002/validation-100-entry-gate-fix/route.json)。

### 8. 用路线搜索筛选定式组合，并避免把结构最优误当胜率最优

十格路线由一连串五格/六格定式、match/Group/EDGE 连接组成；规划器用保护段、块的物理占格和入口/出口合同搜索组合，并用定式的成功概率及成本排序候选。较小目标不强行追求非零激进度；现行限制包括目标至少24、中间最大数至少48、五格目标低于48的激进度取0。旧的三次方难度权重曾误选128的0.05策略，之后审计了实际 `input_aggressiveness` 并修正，避免把“按零猝死条件评估”误当成“策略本身激进度为0”。

结构/成本规划器：[ROUTE_PLANNER.zh-CN.md](ROUTE_PLANNER.zh-CN.md)、[LOW_ORDER_ROUTES.zh-CN.md](LOW_ORDER_ROUTES.zh-CN.md)；有关128变体选择的审计：[binary10240/README.zh-CN.md](runs/binary10240/README.zh-CN.md)。规划器明确不证明真实随机可执行最优：十格路线最终仍须用真实队列、解锁、残留和两枚可见预览做整局模拟。早期五格64结构路线曾在真实随机测试中0/100完成，因此结构成本更低只能当候选筛选依据，不能取代整局验证，详见 [binary10240 实验记录](runs/binary10240/README.zh-CN.md)。

### 9. 真实入口恢复和可安全清掉的残留块

当真实入口带有组合块、固定策略无法直接接入时，入口桥会在真实十格盘面上搜索安全操作，优先使用能回到已验证策略入口的路线；若安全 EDGE 能清除活动区残留组合块且不破坏保护段，也会先清除后再接入。桥接后仍以原真实盘面和队列继续，不重置随机状态。不可安全恢复时仍可能失败，这项改动不能保证所有入口都可救。

实现：[entry_recovery.py](entry_recovery.py) 的 `RecoveryExecutor`、`recovery_action`；被十格回放验证的阶段和桥接结果记录于 [buffer-rescue-007](runs/binary10240/min24/buffer-rescue-all-007)。

### 10. 浏览器执行错误只重试未确认的拖动，并保护盘面

浏览器执行器在合并拖动前刷新起点位置；未命中或拖动被取消时，先读回动作计数与盘面，确认上一操作没有生效才重试。确认不一致时暂停并保存待执行操作及检查点，不盲目重复拖动。现有 Chrome 标签页连接使用10格配置，不另开游戏标签页。

实现：[browser.py](browser.py) 中 `BrowserAdapter`、`perform`、`_drag_group`；本次10格路线接入：[play10240.py](play10240.py)。这是浏览器执行可靠性改进，可避免输入失配导致局面与控制器脱节；它本身不提高定式的数学成功率。

## 主要验证数据与解释

| 版本/实验 | 整局完成 | 其他关键核验 |
| --- | ---: | --- |
| match buffer 救援 | 49/100 | 71 次救援全部完成；原引擎核对706,810个动作，RNG一致、未强制出数 |
| 全路线待出数动态搜索早期版 | 53/100 | 原引擎核对635,477个动作；这是早期路线基线 |
| 严格 single、入口闸门修正前 | 81/100 | 8,380次域外查询错误，99局受影响；原引擎核对871,915个动作 |
| 严格 single、入口闸门修正后 | **86/100** | 631,094次动态搜索；查询错误0；六格出口19,590次、违规0；原引擎核对898,554个动作，RNG一致、未强制出数 |

这些是完整游戏模拟，不是 PETSc 单定式概率。定式概率、所选动作的局部期望概率和整局完成率是不同指标。100局仍是有限样本；详细失败原因在最终 `summary.json` 中：14局失败主要是固定策略判死（10局），另有入口域外、保护段冲突、出口合同不匹配和残留组合块阻塞各1局，说明瓶颈尚未消失。

另有早期传统路线第十一轮在100局中实际合成过1局10240（7,344次投放），但那不是本文件记录的最新严格动态版本；见 [历史停止进度](runs/binary10240/min24/STOPPED_PROGRESS.md)。不要将不同路线、不同种子集或不同版本的结果直接当成相同条件下的胜率比较。

## 文件索引

2026-10-08：保留原开局和连接策略、不使用五格80及以上定式的新路线已通过完整百局验收，89/100成功。全部定式至少五格、目标至少24；成功局均调用五格64共17次。原引擎核对1,483,687个动作，RNG一致、未强制出数。详细设计、约束与证据见[不使用五格80的路线迭代记录](NO80_ROUTE_ITERATION.zh-CN.md)及[最终验收汇总](runs/no80-dynamic/validation-min24-v5-fresh/summary.json)。17次尚未证明为全局最少。

- 核心规则和模型：`automation/game.py`、`automation/tallnum_reachable.cpp`、`automation/library.py`、`automation/pending_value.cpp`。
- 路线与执行：`automation/route_runtime.py`、`automation/entry_recovery.py`、`automation/opening128_40.py`、`automation/single_six.py`、`automation/execution.py`、`automation/browser.py`、`automation/play10240.py`。
- 设计记录：`automation/CLEAN_EXIT.md`、`automation/SIX_STRICT_SINGLE.zh-CN.md`、`automation/BUFFER_RESCUE.zh-CN.md`、`automation/PENDING_VALUES.zh-CN.md`、`automation/runs/binary10240/min24/STOPPED_PROGRESS.md`。
- 最新严格动态验证：`automation/runs/six-strict-single-002/validation-100-entry-gate-fix/`（`summary.json`、`configuration.json`、`route.json`、`catalog.json`、`validation.json.engine-check.json`）。
- 浏览器会话记录：`automation/runs/six-strict-single-002/chrome-play/`（`actions.jsonl`、`checkpoint.json`、`rounds.jsonl`、`controller.log`；这些记录随实际浏览器游玩更新）。
