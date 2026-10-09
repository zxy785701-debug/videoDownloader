# 前端改版验收记录

## 最新版本 · 2026-10-08

用户确认四张图片作为新设计参考，采用白底蓝色、圆角输入框、简洁账号窗和免费／VIP 双卡；解析后保持下载与 AI 学习同屏。头像菜单、密码显隐和真实额度展示已实现，价格沿用 ¥19.90／30 天，免费／会员新摘要额度为每日 3／30 次。

45 项浏览器流程、7 组布局与生产构建通过；实际 8000 只读检查已确认加载新版，没有新增真实付款或模型调用。视觉与业务操作的人工验收待用户确认。当前说明和截图目录见 [参考设计改版与验收](FRONTEND_REFERENCE_REDESIGN.md)。

随后按用户截图反馈，将下方重复的“简单三步”换成四步使用教程与小贴士，保留上方功能介绍。顶部“使用教程”直达该区域，提供开始使用、详细帮助及完整教程入口；额外 12 项实际页面只读检查和生产构建通过，具体证据见上述当前说明。

最新反馈后，“详细帮助”弹窗已换为单一标题的“版权与使用声明”，入口与图标同步更新，教程继续保留在首页；页脚窄屏换行。另有 8 项实际页面只读检查和生产构建通过，旧帮助卡截图不代表当前版本。

以下 2026-10-03 内容保留为历史记录，布局尺寸和当时功能范围不代表当前版本。

## 2026-10-03 改版记录

## 当前补充调整

- 首页输入条最大宽度从 760px 收窄到 680px，主内容和流程区最大宽度统一为 920px，顶栏最大宽度收窄到 1040px。
- PC 的标题、输入区和下方卡片作为整体在主体区居中，位置按最新红框截图调整；平台标签与卡片之间的常驻状态区已收紧到 70px，短 PC 屏幕按高度统一收紧。
- 手机流程卡采用两列，最后一步独占一行；平台标签缩小横向内边距，320px 宽屏也能完整显示在一行。短屏压缩标题、间距和辅助文案；极短屏收起流程说明，保留输入操作。
- 流程卡片与帮助卡片是两个独立组件，通过条件渲染替换；原卡片从 DOM 移除。帮助采用自然内容高度，无固定高度、绝对定位占位或卡片内部滚动。
- 最新调整限定 PC 宽屏（至少 1024px）：取消卡片切换的淡入淡出等待，使用共同的普通布局区域预留空间，切换前后标题和输入框坐标保持一致；展开时按钮显示“收起帮助”。窄屏保持本轮调整前的行为。
- PC 解析中“正在获取视频信息”和解析后“查看解析结果”始终放在平台标签下方的状态区，空闲时该区域仍占位。解析各状态持续显示流程卡片；解析成功后自动打开结果弹窗，可通过右上角关闭按钮、Esc 或遮罩关闭，关闭后原位保留查看按钮以重新打开。窄屏仍使用原来的状态位置和成功后自动打开结果行为。
- PC“查看解析结果”改为浅蓝填充的胶囊按钮，蓝色 15px 文字与右箭头，48px 高、166px 宽，悬停时为纯蓝底白字。窄屏继续使用原按钮。1151×885 与 1024×600 验证了按钮完整位于状态区内，出现及关闭结果前后布局坐标一致且没有页面滚动；记录：[pc-result-button-checks.json](D:/nbproject/videoDownloader/.local/home-layout-20261003/pc-result-button-checks.json)。
- TypeScript 与生产构建通过。解析和下载请求逻辑未改；新增响应式状态仅用于控制 PC 切换及布局。
- 最新自动弹窗行为已在 1151×885 检查：解析成功直接弹出结果，关闭后主页布局坐标完全不变、流程五步保留且无整页滚动，查看按钮可重新打开结果。记录：[pc-auto-dialog-checks.json](D:/nbproject/videoDownloader/.local/home-layout-20261003/pc-auto-dialog-checks.json)；截图：[pc-auto-dialog-final.jpg](D:/nbproject/videoDownloader/.local/home-layout-20261003/pc-auto-dialog-final.jpg)。
- 之前的解析状态检查覆盖 1151×885（用户截图尺寸）、1440×900、1366×768、1280×720、1920×1080、1024×600：初始、解析中、解析成功的标题、输入框、平台、状态区和流程卡片坐标完全一致；流程五步持续保留，状态内容位于空白区内，卡片及整页均无滚动或裁切。成功后查看及关闭结果、帮助替换也通过。记录：[pc-feedback-checks.json](D:/nbproject/videoDownloader/.local/home-layout-20261003/pc-feedback-checks.json)。
- 当前按钮截图：[pc-result-button-final.jpg](D:/nbproject/videoDownloader/.local/home-layout-20261003/pc-result-button-final.jpg)。解析状态使用仅本机的界面验收样例，未向平台发送请求；临时服务检查后停止。之前截图和记录位于 `.local/home-layout-20261003/`；修改前源码保存在 `.local/home-layout-before-20261003/`。

以下是之前的视觉改版记录；其中页内结果布局及截图不代表上述调整后的当前界面。

## 之前的视觉改版记录

本版按用户最后提供的两张截图，以及「看着有点挤」的反馈完成：纯蓝色主操作、居中输入条、宽白色结果卡片、五步说明。说明只在初始页面显示，解析后让位给真实结果。没有加入会员、注册、套餐、AI 总结或虚构平台数量。

## 最终布局与变量

- 桌面输入条最大 760px、高 64px；结果区最大 960px；顶栏与说明区最大 1184px。
- 桌面左侧 280px 封面，右侧标题/来源/时长，间距 32px；手机封面全宽，标题在下方，不再挤在缩略图旁边。
- 单格式卡最大 320px；多格式桌面两列、手机单列。格式间距 16px，卡片内边距 16px；未知大小只统一提示一次。
- 五步说明卡间距和内边距均为 24px；桌面五列、平板两列、手机单列。主按钮在结果底部，不遮挡格式选择。
- 所有设计值集中在 `frontend/tailwind.config.js`。主色 `#2F6FED`，中性灰与红色错误；成功使用主色。深色自动跟随 `prefers-color-scheme`。
- 首页标题桌面 48px / 手机 36px，输入与视频标题 18px，正文 15px，辅助 13px；字重只用 400 / 500 / 600。
- 间距按 8px 刻度；圆角为 14px 与胶囊两档。仅输入条有很轻的阴影，焦点环服务于操作反馈。

## 修改文件

| 文件 | 作用 |
| --- | --- |
| `frontend/src/App.vue` | 顶栏、居中输入、页内结果与说明区显示条件 |
| `frontend/tailwind.config.js` | 统一视觉和动效变量 |
| `frontend/src/style.css` | 公共按钮、格式卡和过渡 |
| `frontend/src/components/LinkComposer.vue` | 胶囊输入条与手机两行操作 |
| `frontend/src/components/VideoResult.vue` | 封面、紧凑摘要、手机上下布局 |
| `frontend/src/components/FormatPicker.vue` | radio 单选、推荐、真实尺寸与统一提示 |
| `frontend/src/components/DownloadAction.vue` | 准备/进度/完成/失败的底部操作 |
| `frontend/src/components/RequestError.vue` | 原因、下一步操作和原始详情 |
| `frontend/src/components/ParseStatus.vue` | 真实等待信息 |
| `frontend/src/components/HelpPanel.vue` | 帮助补齐抖音支持 |
| `frontend/src/components/StartGuide.vue` | 五个真实使用步骤 |

旧 `ResultDialog.vue` 保留但当前页面不引用；没有弹窗或固定下载栏。修改前备份位于 `.local/frontend-before-inline-20261003/`。

## 验证

- `npm.cmd run build` 通过，包含 TypeScript 和生产构建。
- 真实抖音作品 `7691322577818201073` 解析成功，显示 `1080×1920`，没有误写为 1920p。
- 真实哔哩哔哩 `BV1nPaE6NE4g` 解析成功，显示五个格式；选择 394p 后只有一个视频格式选中，保留原始值 `video:30032`。
- 桌面、390px、320px、800px 检查通过，无横向溢出；真实页面控制台无警告或错误。
- App 十一个既有业务函数、三个 fetch 调用及参数、六个既有组件的 props/emit 和五个后端文件哈希均未改变。证据：[contracts.json](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/contracts.json)。
- 浅色主按钮/辅助文字对比度为 4.55:1 / 4.79:1；深色为 7.55:1 / 7.53:1。浅蓝底上的小字已改为更深蓝色。
- 深色与减少动态效果的媒体查询已生成并做代码检查；本轮没有改变操作系统偏好来模拟它们。

错误和下载状态使用仅绑定 `127.0.0.1:8001` 的临时 UI 测试服务，样例标明「界面状态测试样例」，没有向视频平台发送请求。服务已停止。实际应用继续使用原后端。本轮检查了保存入口，没有执行浏览器文件保存。

## 状态与截图

首页、结果和手机截图已经更新为放宽间距后的最终版。错误、解析中和下载状态截图在间距微调前采集，用于验证行为；状态逻辑保持不变。

| 状态 | 页面表现 / 截图 |
| --- | --- |
| 初始桌面 | [居中输入与五步说明](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/desktop-initial.png) |
| 初始手机 | [输入、按钮分行，说明单列](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/mobile-initial.png) |
| 解析中 | [按钮禁用、正在获取视频信息](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/parsing.png) |
| 解析成功 | [抖音单格式](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/desktop-douyin.png)、[哔哩哔哩多格式](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/desktop-bilibili.png) |
| 登录验证失败 | [Firefox 登录指引与重新解析](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/error-login.png) |
| 网络失败 | [检查网络后重新解析](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/error-network.png) |
| 不支持链接 | [修改链接](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/error-unsupported.png) |
| 下载准备中 | [固定尺寸按钮显示准备中](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/download-preparing.png) |
| 下载中 | [状态字段显示 42% 和进度条](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/download-progress.png) |
| 完成 | [完成对勾、文件名、保存到设备](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/download-ready.png) |
| 下载失败 | [下一步提示、可用的重试按钮](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/download-failed.png) |
| 手机结果 | [抖音](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/mobile-douyin.png)、[哔哩哔哩](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/mobile-bilibili.png)、[320px](D:/nbproject/videoDownloader/.local/ui-redesign-20261003/mobile-320.png) |

## 必须避免：逐条自检

| 项目 | 结果 |
| --- | --- |
| 渐变、渐变文字、光斑、玻璃拟态 | 无；蓝色为纯色 |
| 居中 hero 加三列等宽图标模板 | 无三列卡；按最新截图使用居中输入和五个真实步骤，解析后隐藏步骤 |
| emoji 当图标 | 无；沿用 Lucide |
| 全部大圆角、大阴影 | 无；普通组件 14px，输入/主操作/标签可用胶囊；卡片没有阴影 |
| 空泛营销文案、虚构数据/用户数/评价 | 无；只描述实际操作 |
| 悬浮放大、无意义入场动画 | 无；过渡只服务于交互或状态 |

## 动效：逐条自检

| 项目 | 实现 |
| --- | --- |
| 输入聚焦与粘贴提示 | 平滑边框/焦点环；有效粘贴触发一次轻微透明度反馈 |
| 解析 loading 与结果展开 | 按钮尺寸稳定；Vue 高度和透明度展开结果 |
| 分步解析文案 | 按已确认方案改为真实等待；接口不返回阶段，未模拟读取格式等进度 |
| 格式选择 | 320ms 边框/对勾反馈，其余卡片轻微淡出；原生 radio 单选 |
| 下载准备、进度、完成 | 原任务状态驱动文案、进度条、完成对勾和保存入口 |
| 错误反馈与下一步 | 220ms 进入、150ms 退出；重新解析、修改链接或下载重试 |
| CSS / Vue Transition | 没有新增动画库 |
| prefers-reduced-motion | 去掉高度、位移、弹性和进度宽度插值，只保留淡入淡出 |

已修正：顶栏 token 与 spacing 名称冲突、中间宽度对齐、过小触摸目标、浅蓝底小字对比度、固定下载栏遮挡格式，以及手机长标题与封面并排拥挤。
