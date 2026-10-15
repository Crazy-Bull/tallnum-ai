# 用定式期望投放数规划路线

入口：`python -m automation.expected_routes`，以及 Python API `build_weights`、`search`、`score_route`。

五格定式仅允许 1、3、5、15 基的目标（普通奇数只允许 15）。single、match、extend 是三种不同定式，分别计算权重；每个接口仅选择一个已有且经过出口验证的固定策略。默认选择激进度 0；有多个同激进度策略时，先选择最小数值上限，再选择已计算成本最低的一个。不计算五种激进度的全套变体。

## 权重含义

令 p 为单次成功率，u、v 为成功和失败的投放数加权矩。单次尝试直到成功或失败的期望投放数是 c=u+v。采用权重：

```text
定式权重 = c/p
路线总权重 = 每一次定式调用的权重之和
```

该权重包含本定式失败后从本定式入口重试的成本，避免把失败很快的策略误认为便宜。重复调用重复收费，Group、EDGE 连接不产生投放，权重为零；旋转附带的投放已计入固定策略的统计。

这里“步”指投放数，沿用项目的成本单位。该路线总和是独立局部重试的近似，不是整局失败后从开局重来的真实期望投放数。统计入口沿用五格模型的 uniform-first-36、iid-six-original-table，未直接建模十格解锁、隐藏队列、同值出数限制和各实际入口分布。

权重不再混入三次方难度、最大残局目标或该目标调用次数。它们可作为说明信息，但不决定新搜索的排序。

## 已有实际计算结果

`runs/expected-measured64/expected-weights.json` 已从固定策略图重新计算 10 个接口的概率与矩，而非读取难度公式。每个接口只使用一个基线变体：

- 16-single：约 8.440；16-match：约 5.430；16-extend：约 5.560。
- 24-single：约 16.162；24-match：约 8.046。
- 32-single：约 16.947；32-match：约 9.937；32-extend：约 10.002。
- 64-match、64-extend：均约 161.687。

较高的 64 残局成本现在由固定策略的计算结果决定；不同策略变体或入口统计可改变这个值。

七格 96 示例的模型内最小总权重约 42.649，路径是：24-single → 24-match 得到 48 → 16-single 得到 `[48,16]` → 32-extend 得到 96。结果在 `runs/expected96/expected-plan.json`。仅证明已列出定式的结构模型内最低权重，未证明策略执行成功或真实整局最佳。

十格 8192 的旧路线当前缺少 40-single/match、48-single/match、60-single/match、64-single 的有效权重，评分文件 `runs/expected-ten8192/expected-scores.json` 将完整总权重标记为 null，并列出缺项。已知部分的和不会冒充完整路线成本。七格 640 在当前已计算接口集合中未找到路线，也不意味着游戏中不可达。

## 计算与使用

从已有认证统计提取每个接口的一个变体：

```powershell
python -m automation.expected_routes weights --directory automation/runs/my-expected --catalog automation/runs/no80-dynamic/catalog.json
```

从策略图重新求解概率和期望矩：

```powershell
python -m automation.expected_routes weights --directory automation/runs/my-expected --catalog automation/runs/no80-dynamic/catalog.json --max-target 64 --recalculate
```

计算完成一个接口即保存矩缓存；图、策略或求矩代码变化会使相关缓存失效。重跑相同命令复用已有计算。

补算标准基定式（需要本项目原生计算程序及 PETSc，默认仅计算激进度 0）：

```powershell
python -m automation.expected_routes prepare --directory automation/runs/missing-expected --catalog automation/runs/no80-dynamic/catalog.json --targets 40 48 60 --exits single match
python -m automation.expected_routes prepare --directory automation/runs/missing-expected --catalog automation/runs/no80-dynamic/catalog.json --targets 64 --exits single
```

每次 prepare 后重新生成该目录的 expected-weights.json，包含已提供目录及新生成的已认证接口。不可终止、成功率为零、未认证的接口仍不成为有效权重，也不回退到三次方估算。

搜索与续算使用同一命令：

```powershell
python -m automation.expected_routes plan --directory automation/runs/my-search --weights automation/runs/missing-expected/expected-weights.json --target 8192 --cells 10 --node-limit 10000
```

已有候选按总权重比较：

```powershell
python -m automation.expected_routes score --directory automation/runs/my-scores --weights automation/runs/missing-expected/expected-weights.json --route automation/runs/ten8192/verified-route.json
```

score 也接受旧规划结果的 routes/structures 数组，一次评分并排序所有候选；完整可计价的候选优先，缺权重的候选不参与推荐。

## 搜索及证明范围

新搜索对完整有序保护前缀（值、占格、Group 标记）做记忆化 A* 搜索，包括已有 single/match/extend 合同、Group 及 EDGE 连接，五格工作区的预留沿用原模型。只允许具有已计算权重的定式动作，不以未知接口替代已验证统计。数值上限默认 max(48,2×目标)，最高 65535。

每个状态使用概率、矩的小数表示导出的精确有理数累计成本，避免搜索排序中的浮点舍入。启发式使用剩余质量乘以最小单位质量成本，目标从队列取出后才声明模型内最优。节点预算耗尽只报告 paused；SQLite 保存状态、代价、前驱、动作和完成进度，重复运行继续。

固定策略身份、统计、规则、数值上限、格数、目标及搜索代码均进入缓存标识。修改权重后重新搜索，不复用旧目标函数的结论。

前缀合同仍保留未知活动残区，因此即使报告 minimum-in-scope，也不等于证明随机执行可行、全局游戏最优或实测整局成本。输出明确区分这些结论。

验证命令：

```powershell
python -m unittest automation.tests.test_expected_routes -v
```
