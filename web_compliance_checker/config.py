"""
Web Compliance Checker - Unified Configuration
"""

import os
from typing import Dict, Any, List

def find_env_file() -> str:
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""

def load_env_vars() -> Dict[str, str]:
    env_map = {}
    env_path = find_env_file()
    if env_path and os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_map[k.strip()] = v.strip().strip("'\"")
        except Exception:
            pass
    return env_map

_ENV = load_env_vars()

# Database Settings
DB_CONFIG = {
    "host": _ENV.get("PG_HOST", os.getenv("PG_HOST", "202.194.101.181")),
    "port": int(_ENV.get("PG_PORT", os.getenv("PG_PORT", 5432))),
    "user": _ENV.get("PG_USER", os.getenv("PG_USER", "postgres")),
    "password": _ENV.get("PG_PASSWORD", os.getenv("PG_PASSWORD", "Cernet@2026")),
    "database": _ENV.get("PG_DATABASE", os.getenv("PG_DATABASE", "website_domain_db")),
    "task_table": "external_domains",
    "audit_table": "compliance_audit_logs",
    "timeout": 5,
}

# AI Engine Settings
AI_CONFIG = {
    "api_base": _ENV.get("AI_API_BASE", "http://192.168.1.190:8787/v1"),
    "model": _ENV.get("AI_MODEL", "XiaoAi"),
    "api_key": _ENV.get("AI_API_KEY", "EMPTY"),
    "timeout": 30,
    "temperature": 0.1,
}

# Multi-Device Emulation Presets
DEVICE_PROFILES: Dict[str, Dict[str, Any]] = {
    "desktop_chrome": {
        "name": "PC 桌面端 Chrome",
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "is_mobile": False,
        "device_scale_factor": 1,
    },
    "mobile_iphone_safari": {
        "name": "苹果 iPhone Safari",
        "viewport": {"width": 390, "height": 844},
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
        "is_mobile": True,
        "device_scale_factor": 3,
    },
    "desktop_mac_safari": {
        "name": "苹果 Mac Safari",
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "is_mobile": False,
        "device_scale_factor": 2,
    },
    "mobile_android_chrome": {
        "name": "安卓 Android Chrome",
        "viewport": {"width": 412, "height": 915},
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "is_mobile": True,
        "device_scale_factor": 2.625,
    },
}

DEVICE_PRESETS = {
    "dual": ["desktop_chrome", "mobile_iphone_safari"],
    "pc": ["desktop_chrome"],
    "full": ["desktop_chrome", "desktop_mac_safari", "mobile_iphone_safari", "mobile_android_chrome"],
}

# Scan & Probe Parameters
PROBE_CONFIG = {
    "http_timeout": 2.5,
    "dns_timeout": 1.2,
    "navigation_timeout": 12.0,
    "wait_after_load": 1.0,
    "max_scrolls": 1,
}

DEFAULT_WORKERS = 3
DEFAULT_BATCH_SIZE = 30
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "screenshots"), exist_ok=True)
