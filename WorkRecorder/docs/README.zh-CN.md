# WorkRecorder 文档总览

[English](README.md) | [简体中文](README.zh-CN.md)

WorkRecorder 当前以录制会话为产品入口：选择录制区域、确认开始、执行操作、完成录制，然后在录制中心回看和导出。默认快捷键为 `⌃⌥⌘R`。

录制中的关键帧图像作为操作证据保存。安装和当前使用流程以中英文 README 为准。

## 当前入口与实现

| 入口 | 内容 |
| --- | --- |
| [WorkRecorder 中文说明](../README.zh-CN.md) | 录制流程、平台范围、安装、权限、回看与导出 |
| [macOS 开发说明](../apps/macos_capture/README.md) | 原生录制 App 的启动与验证 |
| [Linux AT-SPI 采集](../apps/linux_capture/README.zh-CN.md) | 单桌面服务、SSH 启动、证据格式与两种录制模式 |
| [浏览器 provider](../apps/browser_extension/README.md) | 网页证据采集接口与开发说明 |
| [录制模块](../packages/active_capture/) | 会话、操作、关键帧、时间线和导出实现 |

## 设计与历史架构参考

以下文档保留设计过程及早期上下文事件架构，其中部分包含旧版截图入口、旧 UI 或尚未实现的规划。它们不代表当前用户流程，具体行为以当前代码和项目 README 为准。

- [录制功能 UI/UX 设计](design/RECORDING_UI_UX_CN.md)
- [大屏录制复盘工作区设计](design/RECORDING_LARGE_SCREEN_REVIEW_CN.md)
- [Active Context Capture 设计](design/USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md)
- [总体技术简介](TECHNICAL_OVERVIEW_CN.md)
- [系统证据与 System Appshot](architecture/SYSTEM_APPSHOT_CN.md)
- [早期 Chrome 流程案例](USER_GUIDE_CHROME_CASE_STUDY_CN.md)
- [六阶段架构：触发](01_TRIGGER_CN.md)、[采集](02_COLLECTION_CN.md)、[事件入库](03_EVENT_LEDGER_CN.md)、[增强与去噪](04_ENRICHMENT_CN.md)、[索引与披露](05_INDEX_DISCLOSURE_CN.md)、[Agent 使用](06_AGENT_USAGE_CN.md)
- [RFC 与实现对齐](RFC_CODE_ALIGNMENT_CN.md)
- [Agent skill](../apps/skill/SKILL.md) 与 [CLI 参考](../apps/skill/references/cli.md)

## 文档维护

当前产品说明围绕录制会话、操作证据、回看和导出组织。更新时应区分已实现能力、可选采集项和待接入部分，并同步维护中英文 README。各目录的 `README.md` 统一使用英文，中文说明放在 `README.zh-CN.md`，两者提供语言切换链接。
