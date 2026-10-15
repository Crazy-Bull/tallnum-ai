# 带格数、入口盘面及 buffer 的二叉搜索

`binary_routes.py` 是可复用的命令行程序，按每次五格定式的已计算 `(u+v)/p` 累加比较路线。大格数定式通过二叉连接构造，连接动作不另算第三个定式。`single`、`match`、`extend` 均带可用格数及实际目标；`extend` 额外带入口 A、B（A−B 为补齐量）。`buffer` 用十进制前缀描述 Group 范围，例如 27 表示 270～279，并保存现有普通成员及相邻块。

普通匹配拆分先做较大目标，补齐量不得超过先做的目标。buffer 的整个 Group 可以大于相邻普通块；32 旁构造 Group(24,10)=34 是合法例子。Group 的成员必须为普通块，不能嵌套，最多五个成员。已有边界可以复用，例如 `[48,16]` 上的 `n-32-extend` 拆成 `n-16-match` 与 `n-16-extend`，后一步仍有 n 格。

缓存键包含完整有序入口、物理占格、Group 标记、接口、目标及 EDGE 深度。规则文件、权重快照、数值上限或搜索模式变化会切换缓存命名空间。SQLite 每 200 个缓存项提交一次，正常退出再提交最后一批。再次运行相同命令会复用已完成子问题；未完成分支会重新展开。

## 运行

在项目根目录运行：

```powershell
python -m automation.binary_routes 6912 --cells 10 --weights automation/runs/binary6912/weights/expected-weights.json --directory F:\TallnumData\tallnumai-templates\automation\runs\binary6912\final-search --maximum 13824 --edge-depth 5 --node-limit 1000000
```

改目标和 `--cells 7` 即可搜索其他目标。数值上限必须覆盖目标，最高 65535。`--node-limit 0` 表示不限节点预算。程序先生成有界启发式候选，再展开记忆化成本搜索；节点预算分别用于这两个阶段。种子只用于提供上界，不提供最低成本证明。

默认 `--split-mode guided` 在普通分量中枚举标准基目标，并加入区间端点及中点的偶数；`--split-mode all` 枚举区间中所有偶数及 15。两种模式都会递归构造非标准基，并检查空间与入口，但五格叶子仅使用标准基 1、3、5、15 的已测策略。目标超过五格定式库的覆盖范围时，继续拆分；未测的五格接口不会获得零成本。

结果保存在 `binary-plan.json`，包含完整二叉树、各接口调用数量、实际导出树的加权成本及最优性标记。`ideal-connection-trace.json` 逐步保存理想成功出口上的普通合并、Group 和 EDGE，并核对最终目标及物理占格。共享子问题更新后，导出时重新计价，避免旧父节点上界与实际路线成本不一致。

## 十格 6912 的验证

```powershell
python -m automation.binary_witness F:\TallnumData\tallnumai-templates\automation\runs\binary6912\final-search\binary-plan.json --output automation/runs/binary6912/controlled-witness.json
node automation/binary_witness_check.mjs automation/runs/binary6912/controlled-witness.json
```

见证程序从真实开局 `[2,4]` 开始，先构造 128，再构造 Group(80,40)=120，EDGE 得到 24，匹配 24 得到 48。这段开局合法解锁 6、10、15，替换理想路线第一次达到普通 48 之前的阶段。随后为每个叶子寻找保持入口的条件投放序列，检查完整十格棋盘、四步隐藏队列的生成时点、出数池和连续同值限制。原版 JavaScript 引擎独立重放每一个动作并核对盘面、解锁和占格。

若路线不含普通 48，但包含普通 10 检查点，见证程序改用普通 10 开局：构造 256 与 Group(240,12,2)=254，EDGE 得到 50；再构造 Group(40,12)=52，EDGE 得到 10。这段引导使用 69 次条件投放，同样永久解锁整个出数池，并替换首次普通 10 之前的理想阶段。

见证程序当前适用于上述普通 48 或 10 检查点可作为开局接点的十格路线。它验证有这样一条合法出数路径；没有找到同样路径的 RNG seed，也没有证明这些投放来自选定的随机策略。实际开局的随机策略期望成本尚未测量。

较大的定式在 PETSc 认证阶段内存不足时，可运行 `python -m automation.certify --directory 定式目录 --solver-restart 20` 继续。较小的 restart 降低向量存储量，保留原有收敛容差及出口概率复核；已认证的接口和已完成阶段会复用。

## 成本和结论的范围

定式权重来自一个无激进惩罚的固定变体，在 `iid-six-original-table`、`uniform-first-36` 入口模型下计算，并经过出口概率复核。和式假设每个定式能够独立重试，不计整个棋盘失败后重开，也不计连接动作的投放数（Group/EDGE 不投放）。实际入口、四步隐藏队列和早期解锁可能改变定式表现；单次失败也未必能保留原盘面独立重试。因此该和式用于排序近似，不能当作十格实测期望投放数。

激进度指构造策略时的参数，而不是评估时的人为猝死概率。非零激进度策略在原规则（猝死概率为零）下评估后，仍属于原来的非零变体。权重生成器读取 PETSc 的 `input_aggressiveness` 核对旧目录的策略来源，只接受与指定激进度完全一致的版本；缺少所需变体时报告缺失，不自动改用非零版本。2026-10-02 修复前的 10240 权重及搜索目录含误标的 128 变体，已被 `zero-risk-weights` 和 `zero-risk-search` 替代。

`globallyOptimal` 保持 false。只有当前声明的接口、数值边界、有限 EDGE 深度与候选分量域内所有相关低成本分支完成，`minimumAdditiveWeightProvenInScope` 才能为 true。达到节点预算时报告当前最低已知候选；缺失接口、未测 buffer 原语、主动旋转、随机残留盘面等都不属于已完成证明。条件出数见证也不会将随机策略验证标记改为 true。

测试：

```powershell
python -m unittest automation.tests.test_binary_routes automation.tests.test_expected_routes automation.tests.test_route_search automation.tests.test_nonstandard_base automation.tests.test_core
```
