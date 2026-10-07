# 构建与运行验证 / Build and runtime verification

验证日期：2026-10-07。验证使用精简后的发布源码，测试脚本、过程日志和测试数据保存在仓库外。

Verified on 2026-10-07 using the trimmed release source. Test harnesses, logs and generated test data are kept outside the repository.

## 环境 / Environment

- Windows x64；Node.js 18.17.1、npm 9.6.7、Python 3.11.4。
- 本机 MSYS2 UCRT64 GCC 与 sequential double precision PETSc。
- 新建独立 Python 虚拟环境并安装 requirements：NumPy 2.4.6、SciPy 1.17.1、Playwright 1.63.0、websocket-client 1.9.2、ijson 3.5.1。
- Fresh Python virtual environment installed from the declared requirements. Desktop dependencies were independently installed with `npm ci`, including the Electron runtime.

## 实际通过的检查 / Passed checks

1. **原生构建 / Native build**：统一入口成功编译原版与激进度求解器、五格/六格策略桥、PETSc 图评估器，以及动态期望值程序，并复制运行所需 DLL。
2. **桌面构建与打包 / Desktop build and packaging**：`npm run typecheck` 和 `npm run dist:win` 通过，成功生成完整 `win-unpacked` 目录与 Windows NSIS 安装包。
3. **独立 Python 环境 / Clean Python environment**：所有保留的运行模块导入成功，README 列出的高级 CLI 帮助命令均可运行。
4. **README 命令行示例 / Documented native quick start**：3 格、目标 16、最大数字 32、目标占格上限 1、激进度 0。实际生成 7,092 个状态，完成 20 轮 VI 与 PETSc 评估；PETSc 报告收敛，初始平均策略值约 `0.1406427664`，实际残差约 `1.11e-10`。
5. **PETSc 小规模集成 / PETSc integration micro-fixtures**：GMRES、DGMRES、ILU、精确概率对照、策略读写、闭合循环、配置及指纹拒绝、未收敛处理通过。
6. **打包应用实际运行 / Packaged application runtime**：使用隔离用户资料和隐藏窗口启动刚构建的应用。界面及 preload IPC 正常；创建 3 格、目标 16、最大数字 32、激进度 0.05 的任务，生成 6,264 个状态，完成 VI 与三次 PETSc 阶段，最终状态为 completed、无任务错误。随后通过自动玩界面调用 Python 后端，正确生成 768 拆解及 12 个缺失策略条目，无页面异常。
7. **打包资源与新版规划 / Packaged resources and v2 planning**：检查托盘图标、游戏规则 `.mjs`、动态工作器、原生核心与 DLL 已进入包；从包内 Python 模块运行七格目标 24 的新版规划，正常返回待补算定式结果。
8. **发布文件检查 / Source release audit**：核对本地文档链接、C++ 相对引用、敏感文件形状、本机绝对路径和超大文件；源文件清单用于打包及提交前核对，未将测试脚本、依赖或运行数据纳入提交。

## 修复的发布问题 / Packaging fixes

- 补齐托盘图标，修正开发模式图标路径。
- 将 Python 运行所需的 `.mjs`、固定游戏规则与动态查询工作器加入桌面资源配置。
- requirements 补充实际被运行功能使用的 `ijson`。
- 桌面 Python 后端支持 `TALLNUM_PYTHON`，以便明确选择虚拟环境。
- 原生构建统一支持外部 `TALLNUM_MSYS_ROOT`，并使用可写的临时目录。

## 验证边界 / Limits

本次执行了构建、打包与程序实际运行验证，没有自动安装到系统、操作用户现有游戏或执行完整大目标策略计算。安装包生成通过，运行检查使用同次构建的目录版。真实网页版本和实际大目标策略需按 README 的 prepare、validate 流程另外验证；小规模通过不能证明所有目标收敛或全局最优。

The installer was built successfully; runtime checks used the unpacked app from that build. No system installation, manipulation of an existing user game, or full large-target computation was performed. Prepare and validate actual policies before browser play. Passing small cases does not prove convergence for every target or global optimality.
