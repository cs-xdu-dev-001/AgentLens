---
name: KnowFlow AI
description: 安静、克制且过程透明的Agent学习与实践工作台
colors:
  canvas: "#f2f2ef"
  surface: "#fbfbf9"
  surface-soft: "#f6f6f3"
  surface-hover: "#e7e7e2"
  text: "#171717"
  text-soft: "#303030"
  muted: "#696965"
  border: "#d8d8d0"
  border-strong: "#c8c8bf"
  inverse: "#151515"
  inverse-text: "#f7f7f2"
  terminal-accent: "#d97757"
typography:
  headline:
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  title:
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "18px"
    fontWeight: 650
    lineHeight: 1.4
  body:
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.4
rounded:
  sm: "8px"
  md: "10px"
  lg: "14px"
  floating: "18px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.inverse}"
    textColor: "{colors.inverse-text}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
  chip:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-soft}"
    rounded: "{rounded.pill}"
    padding: "4px 10px"
---

# Design System: KnowFlow AI

## Overview

**Creative North Star: "安静的可见工作台"**

KnowFlow AI不是仪表盘陈列馆，也不是重新包装的聊天框。它是一张安静、专业的Agent工作台：主体让用户专注任务，右侧运行面板把模型、工具、Skills、MCP、记忆和计划的关键状态讲清楚。界面保持低饱和黑白中性色，不用装饰制造“高级感”，而通过清晰层级、稳定密度和真实状态建立可信度。

优化以现有界面为基础。保留当前导航、三栏聊天布局、黑白视觉语言和主要交互；只收敛字体、间距、圆角、边框、控件和信息密度。Agent过程必须可见，但采用渐进披露：先说明发生了什么，需要时再展开输入、输出、耗时和诊断信息。

**Key Characteristics:**

- 安静克制的黑白中性色
- 桌面优先、长时间使用友好的工作台密度
- 状态优先、细节按需展开的Agent过程
- 统一而不过度圆润的控件语言
- 中文优先、专业但不晦涩的表达

## Colors

色彩只服务于层级、状态和可读性，默认界面保持中性；成功、警告和错误色只在确有状态含义时出现。

### Primary

- **工作台黑**：用于主要文字、强调操作和选中状态。其稀缺性让重要操作自然突出。

### Neutral

- **暖灰画布**：承载全局工作区，弱化长时间阅读的视觉疲劳。
- **纸面白**：用于主要内容面、输入区域和抽屉。
- **柔和灰面**：用于次级分区、悬停和轻量状态背景。
- **结构灰线**：用于边界和分隔，不承担视觉主角。
- **层级灰字**：仅用于辅助信息，核心信息不得依赖低对比小字。

**The Monochrome-First Rule.** 默认操作和结构只使用中性色；语义色必须对应真实状态，不能作为装饰。

CLI终端使用`#d97757`作为唯一品牌强调色，仅用于欢迎框标题、输入边界、当前命令和运行指示；正文、结果与辅助信息仍使用终端中性色。Shell工具沿用Claude Code的渐进披露：运行时默认展示最近5行及耗时、行数、字节数，`Ctrl+O`展开有界详情；无输出、超时、非零退出与用户中断必须明确区分。

**The Contrast Before Color Rule.** 先用字号、字重、间距和明暗建立层级，再考虑颜色。

## Typography

**Display Font:** Inter与系统无衬线字体栈
**Body Font:** Inter与系统无衬线字体栈

**Character:** 字体中性、紧凑、适合中英文混排。层级依靠少量稳定角色，不使用“大标题＋小字号解释段落”的模板式组合。

### Hierarchy

- **Headline**（700，28px，1.25）：页面名称和高价值分区标题；同一视口不重复制造大标题。
- **Title**（650，18px，1.4）：卡片、抽屉和任务节点的主要名称。
- **Body**（400，16px，1.65）：聊天正文、说明和表单主要内容；长文控制在约72ch以内。
- **Label**（600，14px，1.4）：控件标签、状态和紧凑元数据；不得替代正文表达核心信息。

**The Four-Level Rule.** 一个界面最多同时使用四级文字角色，避免用零散字号制造层级。

**The Core Message Rule.** 用户必须理解的信息应进入标题、正文、控件标签或占位符，不得藏在低对比小字中。

## Layout

桌面端沿用左侧导航、中部工作区、右侧运行面板的三栏结构。聊天主区保持内容聚焦，输入框与对话内容共享同一视觉轴；右侧面板是运行过程的第二阅读层，不与回答正文争夺注意力。

间距采用4px基础节奏，常用步长为8、12、16、24和32px。页面级留白优先使用24或32px，控件内部优先使用8或12px。设置、知识库、Skills、记忆和MCP页面共享同一种列表—详情或列表—编辑工作区语法，不为每页重新发明布局。

1180px以下允许收窄或覆盖右侧运行面板；900px以下收起左侧导航；720px以下进入单列核心流程。移动端保留聊天、模型切换、Skill选择、审批和运行状态，次级详情通过抽屉展开。

**The Existing-Skeleton Rule.** 优化不得改变现有信息架构和主导航位置；任何结构变化必须解决明确的可用性问题并单独确认。

## Elevation & Depth

系统以平面和色阶分层为主。常驻页面、列表和卡片不使用阴影；边框、背景差和留白负责区分层级。阴影只用于真正悬浮的输入框、菜单、对话框和覆盖式抽屉，并保持柔和、短距离、低不透明度。

### Shadow Vocabulary

- **悬浮输入**（`0 18px 46px rgba(15, 23, 42, 0.10)`）：仅用于底部输入框等脱离文档流的关键悬浮控件。
- **临时浮层**（`0 10px 24px rgba(19, 26, 34, 0.16)`）：用于菜单和对话框，关闭后不留下视觉痕迹。

**The Flat-By-Default Rule.** 常驻表面默认无阴影；只有空间上真实悬浮的元素才获得阴影。

## Shapes

形状保持克制。8px用于小控件，10px用于按钮和输入，14px用于卡片与抽屉内分区，18px仅用于输入框、对话框等重点悬浮容器，胶囊形只用于状态、筛选或极短标签。边框统一为1px中性灰，焦点态使用清晰轮廓而不是加粗双边框。

**The Radius Budget Rule.** 同一组件只使用一个主圆角；大圆角不能层层嵌套。

## Components

### Buttons

- **Shape:** 紧凑矩形，轻微圆角（10px）。
- **Primary:** 工作台黑底、反白文字，内边距10px 16px；每个操作区最多一个。
- **Hover / Focus:** 悬停只做轻微明暗变化；键盘焦点必须有2px可见轮廓。
- **Secondary / Ghost:** 次级按钮使用纸面白和1px边框；无边框按钮只承载低风险辅助操作。

### Chips

- **Style:** 柔和灰面、14px字重标签、胶囊形；用于状态、协议、来源和筛选。
- **State:** 选中态通过更高对比文字或深色填充表达，不使用多余图标。

### Cards / Containers

- **Corner Style:** 轻度圆角（14px）。
- **Background:** 纸面白或柔和灰面。
- **Shadow Strategy:** 常驻容器无阴影。
- **Border:** 1px结构灰线。
- **Internal Padding:** 16或24px，信息密集列表可降至12px。

### Inputs / Fields

- **Style:** 纸面白背景、1px边框、10px圆角，标签与输入值形成直接关系。
- **Focus:** 清晰边框和外轮廓，不改变布局尺寸。
- **Error / Disabled:** 错误说明紧邻字段并给出下一步；禁用状态保持可读，不只依赖透明度。

### Navigation

导航项使用16px正文和稳定行高，默认透明、悬停柔和灰面、选中态提高对比并保持当前位置可辨识。图标只辅助识别，不替代文字。移动端将主导航收进抽屉，但新对话和当前任务入口保持可达。

### Composer

输入框是聊天页的主要操作面。文本输入占据主层级；附件、模型和Skill选择以同一行的紧凑入口出现；发送按钮保持明确但不过度放大。两行结构必须视觉相连，不能像两个独立工具条。

### Agent Run Trace

运行轨迹以状态和任务语义为第一层：名称、状态、耗时必须一眼可读。输入、输出、错误、来源和诊断信息在选中节点后展开。不得渲染隐藏思维链、Secret、Token或未经脱敏的内部日志。

## Do's and Don'ts

### Do:

- **Do** 在现有黑白三栏界面上做系统性收敛，而不是换一套视觉世界。
- **Do** 让模型、工具、Skills、MCP、记忆和计划使用一致的状态语言。
- **Do** 将设置和管理页面做成清晰的列表—详情工作区。
- **Do** 让错误信息说明失败对象、原因类别和可执行的下一步。
- **Do** 同时验证桌面、窄屏、长文本、空状态和键盘操作。

### Don't:

- **Don't** 用大标题配一段低对比小字来制造层级。
- **Don't** 为“高级感”增加渐变、玻璃拟态、发光、厚阴影或装饰性色块。
- **Don't** 把每个信息块都做成圆角卡片，也不要层层嵌套卡片。
- **Don't** 隐藏Agent过程，或把未脱敏的后端日志直接输出到前端。
- **Don't** 改名、换Logo、重排导航或改变核心交互，除非用户另行确认。
