# 全偶数预计算：最小化路线中出现过的最大数字

主入口 `automation/even_precompute.py`，默认六格独立工作盘面。
目标集合为 2～65534 的所有偶数，中间值上限默认 65535。
不进行十格搜索，不自动计算或执行随机定式。

这里的目标严格为：

`路线成本 = max(初始盘面的值，以及后续每一步出现的普通块值和 Group 总值)`。

例如普通 54 的 EDGE 前驱是两个位于 270～279 的相邻块，至少一个是普通块。
程序不能把“调用目标为 54 的定式”直接视为最大数字只有 54；必须记录其内部前驱。
Group 值计入最大数字，其成员仍按物理占格计算。

## 运行与续算

```powershell
python -m automation.even_precompute --directory F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six --cells 6 --max-target 65534 --max-value 65535 --node-limit 100000 --output F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six\index.json

# 相同命令继续；预算是所有目标共用，不是每个数字分别展开十万状态。
python -m automation.even_precompute --directory F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six --cells 6 --max-target 65534 --max-value 65535 --node-limit 100000 --output F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six\index.json

# 读取普通单格 54 的记录及已有路径。
python -m automation.even_precompute --directory F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six --cells 6 --max-value 65535 --lookup 54
```

`--node-limit 0` 持续运行，直到请求范围全部分类或声明的状态图被穷尽。
精确六格全盘面状态图很大，有限预算下的文件不会伪称已完成全表。
完整搜索前沿、路径前驱和已经证明的结果保存到 `even-precompute.sqlite3`。
`index.json` 给每个偶数提供一条记录；暂停后没有路径的目标明确标为 `unknown`。

## 在程序中复用

```python
from automation.even_precompute import EvenPrecomputer

planner = EvenPrecomputer(
    r"F:\TallnumData\tallnumai-templates\automation\runs\even-minimax-six",
    cells=6,
    max_value=65535,
    initial=(),  # 完整七格开局另用 cells=7, initial=(2,4)
)

summary = planner.precompute(max_target=65534, node_limit=100000)
ordinary54 = planner.lookup(54)
group270 = planner.lookup(270, kind="group", span=2)
```

输入池默认 Standard 的 2、4、8、6、10、15，也可以显式传入子集。
格数支持 1～7；六格表示独立工作空间，不自动包含或保护外部固定段。
目标上限仅影响请求与导出，不影响共享缓存身份，所以扩大目标范围可以复用已经搜索的状态。

## 两层预计算及证明范围

第一层是 `automation/peak_bounds.py` 的数值松弛动态规划：

1. 从原始数字和初始普通块出发。
2. 等值合并产生两倍数字。
3. EDGE 产生 `2×floor(A/10)`，另一块先按可以构造相应总值的 Group 处理。
4. 以最大中间值为标签反复松弛，直到固定点，保存每个数字的前驱配方。

它允许更宽松的 Group 构造并忽略物理空间，所以得到的是**必要数值下界，不是六格可执行路径**。
Group 出口不会与普通块出口混同。数值松弛都无法生成的目标，可以在声明上限内排除；
数值松弛能够生成的目标仍需第二层验证。

例如 54 的数值下界是 272，对应最后一个配方 `普通272 + Group270 → EDGE → 普通54`。
这不证明从空六格盘面能够以最大值 272 构造出全部前驱。

第二层是共享完整盘面状态的精确 minimax 标签搜索：

`D(后继) = min(D(后继), max(D(当前), 后继盘面中的最大值))`。

缓存保留有序块、Group 标记与物理占格、上一次输入及连续次数。
动作直接复用游戏规则，包含旋转必带投放、合法 Group、EDGE、自动合并、满盘终止和连续输入限制。
这层一次扩展可同时更新所有普通目标和所有 Group 出口的记录，不再对每个目标重复从头搜索。

真实合法路径达到第一层下界时，可以立即证明其最大值最小；
否则要等待完整前沿排除更低成本路径，才能标为已证明。
满盘状态没有后续动作，其输入历史会合并，路径仍保留；它们不会重复扩展。

结果状态：

- `minimum-peak-proven`：已有完整盘面路径，并证明声明图内的最大值最小。
- `candidate`：已有完整盘面路径，但更低最大值的可能性尚未排除。
- `unknown`：没有完整盘面路径；可能仅有数值下界和待验证的配方。
- `unreachable-in-scope`：数值必要条件排除，或完整状态图穷尽后仍没有路径。

`peakLowerBound` 与已找到路径的 `peak` 分开保存；未知值使用 null，不使用零占位。
改变空间、输入池、初始盘面、规则或中间上限后，使用独立缓存身份。
最优性和排除结论均只针对声明的上限，不扩展到允许更大数字的规则范围。

## 与定式统计的关系

输入数字是路径要求的随机出数，不是玩家可控投放，因此结构路径不等于低风险策略。
`stochasticPolicyVerified=false`；成功率和失败重开期望不在本次预计算中虚构。
本程序记录逐动作路径，尚不将它自动切分、认证为五格定式，因此 `fiveCellTemplateCounts` 保持 null。

操作数和投放数仅为路径记录。最小最大值并不保证同一最大值下操作最少，
所以 `shortestActionCountProven=false`。这与上层对定式风险、概率成本的比较分别处理。

## 验证

```powershell
python -m unittest automation.tests.test_even_precompute automation.tests.test_nonstandard_base -v
```

测试覆盖最大值目标优先于更短操作路径、初始数字和 Group 值计费、54 的 EDGE 前驱、
数值下界与可执行路径区分、全范围索引、缓存续算、范围扩展及中断恢复。
