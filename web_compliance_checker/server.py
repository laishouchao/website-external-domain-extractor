"""
Web Compliance Checker - High-Performance Web Dashboard Server
Zero-dependency HTTP Server powering the modern compliance UI & REST APIs.
"""

import os
import sys
import json
import mimetypes
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import asyncio

from config import OUTPUT_DIR, DEVICE_PRESETS
from db import GLOBAL_DB
from runner import GLOBAL_RUNNER
from ai_vision import GLOBAL_AI_AUDITOR
from inspector import GLOBAL_INSPECTOR

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")

class DashboardRequestHandler(BaseHTTPRequestHandler):
    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, file_path: str):
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            self.send_error(404, "File Not Found")
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Root / UI Static Entry
        if path in ["/", "/dashboard", "/index.html"]:
            self.serve_file(os.path.join(UI_DIR, "index.html"))
            return

        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            self.serve_file(os.path.join(UI_DIR, rel_path))
            return

        if path.startswith("/output/"):
            rel_path = path[len("/output/"):]
            self.serve_file(os.path.join(OUTPUT_DIR, rel_path))
            return

        # 2. REST API: Statistics
        if path == "/api/stats":
            stats = GLOBAL_DB.get_stats()
            self.send_json(stats)
            return

        # 3. REST API: Domains List (Pagination & Filters)
        if path in ["/api/domains", "/api/tasks"]:
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["20"])[0])
            filter_type = query.get("filter", ["all"])[0]
            search_kw = query.get("search", [""])[0]

            res = GLOBAL_DB.fetch_domains(
                page=page,
                page_size=page_size,
                filter_type=filter_type,
                search_kw=search_kw
            )
            self.send_json(res)
            return

        # 4. REST API: Single Domain Detail
        if path.startswith("/api/domain/"):
            domain = urllib.parse.unquote(path[len("/api/domain/"):])
            item = GLOBAL_DB.fetch_single_domain(domain)
            if item:
                self.send_json(item)
            else:
                self.send_json({"error": "Domain not found"}, 404)
            return

        # 5. REST API: Scan Job Status (with backwards compatibility alias)
        if path in ["/api/scan/status", "/api/job/status"]:
            st = GLOBAL_RUNNER.get_status()
            self.send_json(st)
            return

        # 6. REST API: Test AI
        if path == "/api/test_ai":
            test_res = GLOBAL_AI_AUDITOR.test_connection()
            self.send_json(test_res)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}

        # 1. REST API: Start Scan
        if path in ["/api/scan/start", "/api/start_job"]:
            workers = int(data.get("workers", 3))
            batch_size = int(data.get("batch_size", 30))
            dev_preset = data.get("device_preset", "dual")
            devices = DEVICE_PRESETS.get(dev_preset, DEVICE_PRESETS["dual"])
            domain_filter = data.get("domain_filter", "")
            is_loop = bool(data.get("is_loop", False))
            is_dry_run = bool(data.get("is_dry_run", False))

            res = GLOBAL_RUNNER.start(
                workers=workers,
                batch_size=batch_size,
                devices=devices,
                domain_filter=domain_filter,
                is_loop=is_loop,
                is_dry_run=is_dry_run
            )
            self.send_json(res)
            return

        # 2. REST API: Stop Scan
        if path in ["/api/scan/stop", "/api/stop_job"]:
            GLOBAL_RUNNER.stop()
            self.send_json({"ok": True, "message": "已向巡检引擎发送停止指令"})
            return

        # 3. REST API: Instant Single Domain Audit
        if path == "/api/audit/single":
            domain = data.get("domain", "").strip()
            if not domain:
                self.send_json({"error": "domain is required"}, 400)
                return

            dev_keys = data.get("devices") or DEVICE_PRESETS["dual"]
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(
                    GLOBAL_INSPECTOR.inspect(domain=domain, devices=dev_keys)
                )
                loop.close()
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        # 4. REST API: Remediate Legacy Clean Records
        if path == "/api/remediate_legacy":
            updated_count = GLOBAL_DB.remediate_legacy_clean()
            self.send_json({"ok": True, "updated": updated_count})
            return

        self.send_error(404, "Not Found")

def run_server(host: str = "0.0.0.0", port: int = 8888):
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    print("=" * 60)
    print("  Web Compliance Checker - 现代化合规审计控制台")
    print(f"  服务启动成功: http://localhost:{port}")
    print(f"  局域网访问地址: http://192.168.1.207:{port}")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
        server.server_close()

if __name__ == "__main__":
    port = 8888
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port=port)
