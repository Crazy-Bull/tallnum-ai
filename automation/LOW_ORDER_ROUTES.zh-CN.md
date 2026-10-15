# 低阶定式优先的大数路线规划器

最新结果：全部使用五格定式，五格 64 最少调用 **13 次**，已在记录的有限合成模型内闭合上下界证明。旧 16 次候选保留作比较。见 [完整路线与证明](runs/binary10240/minimum64/README.zh-CN.md)。




入口为 `automation.binary_routes`，支持七格、十格和 2～65535 的普通单格目标。
目标及中间普通块允许非标准基；例如 54、1728。其他奇数除 15 外不能成为普通块。

## 路线优劣

默认 `--objective difficulty`。先按定式格数，再按目标值确定阶数，从高到低比较调用次数。
同阶的 single、match、extend 合并计数。较高一阶少一次，优先于任意数量的低阶调用；
所有阶数计数相同时，再比较已提供的独立重试权重。调用次数按展开后的实际调用计，
不是不同定式的种类数，也不是去重后的树节点数。

内部用可加的计数向量比较子路线，避免只记录“最大值和次数”导致子路线最优选择失效。
`leafCalls` 仍报告总调用数；`difficultyProfile` 报告用于排序的完整阶数分布。

未指定定式上限时，纯五格库自动从低到高尝试上限。空间上界能直接排除的上限无需展开。
十格目标 10240 自动选择 64，无需写目标专用规则或手动禁用 80。
已有六格策略的混合库按完整格数/目标计数向量搜索，不使用纯五格的上限扫描。

## 运行与续算

```powershell
# 自动选择最低定式上限，允许非标准基中间块
python -m automation.binary_routes 10240 --cells 10 --directory automation/runs/binary10240/replanned --maximum 20480 --edge-depth 5 --node-limit 3000

# 非标准基的大数目标
python -m automation.binary_routes 1728 --cells 10 --directory automation/runs/nonstandard1728 --maximum 8640 --edge-depth 5 --node-limit 3000

# 明确限制为 64 及以下；all 枚举所有合法偶数拆分及 15
python -m automation.binary_routes 10240 --cells 10 --directory automation/runs/strict64 --maximum 20480 --maximum-leaf-target 64 --split-mode all --node-limit 150000
```

相同命令再次运行会复用完整子问题并继续未完成搜索。`--node-limit 0` 表示不设预算。
种子构造和优化分别使用预算；预算耗尽返回 `paused` 和已找到的完整候选，不能据此判不可达。
默认 guided 包含标准族及其三倍族，覆盖 1728 等关键中间块；它是明确记录的有限候选域。
`all` 放开拆分候选，仍保留中间数值上限和 EDGE 嵌套深度。

省略 `--weights` 时声明标准五格结构接口，不虚构策略统计：单位结构成本只记录调用数，
所有使用的接口列入 `missingPolicies`，仍需固定策略认证。提供 `--weights FILE` 时只调用文件
中已有策略，可用 `--objective weight` 显式恢复旧的独立重试权重目标。
旧权重库缺少已认证的小目标接口时，不能把“该库找不到”解释成“游戏中不可达”。

Python 接口：

```python
from automation.binary_routes import BinaryPlanner, structural_snapshot

planner = BinaryPlanner(
    "automation/runs/my-planner",
    structural_snapshot(65535),
    maximum=65535,
    edge_depth=5,
    node_limit=3000,
)
try:
    result = planner.plan(1728, cells=10)
finally:
    planner.close()
```

## 搜索与验证边界

搜索包含等值倍增、左右两种有序拆分、连续复用边界块、普通成员 Group 和递归 EDGE。
即使只剩五个工作格，也允许不消耗额外格子的边界复用。不会嵌套 Group。
每个连接按完整有序保护盘面和实际占格检查；成功子树可在其他前缀下重新验证后复用。

纯五格结构的乐观上界记 L 为最大叶子目标：
`M(5)=L, M(n)=3M(n-1), S(5)=L, S(n)=2M(n-1)`。
Group 新增普通成员的总量不超过 M(n)；连续边界匹配最多翻倍 M(n)，再补齐 M(n)，
给出下一格的匹配上界。EDGE 降低质量，按嵌套深度归纳后上界仍成立。
这些上界只适用于本规划语法，不是任意游戏操作的全局不可能性证明。

结果区分：

- `minimumPeakProvenInScope`：自动上限扫描在所记录语法/候选域内排除了所有更低上限。
- `minimumDifficultyProvenInScope`：完整计数向量优化已完成；paused 时为 false。
- `idealConnectionsVerified`：完整保护盘面的结构连接成立。
- `executionVerified`：真实随机策略执行认证，本规划入口始终不代替该认证。

改变规则、策略权重、目标域、格数或上限会使用不同缓存身份。

## 10240 的重规划结果

结果保存在 `automation/runs/binary10240/replanned/binary-plan.json`。
路线不使用 80、96 或 128 定式；最高为五格 64，调用 16 次，共 1216 次叶子调用。
这是预算内的当前最佳计数向量，完整次数最优性尚未证明。

最后一次 5120 配对使用：

`1728 + 1728 + 1664 = 5120`

先将两份 1728 普通合并成 3456，再把 1664 构造成普通成员 `1152 + 384 + 128`。
在保护的 5120 右侧执行 `Group(3456,1152,384,128)`，立即合并成普通 10240。
1728、1152 等非标准基通过较小数上的 EDGE 引入，再倍增，不能只搜索标准族。

新路线的指定出数见证完成真实 `[2,4]` 开局和永久解锁，共 5362 次投放、6663 个动作，
最多占用九格。Python 与原版 JavaScript 引擎逐动作一致。
见证保存在同目录的 `controlled-witness.json`，它证明存在合法出数路线，不给出随机成功率。

```powershell
python -m automation.binary_witness automation/runs/binary10240/replanned/binary-plan.json --output automation/runs/binary10240/replanned/controlled-witness.json
node automation/binary_witness_check.mjs automation/runs/binary10240/replanned/controlled-witness.json
```
