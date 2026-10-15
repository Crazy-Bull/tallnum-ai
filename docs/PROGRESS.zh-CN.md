# 路线规划与概率表进展

本次整合发布开发源码、回归测试、小型路线样本及精简统计，不包含预计算二进制、完整回放、浏览器配置和实机控制文件。此前仓库中的README修改已保留。

## 已整合功能

- 通用规划器接受1–255格容量、2–65535整数目标；允许规格可指定5–255格、目标24–65535及single、match、extend出口。结构规划与概率表绑定分离，缺表明确报告，不自动启动昂贵补算。
- 动态规划先降低最高阶五格定式，再减少其主路线次数；执行修复使用可用空格、严格生产定式、真实开局连接、回退和EDGE残留轮转。回退的额外次数与主路线分别统计。
- 桌面界面提供通用规划、允许定式选择、整数规划和按两个可见待出数展示的36状态成功概率。新定式动作来自概率表，历史固定策略表结果不作为新功能验收。
- 保留现有Chrome连接、正常键鼠输入、操作确认及虚拟半值底层续玩代码。实机续玩只在规划器内部投影底层数值，不改写真实存档、发牌或RNG。

## 三个目标的完成记录

数据在[验证目录](validation/route-execution-2026-10/manifest.json)：每个目标包含原始路线、规划报告、验收结果、配置、原引擎核对报告及100局精简记录。

- 8192：v6路线，308阶段，最高五格60，主路线14次；94/100成功，无未完成局，原引擎核对794191个动作。
- 10240：v7复测，426阶段，最高五格64，主路线14次；87/100成功，无未完成局，原引擎核对2041549个动作。
- 12288：v7路线，448阶段，最高五格80主路线10次，五格64主路线11次；91/100成功，无未完成局，原引擎核对3185745个动作。

三组测试使用相同100个种子、Standard发牌、两个可见待出数、每局100000动作预算、概率表决策、回退开启、无强制发牌。完整回放的原引擎发牌与状态核对已在本机完成；仓库仅提供精简统计及原报告的SHA-256，不能用精简记录替代完整动作回放重新核对。

Chrome实机已在一局中合成普通12288（19842次投放、30610个动作）。这是单局运行记录，不并入上述百局统计；后续虚拟6144续玩仍属独立运行，未登记新胜率。

模型概率、有限样本成绩、候选路线和有范围的最优性结论分别处理。达到85/100不意味着总体胜率已被统计证明至少85%；未匹配路线、目录和执行源码指纹时不能沿用这些成绩。

## 概率表与目录缺口

`desktop/peak13-assets/probability-catalog.json`保留已测目录的原始身份和数据位置，包含此前计算的五格80、128变体元数据。目录中出现定式不代表Git仓库包含其二进制概率表；其中的本机路径在其他机器上通常不存在。实际计算或模拟需要生成或导入自己的表及匹配目录，并继续执行SHA-256与规则兼容性校验，不能通过修改元数据绕过校验。

`probability-validations.json`及`measured-route.json`等资产保留各自原始版本，不能将较早的测量路线当作当前通用规划器输出。界面仅对匹配身份显示对应成绩。当前三目标路线以本说明所链接的验证目录为准。

无表结构规划示例（从仓库根目录运行）：

```powershell
python -m automation.probability_route_planner 96 --cells 7 --allow-template 7:96:single --out automation/runs/example-seven
```

有本地概率表目录时：

```powershell
python -m automation.probability_route_planner 10240 --cells 10 --catalog path/to/local-catalog.json --out automation/runs/my-10240
```

这会执行当前通用规划器；允许列表和搜索预算可能产生不同候选，不能直接套用87/100。大目标搜索或补表可能耗时较长。

## 发布检查

执行核心源码和路线按原始字节保存，以使已测SHA-256在Git签出后仍可复核。8192的v6执行绑定函数早于当前v7，原始源码单独保存在该目标的`sources/`；配置所列的其他源码与当前执行核心一致，不能将该历史绑定源码冒充当前版本。执行器回归使用`automation/tests/fixtures/generic-plans/`的小型路线样本；大型原始运行目录仍被忽略。

```powershell
python tools/verify-release-evidence.py
python -m unittest automation.tests.test_probability_route_planner automation.tests.test_probability_route_execution automation.tests.test_connection_alignment automation.tests.test_boundary_rewind automation.tests.test_opening128_40 automation.tests.test_entry_recovery -v
node desktop/scripts/test-calculator-rules.cjs
npm --prefix desktop run build
```

本次发布目录实际通过61项上述定向回归，以及47项执行、续局、标签页与输入恢复等回归，共108项；另通过计算器规则校验和Electron源码构建。沙箱默认临时目录拒绝原子替换时，将测试临时目录设在仓库的`automation/runs/`后重跑通过。构建复用了开发目录已安装的依赖；未重新安装工具链或打包安装程序。

这些检查不启动浏览器或大型枚举。其余历史/原生/实机测试可能依赖未随仓库分发的数据与程序；没有将全套测试、原生完整重编译或安装包重打包报告为本次通过。
