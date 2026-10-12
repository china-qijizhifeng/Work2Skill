# WorkRecorder.app 本地一站式入口

WorkRecorder.app 的目标很朴素：把“开 daemon、装插件、授权权限、找 CLI”这些开发态动作收进一个 macOS 本地控制中心里。第一版还是本机 dev 版本，不做 Developer ID 公证和 DMG，也不静默安装 Chrome 插件，但 `.app` 会做本地 ad-hoc 签名，让 macOS 权限列表里出现 **WorkRecorder**。注意：ad-hoc 签名不是正式发布签名，重新打包后 macOS 仍可能要求重新授权。

[上一篇：文档总览](README.md) · [下一篇：Chrome 真实流程 Case Study](USER_GUIDE_CHROME_CASE_STUDY_CN.md)

## 它负责什么

| 页面 | 做什么 | 为什么重要 |
| --- | --- | --- |
| 首页 | 看 daemon、来源、最近 capture 是否正常 | 用户不用猜系统是不是活着 |
| 准备 | 一次性走完 daemon、屏幕录制、辅助功能、网页来源 | 把最容易卡住的安装/权限问题集中处理 |
| 来源 | 展示所有来源的安装、权限、连接、诊断状态 | Chrome 只是第一个网页来源，后续应用可以按同一套模型接入 |
| 试拍 | 打开 ACME 测试页、触发截图、展示保存后的摘要 | 让用户能用一个可复现 case 验证全链路 |
| 诊断 | 复制脱敏诊断 JSON、看本地路径、签名、权限、来源状态 | 出问题时能快速定位，不暴露 secret/raw content |

## 第一次怎么用

先在仓库里生成本地 App：

```bash
./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify
open dist/WorkRecorder.app
```

如果你还没有 `.venv`，先按 README 安装开发环境。WorkRecorder.app 本身会使用当前仓库里的 `.venv/bin/python` 启动 daemon，所以正常使用时不需要再手动 `uv run workrecorder-daemon`。

打开控制中心后按顺序做：

1. 看 daemon 是否 healthy。如果 8765 已经有健康 WorkRecorder daemon，应用会复用；如果没启动，应用会用仓库 `.venv` 启动。
2. 授权屏幕录制。按钮会先触发 macOS 的授权请求，再打开系统设置；授权后可能需要重启 WorkRecorder。
3. 授权辅助功能。这个权限用于采截图框内的系统可访问文本，是 `selection_text` 的主要来源。
4. 加载网页来源。点击打开 `chrome://extensions`，开启开发者模式，选择控制中心复制的 `browser_extension` 路径。文件选择框里如果看不到隐藏目录，按 `⌘⇧G`，粘贴完整路径，例如 `/Users/你的用户名/.workrecorder/app-dev/browser_extension`，然后选择整个文件夹。
5. 在“试拍”里打开 ACME 本地测试页，用 `⌃⌘3` 框选一块文字，或用 `⌃⌘2` 抓当前窗口，然后保存 note。
6. 回控制中心看最近 capture，或者用 CLI：

```bash
./.venv/bin/workrecorder events search ACME --json
./.venv/bin/workrecorder events inspect <event_id> --view selection_text --view clean_page_text --purpose manual_check --json
```

## 为什么不能一键安装 Chrome 插件

Chrome/Edge 不允许普通 macOS 应用悄悄安装 unpacked extension。WorkRecorder.app 能做的是：

- 打开正确的扩展管理页。
- 复制 WorkRecorder 准备好的 extension 路径。这个目录位于 `~/.workrecorder/app-dev/browser_extension`，不是签名后的 `.app` 内部资源。
- 告诉用户三步：打开开发者模式 → 加载已解压的扩展程序 → 选择路径。
- 轮询 daemon 的来源会话，看 extension 是否真的在线。

Chrome 文件选择框选隐藏目录时，推荐直接按：

```text
⌘⇧G
```

再粘贴：

```text
/Users/你的用户名/.workrecorder/app-dev/browser_extension
```

最后选择整个 `browser_extension` 文件夹，不要选择里面的 `manifest.json`。

这不是偷懒，而是浏览器安全模型决定的。后续如果走 Chrome Web Store 或企业策略安装，可以把安装方式换掉，控制中心的来源页面不需要改主流程。

## 来源控制台怎么为未来扩展预留

控制中心不把 Chrome 写死成特殊页面。daemon 提供 `ProviderDefinition` 和 `ProviderStatusReport`，应用只渲染通用状态：

- 是否内置或需要安装。
- 需要什么权限。
- 是否已配置。
- 是否有 session 在线。
- 最近诊断结果是什么。

未来 Slack、飞书、IDE、Terminal、PDF 来源接入时，最小路径是新增来源定义、权限说明、诊断项和运行时会话。控制中心仍然只显示同一套卡片。

## 本地保存在哪里

dev bundle 默认使用：

- 数据库：`~/.workrecorder/app-dev/workrecorder.db`
- staged screenshot：`~/.workrecorder/app-dev/staging`
- content-addressed vault：`~/.workrecorder/app-dev/artifacts`

诊断页会展示这些路径，但复制诊断时不会带 install secret、raw content、vault bytes 或 URL query/hash。

## 现在的边界

- 当前是本机测试版 `.app`，会做 ad-hoc 签名，但不做 Developer ID 公证、不发 DMG；重新打包后可能需要重新授权屏幕录制或辅助功能。
- WorkRecorder.app 依赖当前仓库和 `.venv`，还不是完全独立 runtime。
- Chrome extension 需要用户手动确认 Load unpacked。
- WorkRecorder.app 负责入口和状态工作台；Agent 读取仍然走 `workrecorder` CLI / skill，不在控制中心里做聊天 UI。

这版的重点是把门槛降下来：让用户可以从一个 macOS 入口完成设置、试拍、查看结果、复制诊断，同时保持后续 provider 接入时的架构边界。
