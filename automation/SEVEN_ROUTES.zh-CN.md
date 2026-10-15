# 七格任意目标搜索程序

程序入口是 `automation/seven_routes.py`。它提供可导入的 Python 接口和命令行接口，
固定使用 Standard 七格，目标由调用者传入，没有固定的 768 目标，也不读取十格任务参数。
结构搜索只依赖 Python 3.11 标准库；定式补算、原生策略执行和模拟验证是独立阶段。

## 在其他程序中复用

```python
from automation.seven_routes import SevenCellPlanner, search_seven

# 可长期复用同一个对象；不同查询共用磁盘缓存和定式目录。
planner = SevenCellPlanner(
    cache_directory=r"D:\tallnumai\automation\runs\seven-cache",
    candidate_limit=20,
)

def plan_target(target: int) -> dict:
    # 每次最多计算 10000 个新子问题。暂停后以相同参数再次调用即可续算。
    return planner.search(target, node_limit=10000)

def plan_targets(targets: list[int]) -> dict[int, dict]:
    return planner.search_many(targets, node_limit=10000)

# 单次查询也可以直接调用便捷函数：
def plan_once(target: int, cache_directory: str) -> dict:
    return search_seven(target, cache_directory, node_limit=10000)
```

运行时当前工作目录应为项目根目录，或将项目根目录加入 Python 导入路径。
`search_many` 按输入顺序逐个查询，重复目标只查询一次；无效目标在开始批量查询前统一拒绝。

`catalog=None` 时，每次查询重新读取缓存目录的 `catalog.json`，因此补算后的新 variant 可以立即参与组合。
也可以通过 `catalog={"policies": [...]}` 传入已有策略统计，接口和认证要求与项目策略清单一致。

默认不打印进度。如需在界面显示进度，可传入 `progress=回调函数`，回调收到目标、格数、
本次新增子问题数和缓存命中次数。函数返回字典，不自动导出某个目标的结果文件。

## 命令行

```powershell
# 单个目标，返回 JSON；SQLite 自动保存搜索进度。
python -m automation.seven_routes --target 192 --directory automation/runs/seven-cache --node-limit 10000

# 用相同命令继续未完成查询。
python -m automation.seven_routes --target 192 --directory automation/runs/seven-cache --node-limit 10000

# 批量查询，显式设置输出文件。
python -m automation.seven_routes --target 96 128 192 --directory automation/runs/seven-cache --node-limit 10000 --output automation/runs/seven-cache/export.json
```

这些命令是调用示例，不表示已经完成对应目标的搜索或模拟。
默认 `node_limit=0`，表示不设新增子问题预算，持续计算到当前候选范围完成。

可配置参数：

- `max_value` / `--max-value`：中间数字上限，默认 `min(65535, max(48, 2×目标))`。
- `weights` / `--weights`：具体定式权重覆盖；CLI 读取 JSON 文件。
- `candidate_limit` / `--candidate-limit`：最多 3～20 个代表，默认 20。
- `leaf_targets` / `--leaf-targets`：显式限制普通五格目标域，限制会记录在搜索范围中。
- `node_limit` / `--node-limit`：本次每个目标最多计算的新子问题数。
- `--output`：可选 JSON 导出；未指定时只向标准输出返回一个 JSON 对象。

批量目标共享显式 `max_value` 时，上限必须覆盖全部目标。规则、上限和目标域相同的定式可以复用；
搜索字典中与目标相关的判断仍分别缓存，不跨目标冒用最短性结论。

## 搜索语义

输入是 `2～65535` 的整数，顶层成功条件是普通单格目标。
普通单格奇数只能为 15；其他奇数目标返回明确的规则排除原因。
基为 7、9 等的偶数目标不会因此被排除，例如 14、18、28、36。

程序搜索等值合并、Group 补齐、不同生成顺序及 EDGE 降位路径。
例如七格内可构造两个普通块 72、78，再 EDGE 得到普通块 14；
90、96 则能通过 EDGE 得到普通块 18。构造前驱本身仍需要相应定式或子路线。
任何五格定式调用前，已有保护段的物理占格必须给它留下至少五格工作区。
Group 按实际占格计算，不能把组合块当作只占一格的普通块。

结构难度为所有五格调用的 `(目标/48)³` 之和，重复调用重复计费；
一个 128 的权重大于两个 96。权重覆盖格式示例：

```json
{"5:128:single": 20, "5:96:match": 9}
```

结构搜索采用加权界限递增的记忆化搜索。完成最低结构成本的检查后，继续保留最多 20 条不同定式构成的路线。
内部使用显式搜索栈，不受 Python 递归深度限制；较大的目标仍可能需要多次预算续算。
候选排序优先比较由高到低排列的残局目标序列，再比较三次方成本。例如，即使十次 128 的三次方总成本
大于一次 160，也优先保留避开 160 的候选。三次方最低成本端点仍单独保留，以保证对应的最低成本检查有效。
这是一项保守的结构偏好，不是对真实成功率的预测。

完整成本界限搜索前，还运行最多 2000 个新子问题的记忆化候选搜索，尝试等值拆分和“较小块＋差额补齐”。
例如保护段 `[320,256]` 可以调用 64 的 extend 定式得到 640，而不必直接执行 160 或 320 定式。
补齐候选包括约三分之二处的非标准基，不限于二次幂。每一步均由完整搜索的合法动作生成器核对。
这项候选搜索可能提前找到路线，但不证明最优；`search.discovery` 单独记录其预算和完成情况。
已提供 variant 统计时，组合并保留最多 20 个非支配 `(成功率, 单次期望投放数)` 点，尽量覆盖不同成功率。
实际期望成本仍使用 `p、u、v` 正确累计，并按包含重开的 `(u+v)/p` 初步排序。

统计缓存包括已完成的路线前缀。不同目标或权重下出现相同前缀，可以复用同一组策略统计；
权重改变只重新计算结构难度，不复用旧难度数值。策略指纹或统计变更会更新相关缓存身份。

## 返回值和未完成状态

返回字典包括 `cells`、`target`、`structures`、`routes`、`requirements`、`missing`、`search` 和 `status`。

- `structures`：结构路线、定式调用次数、加权难度及连接步骤。
- `routes`：已经具备合格定式统计的策略组合，每条保留 `p、u、v、c` 和重开期望。
- `requirements` / `missing`：依赖的五格定式以及尚无可用策略的依赖。
- `search`：成本界限、搜索进度、缓存命中和完成范围。
- `status=paused`：预算用完或正常中断；再次调用可继续，不能解释为不可达。
- `status=missing-policies`：已有候选结构，需要提供或补算定式。
- `status=ready-for-simulation`：有可执行候选可供进一步验证，尚未代表实测推荐。
- `status=no-route-in-scope`：规则排除或声明的搜索域中没有结构路线，查看 `search.reason` 和配置。

结构候选增加 `highestEndgameTarget` 和 `difficultyProfile`。`lowestKnownStructuralUnits` 是已找到的
最低三次方成本，`minimumStructuralUnits` 仅在完整成本界限检查确认后填写，两者不能混淆。
`candidateRankingProvenOptimal=false` 表示尚未证明高阶优先排序的全域最优性。

缺少五格定式时，不能把结构路径当作该非标准基已被证明可达。
`structuralMinimumProven` 仅表示保护段合同图中的最低加权结构成本；
`executableMinimumProven` 和 `globallyOptimal` 始终为 false。
阶段的随机残余盘面在实际验证时保留并核对，结构估计不冒充实战成功率。

若之后需要补算或模拟，可以显式保存函数返回字典为数据目录的 `route-plan.json`，并在补算前建立相同参数的七格请求：

```powershell
python -m automation route plan --cells 7 --target 192 --directory automation/runs/seven-cache --node-limit 10000
python -m automation route prepare --cells 7 --target 192 --directory automation/runs/seven-cache
python -m automation route validate --cells 7 --target 192 --directory automation/runs/seven-cache
```

补算/验证细节见 [路线规划器 v2](ROUTE_PLANNER.zh-CN.md)。它们由用户另行调用，七格搜索接口不会自动启动。

## 验证程序

```powershell
python -m unittest automation.tests.test_seven_routes automation.tests.test_core -v
```

七格专用测试覆盖任意目标输入、小图独立最短路对照、7/9 非标准基的 EDGE 路线、
空间约束、预算续算、批量查询、十格配置隔离、新 variant 读取、权重修改和 JSON 接口。
