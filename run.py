import multiprocessing as mp
import uvicorn
from app.config import HOST, PORT

if __name__ == "__main__":
    mp.freeze_support()
    print(f"===============================================================")
    print(f"  网站外部域名提取与全深度网站地图系统 正在启动...")
    print(f"  访问地址: http://localhost:{PORT}")
    print(f"===============================================================")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
