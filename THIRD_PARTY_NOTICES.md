# 来源与许可说明

## 项目源码

早期 C++ 状态枚举和值迭代源码根据原项目记录，从 ChatGPT 分享聊天中的代码与修改还原：
https://chatgpt.com/share/6ab426fb-ad14-83ea-b92c-b67ba05895de

这是一条来源记录，不构成第三方代码的授权证明。发布副本不包含聊天原文、分享页抓取文件或聊天附件。项目尚未选择统一开源许可证；选择许可证前需确认所含代码的权利与可再分发条件。

## Tallnum 游戏规则参考

`automation/vendor/tallnum.mjs` 为原项目固定版本的 JavaScript 游戏规则参考，用于模拟一致性检查。

- 原始来源：https://pku2048.cn/game/tallnum.js?v=20260922-tallnum-small-all-unlocked
- 原项目记录的 SHA-256：`67601620b932b4389ee266d88d1104c0b896d6474633b9fb8c22eeb80697a271`
- 此次整理保留文件内容，本机校验的 SHA-256 与上述记录一致。
- 文件未附单独许可证，原项目未提供可确认的再分发授权。公开发布前需确认该文件许可，项目许可证不能替代这一确认。

## 构建与运行依赖

Electron、React、Vite、TypeScript、electron-builder、Python、NumPy、SciPy、Playwright、websocket-client、MSYS2、GCC、PETSc、ijson 等依赖由各自项目维护。版本约束见 `desktop/package.json`、`desktop/package-lock.json` 和 `automation/requirements.txt`。

源码发布不复制工具链、依赖安装目录或第三方运行二进制。构建安装包会引入 Electron、Chromium 和原生 DLL；分发安装包应保留组件对应的许可、版权及其他分发要求。本文件只记录来源，不替代各依赖的正式许可文件。
