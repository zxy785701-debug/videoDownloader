export type Locale = 'zh' | 'en'
export type Topic = 'home' | 'video-download' | 'ai-video-summary' | 'subtitle-download'
export interface Section {
  id: string
  heading: string
  paragraphs?: string[]
  items?: string[]
  ordered?: boolean
  code?: string
  table?: { headers: string[]; rows: string[][] }
  questions?: { question: string; answer: string }[]
}
export interface PublicPage {
  locale: Locale
  topic: Topic
  title: string
  description: string
  keywords: string[]
  heading: string
  lead: string
  sections: Section[]
}

export const repository = 'https://github.com/zxy785701-debug/videoDownloader'
export const contentUpdated = '2026-10-08'
// Evidence for core behavior is pinned to a published implementation snapshot.
export const evidenceRevision = 'd05a0a213b2ce1dc14bde0c1018f52f79c13c0e1'
export function evidenceFor(page: PublicPage) {
  const files = {
    home: ['docs/UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md', 'backend/app/platform_adapters.py', 'backend/app/subtitle_service.py'],
    'video-download': ['docs/DOWNLOAD_ADAPTER_INTEGRATION.md', 'backend/app/platform_adapters.py', 'start-local.ps1'],
    'ai-video-summary': ['docs/AI_VIDEO_SUMMARY_TEST_REPORT.md', 'docs/AI_SUMMARY_SSE_TEST_REPORT.md', 'backend/app/summary_service.py'],
    'subtitle-download': ['docs/MINDMAP_SUBTITLE_ENHANCEMENT_TEST_REPORT.md', 'backend/app/subtitle_service.py', 'backend/app/analysis_routes.py'],
  }
  return files[page.topic].map(path => ({ label: path, url: `${repository}/blob/${evidenceRevision}/${path}` }))
}
export const locales: Locale[] = ['zh', 'en']
export const topics: Topic[] = ['home', 'video-download', 'ai-video-summary', 'subtitle-download']
export function pagePath(locale: Locale, topic: Topic): string {
  return topic === 'home' ? `/${locale}/` : `/${locale}/guides/${topic}/`
}

export const labels = {
  zh: {
    language: 'zh-CN', ogLocale: 'zh_CN', otherLanguage: 'English', home: '产品介绍', guides: '使用教程',
    skip: '跳到正文', toc: '本页内容', related: '继续阅读', source: '查看源码与项目文档',
    updated: '内容核对日期', cta: '查看本机使用方法', local: '打开本机工作区',
    eyebrow: 'SaveAny · 本机视频下载与学习工具',
    footer: '公开介绍与教程不读取学习记录。本机工具使用可用的平台字幕生成摘要；请只保存自己拥有版权或已获授权的内容。',
    preview: '本机预览：尚未配置正式域名，本页不参与搜索收录。',
    setupLink: '先安装并启动本机工具',
    maintainer: '内容维护：SaveAny 项目文档', markdown: '阅读 Markdown 版本',
    evidence: '功能依据与测试记录', evidenceNote: '以下源码与项目内测试记录用于核对功能范围。测试样例不保证所有视频可用，也不是独立评测。',
  },
  en: {
    language: 'en', ogLocale: 'en_US', otherLanguage: '简体中文', home: 'Overview', guides: 'Guides',
    skip: 'Skip to content', toc: 'On this page', related: 'Read next', source: 'Source code and project docs',
    updated: 'Content reviewed', cta: 'Set up the local app', local: 'Open the local workspace',
    eyebrow: 'SaveAny · Local video downloads and learning',
    footer: 'These public pages do not access learning records. The local app summarizes available platform captions. Only save content you own or have permission to download.',
    preview: 'Local preview: no production domain is configured. This page is excluded from search indexing.',
    setupLink: 'Install and start the local app first',
    maintainer: 'Maintained in the SaveAny project documentation', markdown: 'Read the Markdown version',
    evidence: 'Implementation sources and test records', evidenceNote: 'These source files and project test records support the feature scope. Recorded examples do not guarantee availability for every video and are not independent reviews.',
  },
}

const installCommands = `git clone ${repository}.git
cd videoDownloader
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm.cmd install --prefix frontend
.\\start-local.ps1`

export const pages: PublicPage[] = [
  {
    locale: 'zh', topic: 'home',
    title: 'AI视频总结与下载 - 本机学习 | SaveAny',
    description: 'SaveAny 在本机下载视频，按可用字幕生成 AI 总结、章节和导图，支持字幕与摘要导出。查看支持平台及教程。',
    keywords: ['AI视频总结', '视频下载', '字幕下载', '视频思维导图', 'SaveAny'],
    heading: '万能视频下载总结器',
    lead: '把视频保存下来，也把内容读懂。SaveAny 将视频信息、画质选择和 AI 总结放在同一工作区，适合整理获授权的视频素材、复习课程与阅读长视频字幕。',
    sections: [
      { id: 'definition', heading: 'SaveAny 是什么？', paragraphs: ['SaveAny（万能视频下载总结器）是需要自行安装的本机视频下载与学习工具。它把视频信息、下载选项、字幕、AI 摘要和问答放在同一工作区。AI 总结依据可用的平台字幕，需要配置自己的 DeepSeek 密钥；视频下载与字幕导出无需模型密钥。'], table: { headers: ['项目', '当前能力'], rows: [
        ['运行方式', '本机运行；快速启动脚本面向 Windows PowerShell'],
        ['适用需求', '保存获授权的视频、复习课程、检索字幕与整理学习笔记'],
        ['导出格式', '视频文件、SRT、TXT、Markdown、PNG、SVG'],
        ['语言', '公开教程为中英文；工作区与结构化摘要以中文为主'],
        ['模型用量', '摘要、重新生成与视频问答可能产生自己的 DeepSeek 账户用量'],
      ] } },
      { id: 'features', heading: '一个视频链接，完成下载与学习', items: [
        '视频下载：先查看标题、封面、时长和源站可用格式，选择清晰度后保存到设备；分离音视频按可用格式合并。',
        'AI 视频总结：可用字幕到位后，按开关选择自动生成总览、章节与核心知识点；下载可以先进行。',
        '字幕与引用：阅读带时间戳的原文，搜索内容，按引用核对摘要，并下载完整 SRT 或 TXT。',
        '思维导图与问答：围绕摘要查看导图，导出 PNG、SVG，依据字幕继续提问；摘要可导出 Markdown。',
      ] },
      { id: 'platforms', heading: '支持哪些视频平台？', paragraphs: [
        '视频下载与字幕总结的支持范围不同。能下载不代表一定有可用字幕，平台限制、登录状态、地区和网络也会影响结果。',
      ], table: { headers: ['来源', '视频下载', 'AI 总结前提'], rows: [
        ['哔哩哔哩 / B 站', '已有平台适配，支持可用画质与分 P', '字幕可用；部分视频需本机登录会话'],
        ['YouTube', '使用 yt-dlp；可能需要登录验证', '字幕可用；保留所选字幕语言'],
        ['抖音', '公开普通视频；不含图集与直播', '字幕接口可能受访问限制'],
        ['芒果 TV', '尝试保存当前账号有权完整观看的视频', '当前未接入 AI 字幕总结'],
        ['其他来源', '以提取器和实际解析结果为准', '当前不自动创建 AI 学习记录'],
      ] } },
      { id: 'workflow', heading: '如何使用 SaveAny？', ordered: true, items: [
        '在电脑上安装依赖并启动本机服务；需要 AI 总结时，在后端配置自己的 DeepSeek 密钥。',
        '粘贴视频页面链接并点击“解析视频”，确认视频信息与画质。自动总结默认开启，也可以关闭。',
        '点击下载，文件就绪后保存到设备；在另一侧阅读摘要、字幕或导图，继续提问。',
        '从本机学习记录恢复已保存内容，或导出字幕、摘要与导图。',
      ] },
      { id: 'data', heading: '内容保存在哪里？', paragraphs: [
        '字幕、摘要、问答和中间结果保存在本机 SQLite，可恢复或手动删除。启用 AI 后，相关字幕与问题会发送到 DeepSeek API；模型请求可能产生账户用量。浏览器 Cookie 和模型密钥不发送给前端。',
        '当前工具面向个人本机运行，工作区与结构化摘要以中文为主，字幕保留原语言。本网站提供中英文介绍与教程，没有把本机学习记录发布为搜索内容。',
        '无需模型密钥也能使用视频下载和可用字幕。没有字幕时不会进行语音转录或画面分析；项目不处理 DRM 或访问控制绕过，也不保证所有视频都能下载或总结。',
      ] },
      { id: 'faq', heading: '视频下载与 AI 总结常见问题', questions: [
        { question: 'SaveAny 能总结没有字幕的视频吗？', answer: '当前不能。SaveAny 的摘要与视频问答依据可用的平台字幕，不提供语音转录或视频画面分析。没有字幕时仍可尝试独立的视频下载。' },
        { question: 'SaveAny 能下载和总结任意平台的视频吗？', answer: '不能保证。视频下载已适配 B 站、YouTube、抖音和芒果 TV；字幕尝试获取 B 站、YouTube 与抖音的可用轨道，抖音字幕接口可能受限。芒果 TV 尚无字幕总结适配，实际可用性取决于源站权限和网络。' },
        { question: '使用 SaveAny 是否必须配置模型密钥？', answer: '视频下载、字幕获取与 SRT/TXT 导出不需要模型密钥。AI 摘要和视频问答需要自己的 DeepSeek 配置，可能产生服务商账户用量。只取视频或字幕时可关闭自动总结。' },
        { question: 'SaveAny 适合哪些人？', answer: 'SaveAny 适合愿意在本机安装工具、保存获授权素材和依据字幕复习课程的用户。需要纯在线免安装服务、无字幕转录、字幕翻译或批量播放列表下载时，当前版本不满足这些需求。' },
      ] },
    ],
  },
  {
    locale: 'en', topic: 'home',
    title: 'AI Video Summaries & Downloads | SaveAny',
    description: 'Download videos and summarize available captions locally with SaveAny.',
    keywords: ['AI video summarizer', 'video downloader', 'subtitle download', 'video mind map', 'SaveAny'],
    heading: 'Video downloader and AI video summarizer',
    lead: 'SaveAny is a local video downloader and AI video summarizer. Keep video details, download controls and learning notes in one workspace for reviewing lectures and organizing video material you have permission to save.',
    sections: [
      { id: 'definition', heading: 'What is SaveAny?', paragraphs: ['SaveAny is a video downloader and learning tool that you install and run locally. Its workspace combines video metadata, download options, transcripts, AI summaries and Q&A. Summaries require available platform captions and your own DeepSeek key. Video downloads and subtitle exports do not require a model key.'], table: { headers: ['Item', 'Current capability'], rows: [
        ['Deployment', 'Local app; the quick-start script targets Windows PowerShell'],
        ['Use cases', 'Save authorized videos, review courses, search captions and prepare study notes'],
        ['Exports', 'Video files, SRT, TXT, Markdown, PNG and SVG'],
        ['Languages', 'Bilingual public guides; primarily Chinese workspace and structured summaries'],
        ['Model usage', 'Summaries, regeneration and Q&A may incur usage on your own DeepSeek account'],
      ] } },
      { id: 'features', heading: 'From a video link to files and notes', items: [
        'Video downloads: inspect the title, thumbnail, duration and available formats before choosing a quality. Supported separate audio and video tracks are merged.',
        'AI summaries: create an overview, chapters and key points from available platform captions. Automatic summarization is optional, and downloads can proceed while the summary runs.',
        'Transcripts and citations: search timestamped captions, check summary references against the source, and export the complete transcript as SRT or TXT.',
        'Mind maps and questions: explore a summary as a mind map, export PNG or SVG, and ask questions grounded in the captions. Export summaries as Markdown.',
      ] },
      { id: 'platforms', heading: 'Which platforms are supported?', paragraphs: [
        'Download support and caption support are separate. A downloadable video may have no accessible captions. Platform restrictions, account access, location and network conditions can affect results.',
      ], table: { headers: ['Source', 'Video downloads', 'AI summary requirement'], rows: [
        ['Bilibili', 'Platform adapter, available quality options and video parts', 'Accessible captions; some videos need a local browser session'],
        ['YouTube', 'Uses yt-dlp; login verification may be required', 'Accessible captions in the selected source language'],
        ['Douyin', 'Public standard videos; excludes image galleries and live streams', 'Caption endpoints may be restricted'],
        ['Mango TV', 'Attempts downloads within the current account’s full viewing access', 'AI caption support is not implemented'],
        ['Other sources', 'Depends on the extractor and actual parsing result', 'No automatic AI learning record is created'],
      ] } },
      { id: 'workflow', heading: 'How to use the local app', ordered: true, items: [
        'Install the dependencies and start the app on your computer. Add your own DeepSeek API key in the backend if you want AI summaries.',
        'Paste a video page URL and parse it. Check the video details and quality. Automatic summarization is enabled by default and can be switched off.',
        'Prepare and save the video file while reading the summary, transcript or mind map in the adjacent panel.',
        'Restore saved local learning records or export the transcript, summary and mind map.',
      ] },
      { id: 'data', heading: 'Where your learning data goes', paragraphs: [
        'Transcripts, summaries, questions and intermediate results are stored in a local SQLite database. AI requests send relevant captions and questions to the DeepSeek API and may incur account usage. Browser cookies and API keys are not sent to the frontend.',
        'The current app is designed for personal local use. Its workspace and structured summaries are primarily in Chinese; transcripts keep their source language. These English guides do not imply an English app interface or English summary output.',
        'Video downloads and available captions work without a model key. The app does not transcribe audio or analyze video frames when captions are missing. It does not bypass DRM or access controls, and availability is not guaranteed for every video.',
      ] },
      { id: 'faq', heading: 'Video download and AI summary questions', questions: [
        { question: 'Can SaveAny summarize a video without captions?', answer: 'Currently, no. SaveAny summaries and Q&A use available platform captions. Audio transcription and video frame analysis are not implemented. Video downloads can still be attempted independently.' },
        { question: 'Does SaveAny download and summarize videos from every platform?', answer: 'Availability is not guaranteed. Downloads have adapters for Bilibili, YouTube, Douyin and Mango TV. Captions are attempted for Bilibili, YouTube and Douyin, whose endpoints may be restricted. Mango TV has no caption-summary adapter. Source permissions and network conditions affect results.' },
        { question: 'Does using SaveAny always require a model key?', answer: 'Downloads, caption retrieval and SRT/TXT exports do not need a model key. AI summaries and Q&A require your own DeepSeek configuration and may incur provider usage. Turn automatic summarization off for downloads or captions alone.' },
        { question: 'Who is SaveAny for?', answer: 'SaveAny suits people willing to install a local tool to save authorized material and review courses using captions. It currently does not meet needs for an installation-free online service, transcription without captions, subtitle translation or batch playlist downloads.' },
      ] },
    ],
  },
  {
    locale: 'zh', topic: 'video-download',
    title: '视频下载 - 画质选择教程 | SaveAny',
    description: '用 SaveAny 解析支持的视频链接，选择可用画质并保存文件。了解本机安装、登录验证、下载失败与平台限制。',
    keywords: ['视频下载', '视频画质选择', 'B站视频下载', 'YouTube视频下载', 'SaveAny'],
    heading: '如何下载视频并保存到设备',
    lead: '视频下载分为解析链接、选择格式、准备文件和保存四步。先确认自己有权保存该内容，并在源站确认视频可以正常播放，再使用 SaveAny 的本机工作区。',
    sections: [
      { id: 'local-setup', heading: '安装并启动本机工具', paragraphs: [
        '当前快捷启动方式适用于 Windows PowerShell。先安装 Git、Node.js 22.12 或更新版本、Python 3.10 或更新版本；如果电脑有多个 Python，请确认所选版本满足要求。首次安装在 PowerShell 中运行以下命令。',
        '下载功能不需要 DeepSeek 密钥。项目优先使用系统 FFmpeg，未安装时使用依赖提供的 FFmpeg 回退。',
      ], code: installCommands },
      { id: 'start', heading: '打开页面并解析链接', paragraphs: [
        '启动命令完成后，在浏览器打开 http://127.0.0.1:8000。再次使用时，在项目目录运行 .\\start-local.ps1 即可。端口被占用时先关闭旧实例；服务终端保持运行。',
        '启动脚本使用本机 Firefox 会话。需要登录的来源先在 Firefox 登录并确认视频可播放；Cookie 数据库被锁定时退出该浏览器再启动。无需导出或填写 Cookie。',
      ], ordered: true, items: [
        '复制单个视频页面的完整 HTTP(S) 链接，粘贴到“视频页面链接”输入框。',
        '点击“解析视频”，核对标题、封面、时长与平台；链接不是视频或被平台拒绝时，先按页面错误提示处理。',
        '需要只下载时可关闭“解析后自动总结”，开关会记住本次选择。',
      ] },
      { id: 'quality', heading: '选择画质、准备文件并保存', ordered: true, items: [
        '从实际返回的清晰度中选择；“最佳画质”使用当前可用格式，不能解锁源站未提供的格式。',
        '使用默认自动交付方式，点击“下载”。B 站、YouTube、抖音、芒果等来源使用服务端准备文件，必要时合并音视频。',
        '等待文件就绪后点击保存到设备。页面进度表示文件准备，浏览器下载列表显示实际保存进度。',
      ], paragraphs: ['下载处理中暂时不能切换视频，但可阅读学习内容。任务与临时文件有有效期，过期后需要重新下载。'] },
      { id: 'troubleshooting', heading: '常见下载问题', questions: [
        { question: '为什么解析成功却下载失败？', answer: '上游媒体地址会过期，网络、登录状态或格式也可能变化。检查源站能否播放，重新解析后再选择格式。明确选择的清晰度不可用时不会静默换成别的画质。' },
        { question: '能下载私密视频、直播或所有平台吗？', answer: '当前主要处理单个公开视频。抖音不含图集、直播、私密或已删除作品；其他来源由适配器和源站权限决定。不提供播放列表批量下载、DRM 或访问控制绕过。' },
        { question: '视频下载是否必须等待 AI 总结？', answer: '不需要。两项任务独立，字幕受阻或模型没有配置时，下载仍可继续。AI 总结只在可用字幕和模型配置满足条件时进行。' },
        { question: '如何获得完整配置与排障说明？', answer: '查看下方项目源码与文档入口中的 docs/README.md 和平台测试报告。它们包含浏览器会话、代理与平台支持的具体配置，不要上传自己的 Cookie 或密钥。' },
      ] },
    ],
  },
  {
    locale: 'en', topic: 'video-download',
    title: 'Video Downloads - Setup & Quality Guide | SaveAny',
    description: 'Set up SaveAny, choose available video quality and save the file locally.',
    keywords: ['video downloader', 'video quality', 'Bilibili download', 'YouTube download', 'SaveAny'],
    heading: 'How to download a video and save the file',
    lead: 'Parse the video URL, choose a format, prepare the file and save it to your device. Confirm that you have permission to download the content and that it plays on the source platform before using SaveAny.',
    sections: [
      { id: 'local-setup', heading: 'Install and start the local app', paragraphs: [
        'The quick-start script currently targets Windows PowerShell. Install Git, Node.js 22.12 or later, and Python 3.10 or later. If multiple Python versions are installed, check which version your command uses. Run these commands in PowerShell for the first installation.',
        'Downloads do not require a DeepSeek API key. The app uses system FFmpeg when available and otherwise uses the fallback supplied by its dependencies.',
      ], code: installCommands },
      { id: 'start', heading: 'Open the workspace and parse a link', paragraphs: [
        'After startup, open http://127.0.0.1:8000 in your browser. For later sessions, run .\\start-local.ps1 from the project directory. Stop an old instance if the port is occupied, and keep the service terminal open.',
        'The startup script uses your local Firefox session. For sources requiring login, sign in to the source in Firefox and confirm playback first. If the browser cookie database is locked, close Firefox before starting the service. No cookie export is needed.',
        'The current workspace uses Chinese labels. “解析视频” means parse video, “下载” means download, and “解析后自动总结” controls automatic summarization.',
      ], ordered: true, items: [
        'Copy the complete HTTP(S) URL of one video page and paste it into the video URL input.',
        'Parse the link and check the title, thumbnail, duration and platform. Follow the page’s error message if the URL is not supported or access is denied.',
        'Switch off automatic summarization if you only want the download. The preference is remembered locally.',
      ] },
      { id: 'quality', heading: 'Choose quality and save the video', ordered: true, items: [
        'Choose from the formats returned by the source. Best quality selects an available format; it cannot unlock a format the source has not provided.',
        'Keep the default automatic delivery mode and start the download. Supported platform adapters prepare the file on the local backend and merge audio and video when needed.',
        'Wait for the file to become ready, then save it to your device. The page tracks file preparation; your browser download list tracks the actual save.',
      ], paragraphs: ['While a download runs, switching videos is disabled, but learning tabs remain available. Tasks and temporary files expire; an expired file must be prepared again.'] },
      { id: 'troubleshooting', heading: 'Common download questions', questions: [
        { question: 'Why can a parsed video fail to download?', answer: 'Media addresses can expire, and network conditions, account access or formats can change. Check playback on the source platform and parse the link again. A specifically selected unavailable quality is not silently replaced.' },
        { question: 'Can I download private videos, live streams or every platform?', answer: 'The app mainly handles individual public videos. Douyin support excludes image galleries, live streams, private and deleted works. Other sources depend on the adapter and your existing source access. Playlist downloads and access-control bypasses are not implemented.' },
        { question: 'Must the download wait for an AI summary?', answer: 'No. The tasks are independent. Downloads can proceed when captions are unavailable or a model is not configured. AI summaries require accessible captions and a configured model.' },
        { question: 'Where are detailed setup and troubleshooting instructions?', answer: 'Use the source and documentation link below, then read docs/README.md and the platform reports. They describe browser sessions, proxy settings and tested platform behavior. Do not upload your cookies or API keys.' },
      ] },
    ],
  },
  {
    locale: 'zh', topic: 'ai-video-summary',
    title: 'AI视频总结 - 字幕与导图 | SaveAny',
    description: '用 SaveAny 按可用字幕生成 AI 视频总结、章节与导图。了解模型配置、自动总结、引用核对与失败重试。',
    keywords: ['AI视频总结', '字幕总结', '视频章节', '视频思维导图', 'SaveAny'],
    heading: '如何根据字幕生成 AI 视频总结',
    lead: 'SaveAny 的 AI 视频总结以可用的平台字幕为依据，把长视频整理为总览、章节与知识要点。先下载并启动本机工具，再配置模型；没有字幕时，不会用视频画面或音频补做总结。',
    sections: [
      { id: 'requirements', heading: '准备可用字幕与模型配置', paragraphs: [
        '当前尝试获取 B 站、抖音、YouTube 的平台字幕。B 站和 YouTube 已有成功样例，抖音字幕接口可能受限；不能据此保证每个视频都能总结。字幕缺失或受阻时，页面说明原因，视频下载入口仍保留。',
        '在项目根目录的 .env 中填写自己的 DEEPSEEK_API_KEY，然后重启后端。配置模板位于 .env.example；不要把密钥填写到网页、聊天、前端或示例文件。也可运行 .\\start-local.ps1 -AskDeepSeekKey 在终端隐藏输入。',
        '当前默认模型为 DeepSeek，模型请求可能产生账户用量，费用以服务商账单为准。工具和结构化摘要目前以中文为主，原字幕保留源语言。',
      ] },
      { id: 'automatic', heading: '解析后自动总结', ordered: true, items: [
        '粘贴视频链接，保持“解析后自动总结”开启，然后点击“解析视频”。',
        '视频信息先显示，后台继续获取字幕；有有效字幕和模型配置时接续生成摘要。此时可先选择画质下载视频。',
        '阅读流式生成草稿，并等待正式摘要完成。草稿尚未完成校验，最终保存结果才是正式摘要。',
        '已保存摘要直接复用。关闭自动总结只获取信息与字幕，需要时可以手动生成。',
      ] },
      { id: 'reading', heading: '核对引用、查看导图与继续提问', paragraphs: [
        '摘要包含总览、章节和核心知识点。使用引用定位字幕，结合原文核对重要结论；模型引用经过服务端检查，但这并不保证所有内容理解都正确。',
        '在“思维导图”中查看相同摘要的结构，折叠节点并定位原文，导出完整 PNG 或 SVG。在“视频问答”中提交问题，回答基于字幕并带引用；提问会产生新的模型请求。',
        '摘要可导出 Markdown。当前导图不另建一套视频分析结果，问答也不读取视频画面。',
      ] },
      { id: 'recovery', heading: '保存、刷新与失败恢复', questions: [
        { question: '刷新页面会重复生成摘要吗？', answer: '已保存结果会复用，运行中的后台任务可重新订阅。历史恢复、字幕语言切换与流式重连不自动创建新的摘要模型请求。' },
        { question: '自动总结失败或服务重启后怎么办？', answer: '查看失败原因，修复字幕、配置或网络问题后手动重试。进程重启会中断未完成任务，不会自动重新发起计费生成。' },
        { question: '“重新生成”是否有新的模型用量？', answer: '会。重新生成会创建新请求，引用修复也可能产生额外用量。已有成功摘要在重新生成失败时保留。' },
        { question: '长视频有什么默认限制？', answer: '默认最长 2 小时、有效字幕 120,000 字符，并限制字幕资源和模型请求大小。超限会说明原因，不会静默丢弃后半段；具体配置见项目文档。' },
      ] },
    ],
  },
  {
    locale: 'en', topic: 'ai-video-summary',
    title: 'AI Video Summaries - Captions & Mind Maps | SaveAny',
    description: 'Summarize available captions into chapters and mind maps with SaveAny.',
    keywords: ['AI video summarizer', 'caption summary', 'video chapters', 'video mind map', 'SaveAny'],
    heading: 'How to summarize a video from its captions',
    lead: 'SaveAny turns available platform captions into an overview, chapters and key points. Install the local app and configure the model first. Missing captions are not replaced with audio transcription or video frame analysis.',
    sections: [
      { id: 'requirements', heading: 'Prepare captions and configure the model', paragraphs: [
        'The app attempts to fetch platform captions from Bilibili, Douyin and YouTube. Bilibili and YouTube have successful recorded examples; Douyin caption endpoints may deny access. These examples do not guarantee support for every video. Downloads remain available when captions fail.',
        'Put your own DEEPSEEK_API_KEY in the project-root .env file and restart the backend. Use .env.example as a template, not as a place to store a real key. Never put keys in the webpage, frontend or chat. You can also use .\\start-local.ps1 -AskDeepSeekKey for hidden terminal input.',
        'The default model provider is DeepSeek. Requests may incur account usage, with charges determined by the provider. The current workspace and structured summaries are primarily in Chinese; transcripts retain their source language.',
      ] },
      { id: 'automatic', heading: 'Automatically summarize after parsing', ordered: true, items: [
        'Paste a video URL, leave automatic summarization enabled and parse the video.',
        'Video metadata appears first while the backend fetches captions. Valid captions and a configured model allow summarization to continue. You can start downloading at the same time.',
        'Read the streamed draft and wait for the validated final summary. Draft text is provisional until the task completes.',
        'Saved summaries are reused. Turn automatic summarization off to fetch metadata and captions only, then request a summary manually when needed.',
      ] },
      { id: 'reading', heading: 'Check citations, explore the mind map and ask questions', paragraphs: [
        'The summary includes an overview, chapters and key points. Follow its references to the original captions and verify conclusions that matter. Server-side citation checks do not guarantee that every interpretation is correct.',
        'Explore the same summary in the mind-map tab, fold nodes and locate source text. Export the complete map as PNG or SVG. Ask questions in the Q&A tab for caption-grounded answers with references; each question can create new model usage.',
        'Export the summary as Markdown. The mind map uses the summary content, and Q&A does not inspect video frames.',
      ] },
      { id: 'recovery', heading: 'Saved results and recovery', questions: [
        { question: 'Does refreshing generate another summary?', answer: 'Saved results are reused, and an active backend task can be reconnected. Restoring history, changing caption languages and reconnecting a stream do not automatically start a new summary model request.' },
        { question: 'What happens after a failure or service restart?', answer: 'Read the error, resolve the caption, configuration or network problem, then retry manually. A restart interrupts unfinished tasks and does not automatically repeat a billed generation.' },
        { question: 'Does regenerating use the model again?', answer: 'Yes. Regeneration creates a new request, and citation repair can also add usage. A previous successful summary is retained if regeneration fails.' },
        { question: 'What are the default long-video limits?', answer: 'The default limits are two hours and 120,000 effective caption characters, with additional caption-resource and model-request size limits. Oversized inputs are rejected with an explanation rather than silently dropping the end of the video.' },
      ] },
    ],
  },
  {
    locale: 'zh', topic: 'subtitle-download',
    title: '字幕下载 - 完整SRT与TXT | SaveAny',
    description: '用 SaveAny 获取可用平台字幕，保留时间戳和原语言，导出完整 SRT 或 TXT。无需模型密钥或先生成 AI 总结。',
    keywords: ['字幕下载', 'SRT字幕', 'TXT字幕', '视频字幕导出', 'SaveAny'],
    heading: '如何下载完整 SRT 或 TXT 字幕',
    lead: '字幕下载适合保留课程原文、检索视频内容与整理阅读笔记。SaveAny 从支持的平台获取可用字幕，保留时间戳与原语言，导出不需要模型密钥或先生成 AI 摘要。',
    sections: [
      { id: 'fetch', heading: '获取平台字幕', ordered: true, items: [
        '安装并打开本机工具，粘贴 B 站、YouTube 或抖音视频链接。',
        '如果只需要字幕，先关闭“解析后自动总结”，再点击“解析视频”，等待字幕获取完成。',
        '切换到“字幕原文”，查看字幕语言、来源、时间戳及平台说明。',
      ], paragraphs: ['可用字幕由源站决定；抖音字幕接口可能受限。没有字幕时，当前版本不支持自动语音转录、字幕导入或画面识别。'] },
      { id: 'language', heading: '切换语言与搜索原文', paragraphs: [
        '源站提供多个字幕轨道时，可在语言选择器切换。获取另一语言会创建或复用对应字幕记录，不会把原字幕自动翻译，也不自动生成新的 AI 摘要。',
        '使用搜索和分页阅读长字幕，点击时间戳定位相关内容。字幕保留获取到的人工或自动轨道信息；自动字幕可能存在识别错误。',
      ] },
      { id: 'export', heading: '选择 SRT 或 TXT 并下载', table: { headers: ['格式', '内容', '适用场景'], rows: [
        ['SRT', '字幕序号、起止时间和文本', '需要时间轴的字幕播放器或编辑流程'],
        ['TXT', '带时间戳的原文', '阅读、搜索、整理笔记'],
      ] }, ordered: true, items: [
        '在字幕页的格式选择器选择 SRT 或 TXT。',
        '点击“下载字幕”，等待生成文件后保存到设备。',
        '检查文件内容与当前所选语言，按原视频核对自动字幕中的错误。',
      ], paragraphs: ['导出包含当前语言的全部字幕，不受当前搜索关键词、分页或页面上可见行数影响。'] },
      { id: 'questions', heading: '常见字幕问题', questions: [
        { question: '为什么视频能下载但没有字幕？', answer: '下载与字幕是独立能力。作者未提供字幕、登录权限不足或平台接口受限时，字幕获取可能失败，下载不一定受影响。' },
        { question: '导出字幕会调用 DeepSeek 吗？', answer: '不会。字幕获取与 SRT/TXT 导出不需要模型。如果解析时保持自动总结开启且已配置模型，有效字幕到位后可能接续总结，因此只取字幕时先关闭该开关。' },
        { question: '能自动翻译字幕吗？', answer: '当前没有字幕翻译功能。切换语言是在源站提供的轨道中选择，导出保留所选轨道的语言和时间戳。' },
        { question: '字幕和摘要文件有什么区别？', answer: 'SRT 和 TXT 保存字幕原文；Markdown 保存生成的总览、章节和知识点。下载字幕无需先生成摘要，Markdown 摘要导出需要已有成功摘要。' },
      ] },
    ],
  },
  {
    locale: 'en', topic: 'subtitle-download',
    title: 'Subtitle Downloads - Complete SRT & TXT | SaveAny',
    description: 'Export complete source-language captions as SRT or TXT without a model key.',
    keywords: ['subtitle download', 'SRT subtitles', 'TXT transcript', 'caption export', 'SaveAny'],
    heading: 'How to download complete SRT or TXT subtitles',
    lead: 'Save captions for lecture review, text search and reading notes. SaveAny retrieves available captions from supported platforms, keeps source-language text and timestamps, and exports them without requiring a model key or an AI summary.',
    sections: [
      { id: 'fetch', heading: 'Fetch available platform captions', ordered: true, items: [
        'Install and open the local app, then paste a Bilibili, YouTube or Douyin video URL.',
        'If you only want subtitles, turn automatic summarization off before parsing. Wait for caption retrieval to finish.',
        'Open the transcript tab, labeled “字幕原文”, to inspect the language, track source, timestamps and platform notes.',
      ], paragraphs: ['Caption availability depends on the source. Douyin endpoints may be restricted. The current version does not provide audio transcription, subtitle import or frame recognition when captions are missing.'] },
      { id: 'language', heading: 'Choose a language and search the transcript', paragraphs: [
        'When the source supplies several caption tracks, choose another language in the selector. This creates or reuses that caption record; it does not translate the original track or automatically generate another AI summary.',
        'Search and paginate through long transcripts, and use timestamps to locate relevant content. Track information distinguishes available manual and automatic captions. Automatic captions may contain recognition errors.',
      ] },
      { id: 'export', heading: 'Choose SRT or TXT and save the file', table: { headers: ['Format', 'Contents', 'Typical use'], rows: [
        ['SRT', 'Cue numbers, start/end times and text', 'Subtitle playback or editing workflows with a timeline'],
        ['TXT', 'Source transcript with timestamps', 'Reading, searching and note-taking'],
      ] }, ordered: true, items: [
        'Choose SRT or TXT in the subtitle format selector.',
        'Select “下载字幕” to download subtitles and save the generated file.',
        'Check the selected language and verify automatic-caption errors against the source video.',
      ], paragraphs: ['The export includes every caption in the selected language. Search filters, pagination and the number of visible rows do not reduce the exported transcript.'] },
      { id: 'questions', heading: 'Common subtitle questions', questions: [
        { question: 'Why can a downloadable video have no captions?', answer: 'Downloads and captions are separate capabilities. Captions may be missing, require additional source access or be blocked by an endpoint, while the video download still works.' },
        { question: 'Does subtitle export call DeepSeek?', answer: 'No. Caption retrieval and SRT/TXT exports do not require a model. If automatic summarization is enabled and a model is configured, valid captions can trigger a summary after parsing, so switch it off for a subtitles-only session.' },
        { question: 'Can the app translate subtitles automatically?', answer: 'Subtitle translation is not implemented. Language selection chooses a track supplied by the source. Exports retain that track’s language and timestamps.' },
        { question: 'How do subtitles differ from a summary export?', answer: 'SRT and TXT retain the caption text. Markdown contains the generated overview, chapters and key points. Caption export does not require a summary; a Markdown summary export requires a completed summary.' },
      ] },
    ],
  },
]
