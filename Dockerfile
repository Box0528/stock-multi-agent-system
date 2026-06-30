# 构建上下文必须是 Agent工程 的父目录（见 docker-compose.yml 的 build.context），
# 这样才能同时 COPY 到 Agent工程/ 和同级的 股市模型/data_downloader.py。

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY Agent工程/requirements-lock.txt /app/requirements-lock.txt
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY Agent工程/ /app/

# 原样复制独立下载器脚本（不修改其中任何 baostock 逻辑），
# 保持和本地一样的"同级目录"相对路径，对应 tools/data_pipeline.py 的 DOWNLOADER_SCRIPT
COPY 股市模型/data_downloader.py /股市模型/data_downloader.py

EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
