# WorkRecorder 独立安装包试用说明

这份说明给“不是项目开发者”的同事使用。目标是让对方拿到一个 `.zip` 或 `.dmg` 后，可以双击启动 WorkRecorder，而不需要 clone 仓库、安装 uv、手动启动 daemon。

> 当前分发包是本机 Beta 包：已经把 WorkRecorder daemon、Python runtime、浏览器扩展资源和测试页放进 App 里；还没有做 Apple Developer ID 公证，所以第一次打开时 macOS 可能会提醒“无法验证开发者”。

## 1. 生成分发包

在开发者机器的项目根目录执行：

```bash
cd /Users/example/Desktop/projects/workrecorder
./.venv/bin/python scripts/package_workrecorder_distribution.py --dev --verify --archive both
```

生成结果：

```text
dist/distribution/WorkRecorder.app
dist/distribution/WorkRecorder-macos-self-contained.zip
dist/distribution/WorkRecorder-macos-self-contained.dmg
```

如果只想生成 zip：

```bash
./.venv/bin/python scripts/package_workrecorder_distribution.py --dev --verify --archive zip
```

## 2. 发给别人

推荐发送：

```text
dist/distribution/WorkRecorder-macos-self-contained.zip
```

也可以发送：

```text
dist/distribution/WorkRecorder-macos-self-contained.dmg
```

不要发送 `dist/WorkRecorder.app`。那是开发包，会指向开发者本机仓库路径。

`dist/distribution/WorkRecorder.app` 是脚本生成的自包含 App 目录，适合本机检查；真正发给别人请发同目录下的 zip 或 dmg。zip/dmg 会去掉聊天软件、Finder 或 File Provider 容易附加的资源叉元数据，别人解压后更稳定。

不要用 `--adhoc-sign` 生成给别人试用的包。屏幕录制和辅助功能权限由 macOS TCC 按 App 的代码身份记录；ad-hoc 签名容易让系统把更新后的 App 当成新 App，出现“设置里已经允许，但 WorkRecorder 仍反复要求权限”的现象。默认打包会使用稳定的 `WorkRecorder Local Development` 本地签名，内测阶段虽然仍未公证，但权限身份会稳定得多。

分发包里的 `runtime-config.json` 不会携带开发者机器的真实 `install_secret`。你可能会看到：

```json
"install_secret": "__workrecorder_generate_on_first_launch__"
```

这是占位符。WorkRecorder 第一次在用户电脑上启动时，会在 `~/.workrecorder/app-dev/install-secret` 生成本机专属 secret，并用它启动 daemon 和重写本机浏览器扩展配置。

## 3. 对方怎么安装

### zip 方式

1. 解压 `WorkRecorder-macos-self-contained.zip`。
2. 把 `WorkRecorder.app` 拖到 `Applications`，或者直接放在任意本地文件夹。
3. 建议固定放在一个位置后再授权，例如：

   ```text
   /Applications/WorkRecorder.app
   ```

   macOS 权限会跟 App 的签名和路径有关。不要今天从下载目录打开、明天又从桌面打开，否则系统可能把它当成另一个 App，导致已经开的权限看起来又要重新开。
4. 第一次打开如果 macOS 拦截：
   - 右键点击 `WorkRecorder.app`
   - 选择 `打开`
   - 再确认打开

### dmg 方式

1. 双击 `WorkRecorder-macos-self-contained.dmg`。
2. 把 `WorkRecorder.app` 拖到 `Applications`。
3. 第一次打开同样可能需要右键 `打开`。

## 4. 第一次打开 macOS 提示怎么办

当前内测包使用本地开发签名，还没有 Apple Developer ID 公证。macOS 第一次打开时可能会提示“无法验证开发者”“Apple 无法检查是否包含恶意软件”，这是预期现象。

推荐打开方式：

1. 在 Finder 里找到 `WorkRecorder.app`。
2. 不要直接双击，先右键点击 App。
3. 选择 `打开`。
4. 在弹出的确认框里再次选择 `打开`。

如果仍然被拦截：

1. 打开 `系统设置`。
2. 进入 `隐私与安全性`。
3. 找到关于 WorkRecorder 被拦截的提示。
4. 点击 `仍要打开`。
5. 回到 Finder，再右键 `打开` 一次。

这只影响第一次打开。打开成功后，后续通常可以直接双击。

### 4.1 还是打不开：命令行急救

如果你确认这个包来自 WorkRecorder 项目或可信同事，但右键 `打开`、系统设置 `仍要打开` 都不行，可以用 Terminal 做一次排查。

先确认 App 放在固定位置。下面假设你已经把它拖到了：

```text
/Applications/WorkRecorder.app
```

打开 Terminal，依次执行：

```bash
APP="/Applications/WorkRecorder.app"

# 1. 看看 App 是否真的在这里
ls -ld "$APP"

# 2. 清掉下载/聊天软件附加的隔离标记。
# 只对可信来源的 WorkRecorder 包执行这一步。
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

# 3. 清掉 Finder/FileProvider 可能附加的资源叉元数据。
xattr -cr "$APP"

# 4. 检查 App 签名结构是否完整。
codesign --verify --deep --strict "$APP"

# 5. 再尝试打开。
open "$APP"
```

如果 `codesign` 没有输出，一般表示校验通过。然后看 WorkRecorder 是否能打开。

如果仍然闪退，可以直接运行可执行文件，看它把错误打到 Terminal：

```bash
"/Applications/WorkRecorder.app/Contents/MacOS/WorkRecorder"
```

也可以看最近 5 分钟的系统日志：

```bash
log show --last 5m --style compact --predicate 'process == "WorkRecorder"'
```

把 Terminal 里的错误信息、macOS 版本、你用的是 zip 还是 dmg 发给开发者，通常就能判断是权限、隔离标记、资源包还是运行时路径问题。

如果 Workbench 显示：

```text
daemon 在健康检查通过前退出
```

意思是 App 已经启动了内置的本机服务，但这个服务还没响应健康检查就退出了。新的分发脚本会在打包时真实启动一次内置 daemon 并检查 `/health`，所以正常分发包不应该再出现“缺 repo / 缺 .venv / 缺 Python 模块”这类问题。遇到这个提示时，优先点 `帮助与诊断` 复制诊断信息；新版诊断会带上 daemon 退出前的最近日志。

第一次真正使用截图时，WorkRecorder 还会需要两类 macOS 权限：

- `屏幕录制`：用于保存你框选的屏幕区域。
- `辅助功能`：用于读取截图框内的文字和窗口信息。

这些权限不是安装器权限，而是 macOS 的隐私授权。Workbench 会在 `开始使用` 页面引导你打开对应设置。

## 5. 第一次启动需要做什么

打开 App 后按 Workbench 的引导完成：

1. 确认 WorkRecorder 本机服务已启动。
2. 允许屏幕录制权限。
3. 可选：允许辅助功能权限，让“框内文字”更准。
4. 可选：加载 Chrome/Edge 浏览器扩展，让网页截图能补全 URL、标题和正文。
5. 用 `⌃⌘2` 试一次当前窗口截图，或用 `⌃⌘3` 试一次区域截图。

Chrome 扩展仍需要用户手动加载。macOS 普通 App 不能静默安装 unpacked extension，这是浏览器的安全限制。

下面是完整操作步骤。

### 5.1 打开 WorkRecorder

1. 打开 `WorkRecorder.app`。
2. 如果出现 macOS 安全提示，按第 4 节的方式右键打开。
3. 看到 WorkRecorder 控制中心后，先停在首页。
4. 如果首页显示“本机服务启动中”，等几秒再点 `再检查一次`。

### 5.2 打开屏幕录制权限

屏幕录制是最低门槛。没有它，WorkRecorder 不能保存你框选的屏幕区域。

1. 在 WorkRecorder 控制中心点 `开始使用`。
2. 找到 `屏幕区域` 或 `屏幕录制` 那一行。
3. 点击 `去系统设置允许`。
4. 系统设置会打开到隐私权限页。
5. 找到 `WorkRecorder`，打开开关。
6. macOS 可能要求退出并重新打开 WorkRecorder。按提示退出后，再打开 `/Applications/WorkRecorder.app`。

如果系统设置里看不到 WorkRecorder：

1. 确认你打开的是固定位置的 App，例如 `/Applications/WorkRecorder.app`。
2. 退出 WorkRecorder。
3. 重新从 Finder 右键打开 WorkRecorder。
4. 回到 `开始使用`，再点一次 `去系统设置允许`。

### 5.3 可选：打开辅助功能权限

辅助功能不是截图保存的硬门槛，但建议打开。它能帮助 WorkRecorder 更准确地读取截图框内文字、窗口标题和 App 信息。

1. 在 `开始使用` 页面找到 `框内文字` 或 `辅助功能`。
2. 点击 `去系统设置允许`。
3. 系统设置打开后，找到 `WorkRecorder`。
4. 打开开关。
5. 如果系统要求重新打开 App，退出 WorkRecorder 后再打开。

### 5.4 加载 Chrome 浏览器扩展

这一步只影响网页增强信息。没有扩展也能截图保存；有扩展时，Chrome 网页截图可以补全 URL、页面标题、网页正文、DOM 派生文本和 selection map。

先在 WorkRecorder 里准备路径：

1. 打开 WorkRecorder 控制中心。
2. 进入 `开始使用` 或 `保存范围`。
3. 找到 `浏览器扩展` / `网页信息`。
4. 点击 `复制要选择的文件夹`。
5. 如果旁边有 `在 Finder 中显示`，也可以点一下确认目录存在。

要选择的目录一般是：

```text
/Users/<你的用户名>/.workrecorder/app-dev/browser_extension
```

例如用户叫 `example`，路径可能是：

```text
/Users/example/.workrecorder/app-dev/browser_extension
```

注意：不要选 `manifest.json` 文件本身，要选整个 `browser_extension` 文件夹。

然后在 Chrome 里加载：

1. 打开 Chrome。
2. 在地址栏输入：

   ```text
   chrome://extensions
   ```

3. 打开右上角 `开发者模式`。
4. 点击 `加载已解压的扩展程序`。
5. 文件选择框弹出来后，直接按：

   ```text
   Command + Shift + G
   ```

   也就是 `⌘⇧G`。
6. 会出现“前往文件夹”的输入框。
7. 粘贴 WorkRecorder 复制出来的完整路径，例如：

   ```text
   /Users/example/.workrecorder/app-dev/browser_extension
   ```

8. 按回车。
9. 确认当前进入的是 `browser_extension` 文件夹。
10. 点击右下角 `选择` / `打开`。
11. Chrome 扩展列表里应该出现 WorkRecorder 相关扩展。
12. 回到 WorkRecorder，点 `再检查一次`。

如果是 Chrome for Testing，也同样打开：

```text
chrome://extensions
```

步骤完全一样。

如果文件选择框里看不到 `.workrecorder`：

- 这是正常的，因为 `.workrecorder` 是隐藏目录。
- 不要一层层找。
- 直接用 `⌘⇧G` 粘贴完整路径。

如果 Chrome 提示目录无效：

1. 确认选的是 `browser_extension` 文件夹，不是上一级 `app-dev`。
2. 确认目录里有 `manifest.json`。
3. 回 WorkRecorder 再点一次 `复制要选择的文件夹`。
4. 重新在 Chrome 里 `加载已解压的扩展程序`。

### 5.5 试一次截图

1. 打开一个网页，例如公司内部页面或普通网页。
2. 保持 WorkRecorder 正在运行。
3. 按快捷键：

   ```text
   Control + Command + 3
   ```

   也就是 `⌃⌘3`。
4. 鼠标拖出一个框，框住你想保存的内容。
5. 弹窗出现后，可以填一句 note，例如：

   ```text
   这段是客户报价风险，后面让 Agent 帮我整理。
   ```

6. 点击 `保存并复制链接` 或 `仅保存`。
7. 保存后弹窗会自动消失。
8. 回到 WorkRecorder 控制中心首页，应该能看到新的保存记录。

如果没有 Chrome 扩展：

- 记录仍然会保存。
- 卡片会以系统截图、主 App、OCR / a11y 文本为主。
- Chrome URL、网页全文等增强信息可能为空。

### 5.6 用 CLI 检查是否真的保存

如果用户熟悉命令行，可以打开 Terminal：

```bash
/Applications/WorkRecorder.app/Contents/Resources/runtime/repo/.venv/bin/workrecorder events search --limit 5 --json
```

如果是开发者本机仓库，也可以用：

```bash
cd /Users/example/Desktop/projects/workrecorder
./.venv/bin/workrecorder events search --limit 5 --json
```

想看某条记录的安全摘要：

```bash
./.venv/bin/workrecorder events inspect <event_id> --view summary --purpose manual_check --json
```

想看截图引用：

```bash
./.venv/bin/workrecorder events inspect <event_id> --view screenshot_ref --purpose manual_check --json
```

## 6. 分发包里包含什么

`WorkRecorder.app` 内部包含：

- macOS 截图 App。
- WorkRecorder daemon Python 代码。
- Python 3.12 runtime。
- daemon 依赖的虚拟环境。
- 浏览器扩展资源。
- ACME 测试页。
- App 图标和运行配置。

运行数据不会写进 App 内部，而是写到用户目录：

```text
~/.workrecorder/app-dev/
```

包括本地数据库、截图暂存、证据库和浏览器扩展本地配置。

## 7. 卸载

删除：

```text
WorkRecorder.app
~/.workrecorder/app-dev/
```

如果你只想删除 App，不删历史上下文，只删除 `WorkRecorder.app` 即可。

## 8. 当前限制

- 还没有 Apple Developer ID 公证，首次打开需要右键打开或在系统设置里点 `仍要打开`。
- Chrome/Edge 扩展仍需要手动加载。
- 当前包主要面向同事内测；正式外部分发还需要签名、公证、自动更新和更完整的安装器。
- 如果企业安全策略禁止运行未公证 App，需要后续做 Developer ID + notarization。

## 9. 开发者验证清单

发给别人前建议跑：

```bash
./.venv/bin/python -m pyright -p pyrightconfig.json
./.venv/bin/python -m scripts.quality_gate
./.venv/bin/python scripts/package_workrecorder_distribution.py --dev --verify --archive both
```

`--verify` 不只检查文件是否存在，还会用包内 Python runtime 启动一次 daemon，确认 `/health` 能通过。

然后从 zip 解压后的 App 打开一次：

```bash
TMP=$(mktemp -d /tmp/workrecorder-install-smoke-XXXXXX)
ditto -x -k dist/distribution/WorkRecorder-macos-self-contained.zip "$TMP"
open "$TMP/WorkRecorder.app"
```

确认：

- App 能启动。
- Workbench 能打开。
- Daemon health 正常。
- `⌃⌘2` 能截当前窗口，`⌃⌘3` 能框选区域截图。
- 保存后卡片能刷新。
- Chrome 扩展路径能从 App 中复制。
