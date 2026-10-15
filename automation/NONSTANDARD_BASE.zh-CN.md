# 非标准基最短合成路径程序

最新按“路线中出现过的最大数字最小”优化及共享全部偶数缓存的入口，见 [全偶数预计算](EVEN_PRECOMPUTE.zh-CN.md)。
下面这个旧入口仍用于按操作数或投放数搜索，两种优化标准不同。

入口是 `automation/nonstandard_base.py`，只依赖 Python 标准库。
它从给定盘面搜索原始游戏动作，不调用或假定已经存在待求基的定式。

## 可复用接口

```python
from automation.nonstandard_base import NonstandardSynthesizer

planner = NonstandardSynthesizer(
    directory="automation/runs/base-cache",
    cells=5,              # 当前模型的可用物理格数，支持 1～7
    initial=(),           # 空工作盘面；完整七格开局则用 cells=7, initial=(2,4)
    max_value=256,        # 包括 EDGE 前驱在内的中间值上限
    objective="actions", # actions：操作次数；drops：投放次数
)

def synthesize(base: int, exponent: int = 1) -> dict:
    # 每次最多展开 10000 个新状态。相同参数再次调用即可继续。
    return planner.search_base(base, exponent=exponent, node_limit=10000)

# 调用 synthesize(7,1) 求普通单格 14；synthesize(27,1) 求普通单格 54。
# 也可以直接用 planner.search(target, node_limit=10000) 指定实际目标。
```

“基 7”与“普通单格 7”不同：默认 `exponent=1`，目标是 14。
除 15 外，普通奇数单格按规则排除；Group 7 不等同于普通单格 7。
输入目标范围为 2～65535，初始盘面可含普通块或 `Block(value,span,True)` 形式的既有 Group。
程序不证明调用者提供的初始盘面自身能够从开局生成。

## 命令行

在项目根目录运行：

```powershell
python -m automation.nonstandard_base --base 7 --exponent 1 --cells 5 --max-value 256 --directory automation/runs/base-cache --node-limit 10000 --output automation/runs/base-cache/result.json

# 相同命令继续；或改变目标复用同一数据库。
python -m automation.nonstandard_base --base 27 --exponent 1 --cells 5 --max-value 512 --directory automation/runs/base-cache --node-limit 10000

# 明确提供七格开局盘面，按投放数求最短。
python -m automation.nonstandard_base --target 14 --cells 7 --initial 2 4 --max-value 256 --objective drops --directory automation/runs/base-cache
```

示例只是程序调用方式，不表示对应查询已经完成。
省略 `--output` 时，向标准输出返回一个 JSON 对象；搜索进度始终保存至 `synthesis.sqlite3`。
`node_limit=0` 不设状态展开预算，大目标的完整搜索可能占用较多时间和磁盘。

## 搜索包含什么

- 投放 Standard 原始数字：2、4、8、6、10、15，可通过 `inputs` 限制输入集合。
- `up`、`down` 旋转；每次旋转仍必须投放一个数字。
- 连续 2～5 块的合法 Group；最多存在一个 Group，不允许嵌套。
- EDGE；执行整个盘面的降位过程，再执行普通合并。
- 每次动作后的自动等值合并；合并结果是占一格的普通块。
- 物理占格、满盘终止和随机输入最多连续重复四次的限制。

缓存身份包含有序盘面、Group 值与占格、上一个随机输入及连续次数。
目标、格数、初始盘面、上限、输入池、优化指标和规则源码决定查询的独立命名空间。

程序使用 Dijkstra 标签搜索，缓存每个完整状态的最低成本和前驱动作。
`actions` 对所有动作计 1；`drops` 对投放和旋转计 1，对 Group、EDGE 计 0，同投放数时优先操作更少。
找到并取出目标状态后，才能声明该搜索范围内最短。

它不会仅找到一个满足 `floor(a/10)=floor(b/10)` 的数字对便宣称可达；
必须通过整个合法盘面路径实际构造前驱，并执行 EDGE。
默认中间值上限是 `min(65535,max(48,5×目标+9))`，覆盖直接 EDGE 的前驱区间。
如果前驱自身需要更大的数字才能生成，应提高上限后重新查询；不同上限不会冒用同一个最短性结论。

## 返回值的含义

- `status="found"`：返回 `path`，每一步含动作、所需输入、调用前后的完整有序盘面。
- `shortestInScopeProven=true`：该路径在声明的、可控输入的有限图中最短。
- `status="paused"`：本次预算用完或收到正常中断，不能解释为不可达。
- `status="no-path-in-scope"`、`unreachableInScopeProven=true`：已经穷尽声明的图；不能扩展为实际游戏全域不可达。
- `status="excluded-by-rules"`：普通奇数单格等规则性排除。
- `actions`、`drops`、`cost`：路径的操作数、投放数和选定优化指标。
- `search`：本次展开数、累计已存/已完成状态数和剩余前沿的成本下界。

这里的输入是**路径所要求出现的随机出数**，不是玩家能选择投放的数字。
程序证明的是存在性结构路径，不是面对未知随机数的策略。
结果固定保留 `stochasticReachabilityProven=false` 和 `successProbability=null`；
不会把某一条幸运出数序列的最短路径当作低风险定式。

同样，`cells=5` 描述一个独立五格工作盘面，不会自动处理外部固定段或边界合并。
接入上层七格路线前，应对完整入口、出口和随机残余盘面验证定式策略。
真实成功率、失败重开期望以及五格残局的加权排序仍由上层规划器处理，不与这里的动作距离混算。

## 验证

```powershell
python -m unittest automation.tests.test_nonstandard_base -v
```

测试用固定游戏引擎逐动作核对生成器，并用独立 BFS 比较小规模最短路径；
同时覆盖 EDGE 前驱构造、Group/普通块区分、物理格数、旋转投放、重复输入限制和中断续算。
