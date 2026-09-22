from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import asyncio
from app.db.database import init_db
from app.db.clickhouse import init_clickhouse
from app.db import crud
from app.api.tasks import router as tasks_router
from app.api.sitemap import router as sitemap_router
from app.api.domains import router as domains_router
from app.api.subdomains import router as subdomains_router
from app.api.global_domains import router as global_domains_router
from app.api.risk_profiles import router as risk_profiles_router
from app.api.risk_remediation import router as risk_remediation_router
from app.api.events import router as events_router
from app.crawler.risk_verifier import PeriodicRiskVerifier

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Database
    init_db()
    # Initialize ClickHouse in background thread
    asyncio.create_task(asyncio.to_thread(init_clickhouse))
    # Resume cleaning any dangling tasks stuck in 'deleting' status from previous runs
    asyncio.create_task(asyncio.to_thread(crud.purge_dangling_deleting_tasks))
    # Sync ticket statuses for already remediated / regressed records
    asyncio.create_task(asyncio.to_thread(crud.sync_existing_remediation_manual_statuses))
    # Start periodic risk page remediation verifier
    verifier = PeriodicRiskVerifier.get_instance()
    verifier.start()
    yield
    # Shutdown
    verifier.stop()

app = FastAPI(
    title="网站外部域名提取与全深度站点地图系统",
    description="自动扫描配置好的站点的所有深度的网站地图及提取所有页面的所有非本站域名（包含链接与非链接）",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(tasks_router)
app.include_router(sitemap_router)
app.include_router(domains_router)
app.include_router(subdomains_router)
app.include_router(global_domains_router)
app.include_router(risk_profiles_router)
app.include_router(risk_remediation_router)
app.include_router(events_router)

# Static files directory
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIST_DIR = STATIC_DIR / "dist"

# Mount /assets if Vite SPA build exists
if (STATIC_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIST_DIR / "assets")), name="spa_assets")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    if (STATIC_DIST_DIR / "index.html").exists():
        return FileResponse(str(STATIC_DIST_DIR / "index.html"))
    legacy_path = STATIC_DIR / "index.html"
    if legacy_path.exists():
        return FileResponse(str(legacy_path))
    return {"message": "Crawler API is running. UI not yet built."}

@app.get("/{full_path:path}")
async def serve_spa_fallback(full_path: str):
    # Pass through API requests or static requests if somehow unhandled
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("assets/"):
        return {"error": "Not Found", "path": full_path}

    if (STATIC_DIST_DIR / "index.html").exists():
        return FileResponse(str(STATIC_DIST_DIR / "index.html"))
    legacy_path = STATIC_DIR / "index.html"
    if legacy_path.exists():
        return FileResponse(str(legacy_path))
    return {"message": "Crawler API is running. UI not yet built."}
