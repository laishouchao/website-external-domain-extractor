from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db.database import init_db
from app.api.tasks import router as tasks_router
from app.api.sitemap import router as sitemap_router
from app.api.domains import router as domains_router
from app.api.subdomains import router as subdomains_router
from app.api.global_domains import router as global_domains_router
from app.api.risk_profiles import router as risk_profiles_router
from app.api.events import router as events_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Database
    init_db()
    yield
    # Shutdown

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
app.include_router(events_router)

# Static files directory
STATIC_DIR = Path(__file__).resolve().parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Crawler API is running. UI index.html not yet installed."}
