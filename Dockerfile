# ── Stage 1: Build React frontend ────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend-react/package*.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend-react/ ./
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 换成阿里云 apt 源，国内速度快
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt /app/requirements-lock.txt
# 换成清华 pip 源
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-lock.txt

COPY . /app/
# Copy built React dist from Stage 1
COPY --from=frontend-builder /frontend/dist /app/frontend-react/dist

EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
