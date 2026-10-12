# ==============================================================================
# 网站外部域名提取与全深度网站地图系统 - Dockerfile
# ==============================================================================
FROM python:3.11-slim

# 设置工作目录与环境
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 安装系统级依赖库（PostgreSQL 驱动构建依赖、时区支持、健康检查工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 复制系统源码及预编译前端产物
COPY . /app/

# 创建持久化数据目录
RUN mkdir -p /app/data

# 暴露服务端口
EXPOSE 8000

# 容器健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# 启动命令 (支持单进程快速启动或 Gunicorn 多 Worker 启动)
CMD ["python", "run.py"]
