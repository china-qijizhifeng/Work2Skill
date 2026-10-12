export type NavItem = {
  label: string;
  href: string;
};

export type Capability = {
  label: string;
  title: string;
  body: string;
  tone: "mint" | "blue" | "amber" | "silver";
};

export type TimelineStep = {
  label: string;
  title: string;
  body: string;
  meta: string;
  tone: "mint" | "blue" | "amber" | "silver";
};

export const navItems: NavItem[] = [
  { label: "首页", href: "index.html" },
  { label: "截图保存", href: "product.html" },
  { label: "记录片段", href: "active-capture.html" },
  { label: "给 Agent 用", href: "agents.html" },
  { label: "安全", href: "governance.html" },
  { label: "原理", href: "architecture.html" }
];

export const coreCapabilities: Capability[] = [
  {
    label: "Now · 截图",
    title: "把一刻现场变成证据卡",
    body: "框选、备注、保存；画面、App、时间和文字一起进入本机记录。",
    tone: "mint"
  },
  {
    label: "Next · 记录",
    title: "把一段做法整理成步骤",
    body: "视频给人回看，关键时刻和操作线索整理成待确认的步骤草稿。",
    tone: "blue"
  },
  {
    label: "Core · Agent",
    title: "少量安全上下文，回答可追溯",
    body: "Agent 先看摘要，需要更多时再打开指定记录；回答引用和读取过程都会留痕。",
    tone: "amber"
  }
];

export const architectureStages: TimelineStep[] = [
  { label: "01", title: "保存现场", body: "快捷键、备注、选区和窗口信息先落到本机。", meta: "不丢画面", tone: "silver" },
  { label: "02", title: "补齐来源", body: "系统识别文字；命中的 App 可以继续补充自己的上下文。", meta: "来源清楚", tone: "mint" },
  { label: "03", title: "分开完整材料和摘要", body: "完整截图、原始网页材料和安全文本分开保存。", meta: "完整材料需确认", tone: "blue" },
  { label: "04", title: "生成可读文本", body: "搜索先用备注、标题、时间和识别文字；网页正文要点开记录后读取。", meta: "安全文本", tone: "amber" },
  { label: "05", title: "按需交给 Agent", body: "查找时只给摘要；点开记录必须说明目的。", meta: "少给一点", tone: "mint" },
  { label: "06", title: "回答后可复盘", body: "记录 Agent 搜了什么、看了什么、引用了什么。", meta: "有账可查", tone: "blue" }
];

export const disclosureRows = [
  ["搜索短卡", "event_id、时间、应用、标题、备注、截图识别文字、隐藏材料清单", "例如：Agent 能知道“这条记录可能和 ACME 报价有关”，但还看不到完整原图。"],
  ["点开记录", "清洗后的网页正文、可引用正文、截图引用、录制关键时刻", "例如：Agent 指定某条记录后，才能读取网页正文或截图引用。"],
  ["单独确认", "完整截图、原始视频、原始网页材料、本地文件路径、未清洗完整材料", "例如：要打开完整原图或原始视频，必须单独确认并留下记录。"]
] as const;
