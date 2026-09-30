# Web Compliance Checker (高并发工程化多端合规审查系统)

基于 **异步浏览器常驻池（Playwright Async Browser Pool）** 与 **本地多模态大模型（VLM）** 构建的高性能网页安全巡检系统。

本系统针对网络黑灰产（涉黄、涉赌、涉诈、暴恐、涉政违禁、恶意广告）演化出的**“设备端伪装欺诈（Cloaking）”**策略，利用高并发多端仿真模拟（涵盖 PC 桌面端、Retina 屏、iPhone 移动端、Android 移动端及 iPad 平板端）并结合延迟动态渲染截屏与数字证据存证（SHA-256），调用本地部署的多模态视觉大模型（如 Qwen2.5-VL、Qwen2-VL、LLaVA、MiniCPM-V 等）完成自动化安全审查，并以标准 JSON/流式 JSONL 输出。

---

## 架构升级与核心特性

### 1. 异步浏览器池化架构 (Async Browser Pool)
- **进程常驻与上下文复用**：彻底摈弃每次审核冷启动 Chromium 的传统方式，常驻单个浏览器进程，按需派发轻量级的 `BrowserContext`，性能提升 **3 ~ 5 倍**，资源回收率 100%。
- **硬件保护与并发限制**：通过异步信号量（`Semaphore`）限制浏览器最大渲染标签页数（默认 4 并发），防止页面过多导致宿主系统内存暴涨。
- **反反爬避障 (Stealth)**：自动注入 `playwright-stealth` 防检测抹平指纹特征。

### 2. GPU 算力削峰防爆保护 (GPU-Bounded LLM Inference)
- 本地多模态大模型在显存中推理属于显存密集型任务。系统内置模型并发调度器（`--concurrency-llm`，默认 2 并发），在大规模批量爬取网页截图时对推理请求进行削峰平谷，避免本地 GPU 显存 OOM 或服务端返回 503 拥堵。

### 3. 多端仿真与对抗“设备端伪装”（Anti-Cloaking）
- 针对部分黑产网站“PC 端正常、手机端跳转境外博彩”的手法，针对同一 URL 异步并发使用多种 UA、视口分辨率、触控配置与缩放比例。
- 自动进行多端结论交叉对比，触发设备伪装告警（`cloaking_suspected: true`）并自动升阶最高风险等级。

### 4. 电子存证与网络溯源 (Forensics)
- 截图保存时自动计算 **SHA-256** 哈希值，不可伪造篡改。
- 完整记录初始 URL、最终跳转 URL（`final_url`）及 HTTP 响应状态码，有效追踪 302 恶意跳转链。

### 5. 流式持久化与批处理防崩 (Streaming JSONL)
- 支持单 URL 审查与万级 URL 文件批量导入（`--file urls.txt`）。
- 实时采用 **JSONL（JSON Lines）** 增量流式落盘，即使遇到断电或异常终止，已完成的检测记录分秒不丢。

---

## 项目工程结构

```text
web_compliance_checker/
├── browser_pool.py         # 异步浏览器常驻池与 Context 生命周期隔离
├── async_screenshot.py     # 异步多端延时截图、平滑滚动、SHA-256 存证与重试机制
├── async_llm_analyzer.py   # 异步多模态模型交互客户端（GPU 并发受控、JSON 鲁棒解析）
├── pipeline.py             # 生产者-消费者流式巡检流水线与 Cloaking 跨端聚合
├── compliance_checker.py   # CLI 命令行主程序（支持单目标与批量文件巡检）
├── config.py               # 设备 Profiles、违规维度标准与审查 Prompt
├── sample_urls.txt         # 批量巡检示例 URL 文本
└── output/                 # 产物存储目录
    ├── screenshots/        # 存证截图 (PNG，含哈希)
    ├── batch_results_*.jsonl # 流式实时输出记录
    └── batch_summary_*.json # 批量汇总评估报告
```

---

## 快速上手与使用示例

### 1. 单目标快速审查
```powershell
python compliance_checker.py https://example.com
```

### 2. 批量 URL 导入巡检（推荐）
在 `sample_urls.txt` 中写入待查网址（每行一个），执行：
```powershell
python compliance_checker.py --file sample_urls.txt
```

### 3. 高并发参数调优与本地模型指定
以本地 vLLM 或 Ollama 部署的 `Qwen2.5-VL-7B` 为例：
```powershell
python compliance_checker.py --file sample_urls.txt `
  --api-base http://localhost:8000/v1 `
  --model Qwen/Qwen2.5-VL-7B-Instruct `
  --concurrency-browser 6 `
  --concurrency-llm 2 `
  --delay 2.5
```

### 4. 离线仿真测试模式（验证全链路无需启动模型）
```powershell
python compliance_checker.py --file sample_urls.txt --mock
```

---

## 命令行参数详表

| 参数 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `urls` / `--url` | 字符串 | 无 | 单个或多个待测目标 URL |
| `--file`, `-f` | 路径 | 无 | 待审核 URL 文本文件路径（每行一个） |
| `--delay` | 浮点数 | `3.0` | 页面加载后的延迟等待秒数（等待异步 JS 与跳转） |
| `--api-base` | 字符串 | `http://localhost:11434/v1` | 本地多模态模型服务地址 |
| `--model` | 字符串 | `qwen2-vl` | 模型名称 (如 `qwen2.5-vl`, `qwen2-vl`) |
| `--concurrency-browser`| 整数 | `4` | 浏览器池最大并行渲染标签页数 |
| `--concurrency-llm` | 整数 | `2` | 模型推理最大并发请求数（保护本地显存） |
| `--db` | 开关 | 否 | 启用数据库驱动模式（从数据库读取待巡检域名并将结果回写入库） |
| `--db-config` | 路径 | `db_config.json` | 数据库连接配置文件路径 |
| `--db-source` | 选项 | `postgres` | 待测域名的提取源数据库（`postgres` 或 `clickhouse`） |
| `--db-sink` | 选项 | `both` | 审核结果回写目标数据库（`postgres`、`clickhouse` 或 `both`） |
| `--db-batch-size`| 整数 | `50` | 单次提取的待测任务批次量 |
| `--db-loop` | 开关 | 否 | 启用常驻轮询守护进程（持续监听库中新任务） |
| `--db-poll-interval`| 整数| `10` | 轮询模式下库中无新任务时的休眠秒数 |
| `--db-init` | 开关 | 否 | 自动在 PostgreSQL 与 ClickHouse 中建表 |
| `--task-id` | 整数 | 无 | 仅提取指定主任务 ID 的外部域名（对应 `external_domains.task_id`） |
| `--target-table` | 字符串 | `external_domains` | 源任务表名（支持 `external_domains`、`risk_page_remediations` 等） |
| `--target-field` | 选项 | `domain` | 巡检目标字段（`domain` 访问 `https://{domain}`，`sample_page_url` 访问溯源采样页） |
| `--risk-level` | 字符串 | 无 | 按风险等级筛选（如 `pending`, `high`, `safe` 或 `all`） |
| `--verify-status`| 字符串 | 无 | 按研判状态筛选（如 `unverified`, `verified_clean`, `verified_failed` 或 `all`） |
| `--domain-filter`| 字符串 | 无 | 按域名关键字模糊筛选（如 `qq.com`） |
| `--dry-run` | 开关 | 否 | 仅从数据库检索并打印匹配的域名任务清单，不执行爬虫和模型推理 |
| `--slices` | 整数 | `1` | 单设备分屏切片数（`1`=仅首屏，`2`=首屏+页底，`3`=首屏+中部+页底，各切片均保持原始高分辨率） |
| `--max-height` | 整数 | `2500` | 整页截图模式下的智能高度截断阈值（px，防止万像素大图压缩失真） |
| `--full-page` | 开关 | 否 | 是否捕获页面完整长截图（受 `--max-height` 保护） |
| `--no-headless`| 开关 | 否 | 显示浏览器窗口进行可视化调试 |
| `--mock` | 开关 | 否 | 开启仿真审核模式（跳过真实模型推理） |
| `--quiet` | 开关 | 否 | 静默模式，控制台仅输出最终 JSON |

---

## 数据库集成与自动化调用 (适配当前系统库 website_domain_db)

系统已深度适配主系统的 **PostgreSQL** 与 **ClickHouse** 数据库，能够直接调度审查主系统 `external_domains` 外部域名库，并将 VLM 审核结论实时回写至主系统及存证日志表：

### 1. 数据库配置 (`db_config.json`)
默认已连接至当前系统的 PostgreSQL 与 ClickHouse（`website_domain_db`）：
```json
{
  "postgres": {
    "enabled": true,
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "your_password",
    "database": "website_domain_db",
    "task_table": "external_domains",
    "audit_table": "compliance_audit_logs"
  },
  "clickhouse": {
    "enabled": true,
    "host": "localhost",
    "port": 8123,
    "user": "default",
    "password": "your_password",
    "database": "website_domain_db",
    "task_table": "external_domains",
    "audit_table": "compliance_audit_events"
  },
  "default_source": "postgres",
  "default_sink": "both",
  "batch_size": 50,
  "poll_interval_seconds": 10,
  "target_field": "domain"
}
```

### 2. 字段映射与回写机制
- **任务读取**：从 `external_domains` 读取 `id, task_id, domain, sample_page_url, risk_level, verify_status`。
- **目标构造**：默认构造 `https://{domain}`，亦可通过 `--target-field sample_page_url` 审查外链引用页。
- **结果回写**：
  - `risk_level`：映射为小写标准等级（`critical`、`high`、`medium`、`low`、`safe`）。
  - `risk_tags`：格式化为包含判定类别与 Cloaking 标识的 JSON 数组（如 `["赌博博彩", "设备伪装(Cloaking)"]`）。
  - `risk_remark`：详细分析理由与设备端伪装说明。
  - `risk_source`：标记为 `'ai_compliance'`（保留用户手动判定的优先级）。
  - `verify_status`：违规更新为 `'verified_failed'`，合规安全更新为 `'verified_clean'`。
  - `verify_time`：当前更新时间戳。
  - `verify_detail`：生成与前端弹窗 `showVerifyReport` 100% 兼容的完整证据 JSON。
  - **存证审计**：在 `compliance_audit_logs` (PostgreSQL) 与 `compliance_audit_events` (ClickHouse) 中记录多端截图哈希、模型输出及分类置信度。

### 3. 常用命令行示例

```powershell
# 1. 预检模式：查看当前待检测的外部域名清单 (不执行爬虫与模型)
python compliance_checker.py --db --dry-run --db-batch-size 10

# 2. 仅检查指定任务 (如 task_id = 93) 中待判定的外部域名
python compliance_checker.py --db --task-id 93 --db-batch-size 20

# 3. 仅检查特定域名关键字
python compliance_checker.py --db --domain-filter qq.com --dry-run

# 4. 离线仿真测试 (跳过真实大模型调用，用于全链路冒烟测试)
python compliance_checker.py --db --db-batch-size 5 --mock

# 5. 真实生产大模型巡检 (使用本地部署的 Qwen2-VL)
python compliance_checker.py --db `
  --api-base http://localhost:11434/v1 `
  --model qwen2-vl `
  --concurrency-browser 4 `
  --concurrency-llm 2 `
  --db-batch-size 50

# 6. 启动 24/7 常驻轮询守护进程（持续监听库中新增 pending/unverified 外部域名）
python compliance_checker.py --db --db-loop --db-poll-interval 15
```

## 输出数据规范示例

### 1. 流式 JSONL 单条记录规范 (batch_results_*.jsonl)
```json
{
  "url": "https://example.com",
  "checked_at": "2026-09-28T14:58:00.000000+00:00",
  "model_used": "qwen2-vl",
  "verdict_summary": {
    "is_violation": true,
    "overall_risk_level": "HIGH",
    "primary_violation_category": "gambling_lottery",
    "cloaking_suspected": true,
    "cloaking_notes": "检测到设备端伪装：PC端页面正常，但移动端UA下检测到违规违法内容！",
    "category_probabilities": {
      "pornography_vulgarity": { "name": "色情低俗", "max_probability": 0.05, "is_detected": false },
      "gambling_lottery": { "name": "赌博博彩", "max_probability": 0.96, "is_detected": true },
      "fraud_scam": { "name": "电信诈骗/黑灰产", "max_probability": 0.08, "is_detected": false },
      "violence_contraband": { "name": "暴恐违禁/违禁品", "max_probability": 0.01, "is_detected": false },
      "political_extremism": { "name": "涉政暴恐/不良言论", "max_probability": 0.0, "is_detected": false },
      "malicious_adware": { "name": "恶意广告/欺诈劫持", "max_probability": 0.15, "is_detected": false }
    },
    "stats": { "total_tested_devices": 2, "successful_captures": 2, "violation_device_count": 1 }
  },
  "device_inspections": [
    {
      "device_id": "mobile_iphone_safari",
      "device_name": "移动端 (iPhone 15 Pro Safari)",
      "is_mobile": true,
      "viewport": { "width": 393, "height": 852 },
      "final_url": "https://example.com/mobile-vip",
      "http_status": 200,
      "capture_status": "success",
      "screenshot_path": "C:\\...\\output\\screenshots\\example_mobile_iphone_safari.png",
      "screenshot_sha256": "3a7b1c4e9f...",
      "is_violation": true,
      "risk_level": "HIGH",
      "confidence": 0.95,
      "primary_violation": "gambling_lottery",
      "categories": [
        { "key": "gambling_lottery", "detected": true, "probability": 0.96, "reason": "检测到真人发牌画面及百家乐下注充值入口" }
      ],
      "violation_details": "移动端页面呈现网络赌场投注界面",
      "visual_elements_found": ["百家乐赌桌", "投注赔率表", "充值入口"]
    }
  ]
}
```
