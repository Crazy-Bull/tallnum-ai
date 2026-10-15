# 路线规划器 v2

独立的加权记忆化搜索入口，支持 Standard 七格、十格与自定义普通单格目标。
本版本提供结构规划、定式补算和真实规则模拟；结果保存在 `route-plan.json`，不会写入旧自动玩的 `plan.json`。

当前优先使用[七格可复用程序](SEVEN_ROUTES.zh-CN.md)，可作为 Python 接口调用，单独或批量搜索任意目标。
新任务默认七格，目标必须显式传入；十格仅在明确指定格数或继续已有十格请求时启用。

## 使用

在项目根目录执行。已有 Python 本地依赖沿用 `automation/.deps`；编译原生策略桥运行 `./automation/build.ps1`。

```powershell
# 七格，自定义目标；默认持续计算到当前候选范围完成
python -m automation route plan --directory automation/runs/seven-cache --cells 7 --target 192

# 给这次运行设置新增子问题预算，查看部分结果；零表示不限制
python -m automation route plan --directory automation/runs/seven-cache --cells 7 --target 192 --node-limit 10000

# 从保存的参数、搜索界限和分支进度继续
python -m automation route continue --directory automation/runs/seven-cache --node-limit 10000

# 为当前入选结构补算所有需要的五格定式及激进度变体，然后刷新规划结果
python -m automation route prepare --directory automation/runs/seven-cache

# 每条候选及独立留出验证默认各 10000 局
python -m automation route validate --directory automation/runs/seven-cache
```

`--max-value` 设置允许的中间数值上限，默认 `min(65535, max(48, 2×目标))`。
`--candidate-limit` 为 3～20，默认 20。`--rounds` 默认 5000，指定定式 VI 预算。
`--attempts` 默认 10000，可用于小规模试跑，但必须据实报告样本量。

`--leaf-targets` 可显式限制结构搜索调用的普通五格目标；这一限制会记录为最短性结论的适用范围。
以下例子只用 24、48、72、78 的普通块定式及结构连接产生普通块 14：

```powershell
python -m automation route plan --directory automation/runs/base7 --cells 7 --target 14 --max-value 80 --leaf-targets 24 48 72 78 --candidate-limit 3
```

默认搜索域包含上限内的全部偶数普通目标及 15；扩展补齐目标也可以是其他奇数的组合目标。
加入搜索域仅表示待评估，并不证明某个定式可达。

## 难度与风险

每次五格定式调用的初始权重为 `(T/48)³`。同一定式调用两次计两次权重，内部用整数 `T³` 比较。
一个五格 96 的权重是 8，两个为 16；一个五格 128 约为 18.963，因此后者更贵。

可用 `--weights weights.json` 覆盖具体定式的归一化权重：

```json
{
  "5:128:single": 20,
  "5:96:match": 9,
  "5:24:extend": 0.15
}
```

覆盖值必须为有限正数。使用十进制精确有理数比较，不用浮点值判断搜索界限。
修改权重后结构搜索重新计算；已有定式和原规则统计仍可复用。

搜索状态包含有序保护段、块类型、实际占格、固定段、目标、剩余加权预算及规则身份。
可扩展普通单格、与边界匹配的目标和 Group 扩展出口，并执行合法 Group 与 EDGE 连接。
EDGE 搜索允许先生成大数再降位。例如 72 与 78 相邻时能产生普通块 14。
Group 最多五个成员、至多一个已有组合块，组合块按原物理占格计算。

结构搜索使用增加成本界限的记忆化搜索，并用盘面总值的保守下界剪枝。
先完整处理最低结构成本界限，再继续收集最多 20 条不同定式构成的代表路线。
阶段内真实随机残余盘面属于未知活动区，模拟执行时保留，不清空或伪造。
连接不符合合同或策略不支持该入口时放弃路线，继续普通投放到真实结束，计入失败成本。

**结构最低成本只针对保护段合同图，不是游戏可达性或可执行最优性的证明。**
五格出口尚未补算时，路线仍是待验证结构。默认数值上限可能排除需要更大 EDGE 前驱的路线。
普通单格奇数仅可能为 15，基为 7、9 的目标 14、18、28、36 不因此被排除。
顶层 `globallyOptimal`、`executableMinimumProven` 均为 false；实际推荐依据整局模拟。

## 定式与代表点

每个定式补算激进度 `0、0.001、0.005、0.01、0.05`。非零激进度先生成偏好快速成功的策略，
最后保持策略不变，在零人工猝死风险下评估。每份 `templates/<身份>/variants.json` 汇总全部变体：

- `p`：成功概率。
- `c=u+v`：一次执行至成功或失败的期望投放数。
- `u、v`：成功、失败分支贡献的概率加权成本。
- `expectedTotalDrops=c/p`：从头重开的总期望投放数。
- 策略文件、指纹、PETSc 评估及缺失激进度。

存在不终止问题、未收敛或未通过出口核对的变体不进入有限期望规划。
定式允许上限内的全部奇数基，但发牌仍为原 Standard 规则，基列表不改变出数池。

阶段组合保留最多 20 个非支配 `(p,c)` 点：先保留最高成功率、最低成本和最低 `c/p`，
再按与已选成功率的最大距离补齐，尽量均匀覆盖成功率。完整保存 `u、v` 供串联。
二维淘汰和代表点压缩是启发式；不同残余盘面、出数池状态和额外收尾投放由整局模拟处理。

## 文件与恢复

- `route-request.json`：继续运行所需的参数。
- `routes.sqlite3`：结构状态、已完成子问题、部分分支游标、成本界限、依赖与组合统计。
- `route-plan.json`：结构路线、代表策略、加权难度、缺失定式、范围与进度。
- `templates/*/variants.json`：每个定式的所有 variant 统计与完成状态。
- `route-validation.json` / `route-validation-cache`：模拟成绩、推荐者及独立留出验证。

收到正常中断后保存分支进度，执行 `continue` 恢复。进程强行结束仍可复用已提交的子问题。
SQLite 按子问题提交，缓存身份包含规则源码、上限、允许目标域、权重和代表点参数。
定式指纹或统计更新会生成新的组合缓存身份；过期记录保留在库内，但不会被误用。
复用同一目录并改变目标时，匹配的结构子查询和定式可复用。

十格模拟初始出数池为 2、4、8，总值到 32、100、200 分别解锁 6、10、15。
验证按真实队列与重复限制运行，只给策略两个可见预览。成功成本截至首次达标。
最多 20 条代表路线默认各验证 10000 局，选中者另用独立种子验证 10000 局。
报告实际比较范围、95% 置信区间和排序不确定性；出现不匹配或未结束样本不发布有限总期望。

## 测试

```powershell
python -m unittest discover -s automation/tests -v
```

新增测试包含小图独立最短路对照、EDGE 非标准基、Group 占格、权重及续算、
变体文件与统计缓存更新，以及七格/十格共 200 个种子的逐动作游戏源码对照。
