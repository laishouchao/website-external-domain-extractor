"""
Configuration module for high-concurrency Web Compliance Checker.
Includes device profiles, compliance categories, audit prompts, and concurrency tuning constants.
"""

from typing import Dict, List, Any

# 预设设备配置文件
DEVICE_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "desktop_chrome",
        "name": "PC 桌面端 (Windows Chrome)",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False
    },
    {
        "id": "desktop_mac_safari",
        "name": "PC 桌面端 (macOS Safari)",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "viewport": {"width": 1440, "height": 900},
        "device_scale_factor": 2,
        "is_mobile": False,
        "has_touch": False
    },
    {
        "id": "mobile_iphone_safari",
        "name": "移动端 (iPhone 15 Pro Safari)",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 393, "height": 852},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True
    },
    {
        "id": "mobile_android_chrome",
        "name": "移动端 (Android / Chrome)",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True
    },
    {
        "id": "tablet_ipad",
        "name": "平板端 (iPad Pro)",
        "user_agent": "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 834, "height": 1194},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True
    }
]

# 违规审查分类体系
COMPLIANCE_CATEGORIES = [
    {
        "key": "pornography_vulgarity",
        "name_cn": "色情低俗",
        "description": "含有暴露裸露、性暗示、色情交易诱导、露骨成人内容或低俗擦边图像/文字。"
    },
    {
        "key": "gambling_lottery",
        "name_cn": "赌博博彩",
        "description": "含有线上赌场、真人视讯、百家乐、体育私彩、六合彩、赌球跑分或充值返利赌博宣传。"
    },
    {
        "key": "fraud_scam",
        "name_cn": "电信诈骗/黑灰产",
        "description": "杀猪盘、虚假兼职刷单、钓鱼假冒银行/官网、高利贷、非法集资、套现跑分等黑产内容。"
    },
    {
        "key": "violence_contraband",
        "name_cn": "暴恐违禁/违禁品",
        "description": "管制刀具、枪支弹药、爆炸品、毒品违禁药品、血腥暴力残忍画面、恐怖主义宣扬。"
    },
    {
        "key": "political_extremism",
        "name_cn": "涉政暴恐/不良言论",
        "description": "恶意造谣传谣、破坏国家统一、邪教迷信、煽动对抗等极端违法政治不良信息。"
    },
    {
        "key": "malicious_adware",
        "name_cn": "恶意广告/欺诈劫持",
        "description": "伪造系统病毒弹窗、强制诱导下载恶意APK/EXE、诱导点击遮罩层、暗链假提示。"
    }
]

# 并发与工程化架构默认调优参数
CONCURRENCY_CONFIG = {
    "default_browser_concurrency": 4,      # 最大并行渲染标签页/上下文数（防浏览器内存溢出）
    "default_llm_concurrency": 2,          # 最大并行大模型推理请求数（适配单卡/本地GPU算力）
    "page_navigation_timeout_ms": 25000,   # 单页面导航超时毫秒数
    "max_retries_per_url": 2,              # 针对偶发超时的重试次数
    "queue_max_size": 500                  # 内存管道缓冲队列最大深度
}

# 优化后的高精度 & 高效率审核系统 Prompt
SYSTEM_PROMPT = """你是一个专业的互联网网页合规安全视觉审核专家。你的任务是对输入的网页截图进行合规性判定，兼顾判定准确度与响应效率。

【六大违规判定标准与判定边界】
1. pornography_vulgarity (色情低俗):
   - 违规：露点裸露、露骨性动作、情色动漫、招嫖暗语、同城约炮引流。
   - 豁免：正规电商泳装/内衣展示、正规医疗解剖图、人体艺术雕塑不判违规。
2. gambling_lottery (赌博博彩):
   - 违规：真人视讯/百家乐、外围体育博彩、棋牌真钱提现、下注赔率盘口、送彩金返点。
   - 豁免：无真钱提现的休闲益智游戏、官方福彩体彩公益资讯不判违规。
3. fraud_scam (电信诈骗/黑灰产):
   - 违规：兼职刷单返佣、杀猪盘资金盘、虚假高收益投资、钓鱼假冒官网、跑分套现。
   - 豁免：正规持牌银行金融理财、合规企业招聘信息不判违规。
4. violence_contraband (暴恐违禁/违禁品):
   - 违规：枪支弹药、管制刀具、毒品精神管制药、血腥残忍自残、爆炸危险品。
   - 豁免：影视武侠道具、正规药品医疗科普不判违规。
5. political_extremism (涉政暴恐/不良言论):
   - 违规：邪教迷信、分裂国家言论、恶意造谣煽动群体对抗。
   - 豁免：官方新闻媒体、正规政务公开不判违规。
6. malicious_adware (恶意广告/欺诈劫持):
   - 违规：伪造“手机已中毒/内存严重不足”欺诈弹窗、暗链全屏遮罩、强制下载可疑安装包。
   - 豁免：页面常规商业品牌横幅广告不判违规。

【视觉审查重点】
重点扫描：网页顶部/底部悬浮条、弹窗、角落水印引流（Telegram/微信/QQ）、诱导点击按钮（如“立即提款”、“同城约”、“加导师”）。

【效率与输出约束】
- 必须严格输出纯 JSON 对象，首字符为 {，末字符为 }，禁止包含 Markdown 代码块或额外闲聊文字。
- 为保证推理效率，控制输出 Token：reason 字段限 12 字以内极短语；正常页面 violation_details 限 20 字以内；违规页面精确指出违规文案与位置。

【严格 JSON 格式】
{
  "is_violation": false,
  "risk_level": "SAFE",
  "confidence": 0.99,
  "primary_violation": "normal",
  "categories": [
    {"key": "pornography_vulgarity", "detected": false, "probability": 0.01, "reason": "无低俗裸露"},
    {"key": "gambling_lottery", "detected": false, "probability": 0.01, "reason": "无赌博盘口"},
    {"key": "fraud_scam", "detected": false, "probability": 0.01, "reason": "无诈骗刷单"},
    {"key": "violence_contraband", "detected": false, "probability": 0.01, "reason": "无暴恐违禁"},
    {"key": "political_extremism", "detected": false, "probability": 0.01, "reason": "无涉政不良"},
    {"key": "malicious_adware", "detected": false, "probability": 0.01, "reason": "无欺诈弹窗"}
  ],
  "violation_details": "内容合法健康",
  "visual_elements_found": ["导航栏", "正文", "页脚"]
}"""

USER_PROMPT = "审查此网页截图是否合规。依据违规标准与边界，严格以 JSON 返回判定结果："
