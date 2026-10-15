# Tallnum 激进度计算核心（独立副本）

原版源码及已安装桌面程序保持不变。本目录仅提供新的 C++ 计算核心，尚未接入桌面界面。

## 规则

固定发牌为 2、4、6、8、10、15，平均出数大小为 7.5。
猝死率 p = 激进度 × 7.5 / 目标数字。
默认激进度为 0；要求有限且位于 [0, 目标数字 / 7.5]。
每次未成功的出数承担一次猝死风险；成功步免除风险，免费操作不承担风险。
立即成功动作值为 1；非终止动作值为 (1-p) × 六个后继值的平均值。
VI、PETSc 贪心动作选择、矩阵、右端项、对角预条件以及真实残差均使用此规则。
无需实际随机抽取猝死事件，求解器直接计算其概率影响。

若原本成功需要 N 次出数，该成功路径的权重为 (1-p)^(N-1)（成功步不计）。
这一目标倾向于更快成功，但不直接指定或保证某个平均步数；输出成功率包含猝死风险。

## 命令行示例（PowerShell，在本目录执行）

生成转移表的参数和原版完全一致；也可使用已有的匹配 v4 转移表。

```powershell
.\bin\tallnum_vi.exe table.bin 5000 1e-9 values.bin --aggressiveness 0.1
.\bin\tallnum_policy_eval.exe -tallnum_table table.bin -tallnum_values values.bin -tallnum_aggressiveness 0.1 -tallnum_save_policy policy.bin -tallnum_save_values evaluated.bin -ksp_type dgmres -ksp_rtol 1e-10 -ksp_max_it 2000
```

上例目标若为 80，猝死率为 0.009375，即每个未成功出数步 0.9375%。
每次 PETSc 调用仍是选择并评估一次策略；继续策略改进时使用上一轮完整值函数。

## 文件兼容性

转移表格式仍为 TALLTRN4。新值函数、策略和检查点采用独立文件标识并保存激进度；
读取时拒绝不同激进度及旧格式结果。激进度为 0 时，概率递推与原版相同，文件格式仍为新格式。
VI 值文件沿用原版状态顺序约定，必须与生成它的转移表配套。
结果 JSON 新增 aggressiveness、sudden_death_probability、success_step_exempt。

## 编译

运行 build-native.ps1。默认使用上级目录 .tools/msys64 内的 UCRT64/PETSc 工具链，
也可通过 TALLNUM_MSYS_ROOT 指定 MSYS2 根目录。bin 包含所需 DLL，可直接运行。
本次仅编译，没有新增或运行测试，没有重跑计算任务。
