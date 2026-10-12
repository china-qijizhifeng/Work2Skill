# WorkRecorder Capture HUD Reference Style Spec

目标：参考桌面图片的浅色光学截图体验，但不照抄 Finder 内容。WorkRecorder 保持轻量 Context Capsule：截图现场只确认、补一句用途、保存或稍后。

## Reference Mapping

| Reference element | WorkRecorder implementation |
| --- | --- |
| Finder / progress source | 只展示可信 app 图标 + app 名 + 自动工作区，例如 Chrome · 自动工作区 |
| 文件状态 / iCloud / 项目进度 chips | 删除，不在截图现场展示推断标签 |
| 选区框 | Tiffany Light Lens，浅色 veil，精密光学 handle |
| 大玻璃卡片 | 更轻的 Context Capsule，不与选区重叠 |
| 彩虹/Prism | 只保留边缘薄膜折射，不进输入区，不做 blob |

## Visual Rules

- Non-selection veil: light frosted ice-blue, not graphite/dark mask.
- Selection lens: clear inside, 2%-4% Tiffany haze, visible frame with brighter corners.
- Handles: small rounded square optical anchors, translucent white fill, Tiffany stroke, ice highlight.
- Capsule: frosted cyan-white, alpha 0.86-0.90 visual density, soft spatial shadow, satin rim.
- Header: status star + 已捕获上下文.
- Source: app icon + app name + 自动工作区. No URL, title, or page promise.
- Input: future-agent note, clean zone, no Prism pollution.
- Actions: ghost glass 稍后 + Light Capsule 保存为上下文.

## Acceptance Criteria

1. 底层文字不能透过浮窗主体、输入框、按钮区域读出来。
2. 一眼能看出截图 bbox，且不变成霓虹标注工具。
3. 浮窗和选区有关联，但没有 tooltip 尖角，也不压住选区主体。
4. 快照和真实 HUD 使用同一 token，不允许颜色/alpha 分叉。
5. `ACME Pricing`、URL、Finder/progress、chips 不出现在 HUD。
