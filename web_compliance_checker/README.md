# 网站外部域名合规审计系统 (Web Compliance Inspector v2.0)

全新设计重构的**高并发多端仿真合规审计子系统**与**现代化 Web 监控大屏**。

集成 **Playwright 仿真渲染引擎** 与 **局域网超级小爱纯视觉大模型（XiaoAi Vision-Only）**，专为全网外链资产合规审计、暗链黑灰产排查及 Cloaking 双端伪装欺诈捕获打造。

---

## 核心设计与合规审计准则

### 1. 严格的业务处置原则（拒绝盲目盖章“安全”）
* **404 / 报错失效页面**：严格保持待研判记录（`verify_status = 'unverified'`，`risk_level = 'pending'`），记录 404 标签与错误快照，**绝不标记为安全（safe）**。
* **探活死链 / 无法解析**：严格保持待研判记录（`verify_status = 'unverified'`，`risk_level = 'pending'`）。
* **多端未见异常站点**：严格保持待研判记录（`verify_status = 'unverified'`，`risk_level = 'pending'`）。
* **确凿违规异常（重点处置）**：仅当检测到涉黄、涉赌、涉诈、暴恐、恶意广告、设备端伪装欺诈（Cloaking）或 SSRF 内网穿透时，系统才回写处置标记：
  * `verify_status = 'verified_failed'`
  * `risk_level = 'high'` / `'critical'`
  * 写入违规分类标签、研判理由与 SHA-256 数字存证。

### 2. 纯视觉大模型审核（Vision-Only）
* 彻底剥离让模型自行联网请求 URL 的错误模式；
* 本地小模型不具备 Agent 浏览能力，系统由 Playwright 仿真渲染截取首屏视口切片后，将高保真 Base64 图片直接送入多模态接口进行纯视觉审校。

### 3. 多端比对识破隐蔽 Cloaking 假面
* 支持 **PC Chrome (1920×1080)** 与 **iPhone Safari (390×844)** 双端同步渲染比对；
* 自动识破“桌面端展示正常企业或 404 报错，手机端跳转非法博彩/色情”的定向欺诈手法。

---

## 全新子系统工程架构

```text
web_compliance_checker/
├── config.py                 # 统一集中配置 (PostgreSQL、局域网 XiaoAi 模型、设备视口、超时参数)
├── db.py                     # PostgreSQL 数据库驱动层 (psycopg2 健壮直连、全指标统计、分页与合规回写)
├── prober.py                 # 极速 DNS (nslookup) 预检与轻量 HTTP 快速探活 (10ms 拦截 NXDOMAIN 与 SSRF)
├── capture.py                # Playwright 多端视口截图引擎 (支持 PC 桌面端与 iPhone 移动端防反爬仿真)
├── ai_vision.py              # 纯视觉大模型审核客户端 (对接 http://192.168.1.190:8787/v1 XiaoAi)
├── inspector.py              # 核心合规决策引擎 (跨端 Cloaking 判定、404/违规决策树、证据链组装)
├── runner.py                 # 异步后台批处理任务调度器 (并发受控、状态实时跟踪、日志流管道)
├── server.py                 # 现代化 Web 控制台后台 (提供 REST API 与静态资产分发)
├── compliance_checker.py     # 统一 CLI 命令行入口
├── dashboard_server.py       # 兼容启动入口 (直接指向 server.py)
├── ui/                       # 现代化前端界面 (完全独立解耦，拒绝单文件杂乱嵌合)
│   ├── index.html            # 响应式控制台页面 (4 大核心指标卡、Tabs 分类、灯箱与取证抽屉)
│   ├── app.js                # 响应式交互逻辑 (所有选项即时高亮反馈、实时状态轮询、即时诊断)
│   └── style.css             # 现代化样式表 (Segmented 按钮微动效、卡片发光)
└── output/                   # 产物存储目录
    └── screenshots/          # 取证高清截图 (按日期归档，含 SHA-256)
```

---

## 快速上手与操作指引

### 1. 启动 Web 监控与审计大屏（推荐）
在终端中执行：
```powershell
python web_compliance_checker/server.py 8888
# 或
python web_compliance_checker/dashboard_server.py
```
* **本机访问地址**：[http://localhost:8888](http://localhost:8888)
* **局域网访问地址**：[http://192.168.1.207:8888](http://192.168.1.207:8888)

### 2. Web 界面交互功能
1. **自动化多端巡检调度模态框**：
   * **仿真设备选型**：一键切换【双端智能比对 (PC + iPhone)】、【桌面 PC 单端极速】或【4 端全量仿真】，点击卡片立即展现深蓝发光高亮与选中勾选；
   * **并发工作线程数**：点击 `1`、`2`、`3 (推荐)`、`5`、`8` 即时高亮实心切换；
   * **单批次规模**：点击 `10`、`30 (推荐)`、`50`、`100` 即时高亮切换；
   * **AI 连通性测试**：一键测通 `http://192.168.1.190:8787/v1` 并回显真实毫秒延迟。
2. **单域名即时诊断**：
   * 点击右上角【🔍 单域名即时诊断】，输入如 `www.xgrsks.cn`，5 秒内完成现场双端渲染与大模型研判，并实时展示判定理由；
3. **资产大屏与处置抽屉**：
   * 4 大指标卡与分类 Tab：`全部`、`🚨 确凿违规`、`🎭 设备伪装`、`⚠️ 404失效`、`⏳ 待研判资产`；
   * 点击表格截图缩略图，弹出全屏原图灯箱；
   * 点击【👁️ 取证】，打开侧边抽屉对比 PC 与 iPhone 多端截图及大模型完整研判文本。

### 3. 命令行批处理巡检
```powershell
# 批量巡检待研判域名（并发 3，单批 30 条，双端比对）
python web_compliance_checker/compliance_checker.py --db --workers 3 --db-batch-size 30 --devices dual

# 单域名独立命令行审计
python web_compliance_checker/compliance_checker.py --domain www.xgrsks.cn
```
