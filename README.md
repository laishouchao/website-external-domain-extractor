# 网站全深度网站地图扫描与外部域名（链接+文本代码）提取系统

一套高效、精准的自动化网站全深度爬虫与外部依赖域名探测分析系统。系统能够自动对目标站点进行全深度递归遍历，生成完整站点的网站地图（Sitemap），并对抓取到的每一个页面进行深度语义与代码解析，全量提取出所有非本站的外部域名（涵盖所有 HTML 链接属性以及纯文本、脚本代码、注释中的非链接形式裸域名），支持实时监控、上下文溯源与多格式导出。

---

## 🌟 核心功能特性

### 1. 全深度网站地图扫描 (Deep Sitemap Scanner)
- **广度优先递归爬取**：从目标起始 URL 开始，自动发现内链并逐层遍历，支持最大深度与页面上限配置。
- **站点地图预探测**：自动嗅探并解析目标站点的 `/robots.txt`、`/sitemap.xml` 及 `/sitemap_index.xml`，提前预热待爬队列。
- **智能范围隔离 (Scope Filtering)**：
  - **全主根域名模式（推荐）**：例如目标为 `example.com`，所有 `*.example.com` 子域名均被视为本站内链继续探测，其他任何第三方域名一律判定为外部域名。
  - **精确主机名模式**：仅当前主机名（如 `blog.example.com`）判定为本站，其他所有子域和外域均判定为外部域名。
- **URL 规范化与去重**：自动清洗锚点 `#frag`、过滤非 HTTP 伪协议（`mailto:`, `javascript:`, `tel:`），去除重复页面。
- **高性能异步协程**：基于 `asyncio` 与 `httpx.AsyncClient`，支持可控并发（如 5~10 并发协程）与请求延迟（Polite Crawling），保障爬取效率与目标服务器友好性。
- **Sitemap 导出**：支持一键导出符合搜索引擎标准的 XML 格式网站地图 (`sitemap.xml`) 及全站页面列表 CSV。

### 2. 全量外部域名提取引擎 (Link & Non-Link Extraction)
- **链接型外部域名提取**：
  - 页面跳转与超链接：`<a>`, `<area>` (`href`)
  - 媒体与资源：`<img>`, `<video>`, `<audio>`, `<source>`, `<track>` (`src`, `data-src`)
  - 脚本与样式表：`<script src="...">`, `<link href="...">`, CSS `@import` 及 `url(...)`
  - 框架与表单交互：`<iframe>`, `<frame>`, `<form action="...">`, `<object data="...">`, `<embed src="...">`
- **非链接型外部域名提取**：
  - 正文纯文本（如版权声明、技术支持合作方网址、邮箱域名等）
  - `<script>` 变量与内嵌代码（如前端配置的 API 接口基地址 `const apiUrl = "https://api.thirdparty.com"`）
  - HTML 注释（如运维与开发人员遗留的测试域名、内网域名、备份节点备注等）
- **精准过滤与假阳性排除**：
  - 基于 Mozilla **Public Suffix List (tldextract)** 判定合法的顶级域名与公共后缀。
  - **黑名单阻断机制**：强力过滤常见静态资源后缀（如 `.png`, `.jpg`, `.css`, `.js`, `.vue`, `.ts`, `.json`, `.map` 等）以及版本号（如 `1.0.0`）、IP 地址（如 `192.168.1.1`）、保留域（`localhost`），杜绝误判。

### 3. 上下文穿透与证据链溯源 (Provenance & Evidence)
- 系统不仅汇总外部域名列表，更记录每个域名**在哪个页面被发现**、**属于何种类型（链接/代码/文本/注释）**、**原始匹配字符串**以及**上下文代码证据片段（Context Snippet）**。
- 在前端界面点击任意外部域名，即可弹出抽屉查看详尽的证据溯源记录。

### 4. 实时控制台与交互面板 (Modern Web Dashboard)
- **实时事件推送 (SSE)**：通过 Server-Sent Events 流式推流当前抓取页面 URL、HTTP 响应码、耗时与终端日志。
- **任务生命周期控制**：支持实时启动、暂停、继续、停止、重置重新扫描、一键删除。
- **多维度统计看板**：可视化展示 Top 10 外部顶级主域名分布、独立域名总数、链接与非链接比例。
- **多格式导出能力**：
  - **TXT 格式**：纯外部域名列表（每行一个，已去重），可直接作为防火墙阻断、威胁情报或资产梳理输入。
  - **CSV 格式**：包含域名、根域、频次、来源标签、首次发现页面。
  - **JSON 格式**：包含任务元数据及全量结构化域名数据。
  - **XML 格式**：标准 XML 格式站点地图。

---

## 🚀 快速启动指南

### 环境要求
- Python 3.9+
- 推荐使用已配置的 Python 环境（如 MiniConda）

### 依赖安装
如果需要全新安装依赖，执行：
```bash
pip install -r requirements.txt
```

### 启动服务
#### 方式一：Windows 双击启动
直接双击运行项目根目录下的 `start.bat` 即可自动调用 Python 启动服务。

#### 方式二：命令行启动
```bash
python run.py
```
启动成功后，控制台会输出：
```text
===============================================================
  网站外部域名提取与全深度网站地图系统 正在启动...
  访问地址: http://localhost:8000
===============================================================
```

打开浏览器访问：**http://localhost:8000** 即可进入现代化 Web 系统。

---

## 📖 使用操作步骤

1. **新建任务**：
   - 点击右上角 **“+ 新建扫描任务”**。
   - 输入任务名称（如 `某系统外部域名扫描`）及目标站点 URL（如 `https://example.com`）。
   - 根据需要调整最大深度（0 为不限）、页面上限（0 为不限）和并发协程数。
   - 展开高级设置可选择【主根域名模式】或【精确主机名模式】、是否开启非链接文本提取等。
2. **实时监控**：
   - 创建成功后系统自动启动扫描，进入任务工作台。
   - 在【实时监控与日志】选项卡中可查看实时滚动的爬虫终端日志和正在抓取的 URL。
3. **查看外部域名**：
   - 切换到【提取外部域名全集】选项卡，查看系统实时提取的非本站域名列表。
   - 可按关键字搜索，按“仅链接属性”或“仅文本代码”进行筛选。
   - 点击右侧 **“🔍 查看证据”** 按钮，查看该域名在哪些网页出现及上下文代码片段。
4. **浏览网站地图**：
   - 切换到【全深度网站地图】选项卡，查看爬虫探测到的全站页面、深度层级、状态码及耗时。
5. **一键导出结果**：
   - 点击导出按钮，即可一键下载 TXT、CSV、JSON 域名文件或标准 XML 网站地图。

---

## 🛠️ 项目目录结构

```
e:\SOLO\网站外部域名提取系统\
├── app/
│   ├── __init__.py
│   ├── config.py              # 全局配置（默认深度、并发、数据库路径等）
│   ├── main.py                # FastAPI 应用主入口、静态托管与路由组装
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py        # PostgreSQL 原生连接池、GIN 倒排索引与表结构初始化
│   │   └── crud.py            # 任务、页面、外部域名、日志 CRUD 操作
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── engine.py          # 异步爬虫调度引擎（广度优先队列、状态流转）
│   │   ├── worker.py          # 异步请求抓取器、sitemap.xml 预探测
│   │   ├── extractor.py       # 核心提取器：全属性链接提取 + 文本代码裸域名正则解析
│   │   └── risk_verifier.py   # 10分钟涉险页面自动巡检复测引擎
│   ├── api/
│   │   ├── __init__.py
│   │   ├── tasks.py           # 扫描任务增删改查、启动/暂停/停止/重试控制
│   │   ├── sitemap.py         # 网站地图页面列表查询与 XML/CSV 导出
│   │   ├── domains.py         # 外部域名列表、证据穿透、统计与 TXT/CSV/JSON 导出
│   │   ├── subdomains.py      # 本站扩展子域名接口
│   │   ├── global_domains.py  # 全网外部域名知识库与跨任务关联
│   │   ├── risk_remediation.py# 风险页面整改工作台与闭环复测
│   │   ├── risk_profiles.py   # 威胁情报规则库与全库回溯
│   │   └── events.py          # SSE 实时日志与进度广播流
│   └── static/
│       └── dist/              # Vite 5 构建产物（离线自包含 SPA 前端）
├── frontend/                  # 现代化工程化 Vue 3 SPA 前端源码
│   ├── src/
│   │   ├── api/client.js      # Axios 接口封装
│   │   ├── stores/            # Pinia 状态管理 (tasks, globalDomains, remediation, threatIntel, ui)
│   │   ├── components/        # 公共组件 (RiskBadge, StatusBadge, Drawer, Modal, CodeSnippet, Toast)
│   │   ├── views/             # 核心视图 (Dashboard, Tasks, TaskDetail, GlobalDomains, Remediation, ThreatIntel, Settings)
│   │   └── router/            # Vue Router 路由表
│   ├── vite.config.js         # Vite 5 构建配置
│   ├── tailwind.config.js     # Tailwind CSS 离线样式系统
│   └── package.json           # 前端依赖包配置
├── .env.example               # 环境与数据库配置模板
├── run.py                     # 后端服务启动入口
├── start.bat                  # Windows 快捷批处理启动脚本
├── requirements.txt           # 项目 Python 依赖库
└── README.md                  # 系统说明文档
```

### 前端开发与构建
如需修改前端界面：
```bash
cd frontend
npm install       # 安装依赖
npm run dev       # 启动前端开发调试服务器 (http://localhost:3000)
npm run build     # 编译生成生产包到 app/static/dist/
```

