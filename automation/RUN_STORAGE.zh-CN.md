# 运行数据存储位置

大型运行数据已迁移到 `F:\TallnumData\tallnumai-templates`，以释放 D 盘空间。当前主机的历史路径仍通过 D 盘目录联接映射到对应 F 盘目录，所以旧回放、目录清单和运行参数中的 `D:\tallnumai\...` 路径仍然有效。

已迁移的数据包括：

- `binary10240\min24` 下三个严格策略目录的 `policies`、缓冲救援的 `policies`，以及 `pending-search-all-policies-001` 的 `inputs` 和 `pending`。
- `binary6912\final-search`、`binary6912\search` 和整个 `even-minimax-six` 搜索目录。
- `missing-expected`、`match-edge-guard` 下的认证、生成及激进策略数据目录。
- `binary10240\minimum64` 下的随机测试策略库、证明数据库和 `zero-risk-search`，以及两组六格实验的待定概率缓存和验证记录。
- 发布验证的 `build-products`，以及桌面应用 `desktop\release-0.3.0` 安装包目录。

运行新的二叉路线搜索、全偶数预计算时，优先使用相应操作文档里的 F 盘规范路径。历史代码或结果文件如果仍使用 D 盘路径，无需批量改写：目录联接会把读写转到 F 盘，批量改写带有校验摘要的旧结果还可能破坏来源校验。

迁移清单和逐文件校验结果保存在 `maintenance\large-run-data-migration.json`；迁移脚本为 `maintenance\move_large_run_data.py`。

发布验证用的虚拟环境保留在 D 盘；它包含数千个小文件，迁移收益有限。已清理迁移过程中在 F 盘生成的不完整副本，D 盘原环境未改动。
