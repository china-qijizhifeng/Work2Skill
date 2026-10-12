# 阶段 1：触发

> 导航：[返回文档总览](README.md) · 上一篇：[总体技术简介](TECHNICAL_OVERVIEW_CN.md) · 下一篇：[阶段 2：采集](02_COLLECTION_CN.md)

触发阶段只回答一个问题：

> 用户刚刚主动指出了屏幕上的哪一块上下文？

这一阶段离用户最近，所以设计原则是：快、轻、稳定、少判断。它不负责最终事件类型，不读 App 内部数据，也不决定 Agent 以后能看到什么。

## 用户看到什么

用户按 macOS 全局快捷键后，屏幕上出现选区。用户拖出一个 bbox，必要时在 Light Sheet 里补一句 note。

例如在 Chrome 报价页上，用户框住一张表并输入：

```text
用于 ACME 续约风险分析
```

这句 note 很重要。它不是普通备注，而是用户当时的意图信号。后面搜索、摘要卡、审计里都应该能看到它。

## 触发阶段提交什么

macOS shell 提交给 daemon 的不是最终 event，而是 capture attempt。可以把它理解成“用户刚刚发起了一次采集请求”。

它包含：

- 触发时间。
- 用户框选的屏幕坐标和 coordinate space。
- staged screenshot 引用。
- 当前窗口 hints，例如 app name、pid、window id、title。
- workspace、actor、trigger source。
- 用户 note。
- 客户端版本和 basic diagnostics。

这些信息足够 daemon 做后续判断，但不会提前把 App 数据塞进 shell。

## 为什么 macOS shell 要保持很薄

Swift shell 离用户操作链路最近。它一旦变复杂，就会出现几个问题：

- 快捷键响应变慢。
- 系统权限、App 权限、DOM 权限混在一起。
- 不同 App 的采集逻辑塞进桌面端，后续难以维护。
- Agent 权限判断分散，审计口径不一致。

所以 shell 只做四件事：

1. 监听快捷键。
2. 展示选区 overlay。
3. 调系统截图能力生成 PNG。
4. 把 capture attempt 发给 daemon。

它明确不做：

- 不判断最终 event type。
- 不读 DOM。
- 不读取 a11y tree。
- 不生成 `selection_text` 或 `canonical_text`。
- 不写数据库。
- 不决定 Agent 能看什么。

## 失败怎么处理

触发阶段失败不应该污染事件库。

例如：

- 用户取消选区。
- 截图权限没有授权。
- daemon 不在线。
- token 校验失败。
- 网络超时。

这些情况可以在本地 UI 里提示，也可以写 diagnostic log，但不会创建 `ContextEvent`，更不会进入搜索索引。

## note 为什么在第一步进入系统

用户 note 是非常强的上下文，因为它描述了“用户为什么截这块”。对 Agent 来说，note 往往比页面标题更接近真实任务。

因此 note 会在 capture attempt 阶段进入系统，并在后续：

- 作为 safe metadata 入库。
- 进入 indexable projection。
- 出现在默认摘要卡里。
- 进入 agent run snapshot。
- 被 audit 追踪。

这也解释了为什么 note 不应该只是前端 UI 的临时字段。

## 设计亮点

- **入口统一**：无论未来来自快捷键、浏览器按钮、App 菜单，最终都提交 capture attempt。
- **用户意图明确**：bbox + note 共同定义“我想记录这里”。
- **边界清楚**：shell 不做采集编排，daemon 才是系统大脑。
- **失败不污染**：attempt 失败不会产生假 event。

## 后续扩展

触发入口可以继续增加：

- 浏览器扩展按钮。
- App 内右键菜单。
- 命令行触发。
- 自动化触发。

但这些入口都必须遵守同一个原则：它们只提交用户意图和系统 hints，不绕过 daemon 直接写 event。

---

导航：[返回文档总览](README.md) · 上一篇：[总体技术简介](TECHNICAL_OVERVIEW_CN.md) · 下一篇：[阶段 2：采集](02_COLLECTION_CN.md)
