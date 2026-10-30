# ============================================================
# 学生公寓报修系统（含 AI 助手）—— 应用镜像
# 基础镜像选 3.11：chromadb / onnxruntime 在 3.11 上有稳定 wheel，
# requirements.txt 里也写了 3.13 常缺 wheel 的提醒。
# ============================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# libgomp1：onnxruntime（chromadb 的传递依赖）运行时要加载 libgomp.so.1，
#           slim 镜像里默认没有，缺了会在 import chromadb 时报找不到共享库。
# curl：只给 HEALTHCHECK 用。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 tzdata curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只拷依赖清单再装包：改代码时这一层能命中缓存，不必重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷项目本体。ai/chroma_db（约 800KB）一并进镜像，
# 这样容器起来就能问答，不必依赖构建期有没有 API Key。
COPY . .

RUN mkdir -p /app/static/uploads \
    && chmod +x /app/docker/entrypoint.sh

EXPOSE 5000

# 首页能返回 200 就算健康；不探 AI 接口，避免把额度消耗在健康检查上
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/ >/dev/null || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
