# 可指定定式规格的概率表路线规划器

`automation.probability_route_planner` 将结构规划与定式库绑定分开。用户指定允许的 `格数:目标:出口` 契约，格数为 5–255，目标为 24–65535。出口为 `single`、`match` 或 `extend`。五格目标 64 的上限只属于已实测的十格 10240 低阶路线，不约束通用规划器。规划阶段只看所选契约与理想出口，找到路线后再核对待出数状态概率表；不使用固定动作表。

```powershell
# 默认使用概率表目录中全部合规定式
python -m automation.probability_route_planner 80 --cells 6 --catalog desktop/peak13-assets/probability-catalog.json --out automation/runs/example-80

# 只允许六格 40 生成，并绑定对应概率表
python -m automation.probability_route_planner 40 --cells 6 --allow-template 6:40:single --catalog desktop/peak13-assets/probability-catalog.json --out automation/runs/example-six

# 七格 96 无需定式库也可规划结构；缺表会明确报告
python -m automation.probability_route_planner 96 --cells 7 --allow-template 7:96:single --out automation/runs/example-seven

# 通用规划器也接受五格 80；若没有相应概率表，只输出结构路线
python -m automation.probability_route_planner 80 --cells 5 --allow-template 5:80:single --out automation/runs/example-five-80
```

`--allow-template` 可以重复指定。省略时使用目录中所有合规定式；指定后只搜索明确允许的规格。低格数定式与高格数定式同时可用时，规划器优先减少最高阶调用，再比较次数。被允许的干净 `single` 可在相同普通块旁通过游戏真实自动合并完成 `match` 结构连接，叶子仍计作所允许的 `single`，不暗中使用另一个 `match` 定式。

完整绑定时写入 `route.json` 和 `planning-report.json`，状态为 `candidate`，仍不代表已通过整局随机测试。结构路线若引用未计算的概率表，只写 `structural-route.json` 和报告，状态为 `missing-probability-tables`，报告列出全部缺口，不能作为可执行路线。搜索预算耗尽另报 `incomplete`。报告的 `scope.allowedTemplates` 记录实际搜索范围；最优性结论只在该范围内成立。

桌面应用的“概率表路线规划”页面提供同样的默认/自选切换，可以勾选目录现有规格，也可以输入尚无概率表的规格。所有目标均使用通用规划器及同一执行修复逻辑；只有新输出与已测路线、目录和执行源码指纹匹配时，才显示对应的百局成绩。
