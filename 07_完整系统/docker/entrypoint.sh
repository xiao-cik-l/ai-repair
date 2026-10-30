#!/bin/sh
# ============================================================
# 容器启动脚本：等待数据库 -> 补建表 -> 初始化演示账号 -> 检查向量库 -> 起服务
# 每一步失败都会打印明确原因，避免容器静默退出后无从排查。
# ============================================================
set -eu

log() { echo "[entrypoint] $*"; }

: "${MYSQL_HOST:=db}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_DB:=cjl_505}"
export MYSQL_HOST MYSQL_PORT MYSQL_DB

# ---------- 1. 等数据库就绪 ----------
# compose 的 healthcheck 已经挡了一层，这里再兜一层：
# 一是 healthcheck 有 start_period，二是单独 docker run 时没有 depends_on。
log "等待 MySQL ${MYSQL_HOST}:${MYSQL_PORT} ..."
python - <<'PY'
import os
import sys
import time

import pymysql

host = os.environ["MYSQL_HOST"]
port = int(os.environ["MYSQL_PORT"])
user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "")

for attempt in range(60):
    try:
        conn = pymysql.connect(host=host, port=port, user=user,
                               password=password, connect_timeout=3)
        conn.close()
        print("[entrypoint] MySQL 已就绪")
        break
    except Exception as exc:                      # 首次启动 MySQL 要初始化几分钟
        if attempt % 5 == 0:
            print("[entrypoint] 第 %d 次连接失败：%s" % (attempt + 1, exc))
        time.sleep(2)
else:
    sys.exit("[entrypoint] 60 次重试后仍连不上 MySQL，退出")
PY

# ---------- 2. 表结构自愈 ----------
# mysql 镜像只会在数据卷为空时执行 /docker-entrypoint-initdb.d 里的脚本。
# 如果数据卷是旧的、或首次初始化被打断，表可能不存在，这里补一次。
log "检查表结构 ..."
python - <<'PY'
import io
import os

import pymysql

db = os.environ["MYSQL_DB"]
conn = pymysql.connect(host=os.environ["MYSQL_HOST"],
                       port=int(os.environ["MYSQL_PORT"]),
                       user=os.getenv("MYSQL_USER", "root"),
                       password=os.getenv("MYSQL_PASSWORD", ""),
                       database=db, charset="utf8mb4", autocommit=True)
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = 'students'", (db,))
        if cur.fetchone()[0]:
            print("[entrypoint] 表结构已存在，跳过建表")
        else:
            raw = io.open("schema_mysql.sql", encoding="utf-8").read()
            # 去掉 -- 注释行再按分号切；本脚本里没有存储过程，切分是安全的
            body = "\n".join(ln for ln in raw.splitlines()
                             if not ln.strip().startswith("--"))
            stmts = [s.strip() for s in body.split(";") if s.strip()]
            for stmt in stmts:
                cur.execute(stmt)
            print("[entrypoint] 已按 schema_mysql.sql 建表，语句数 %d" % len(stmts))
finally:
    conn.close()
PY

# ---------- 3. 演示账号 ----------
# 用 INSERT IGNORE：已存在的行不会被覆盖，重复执行也安全。
log "初始化演示账号 ..."
python -c "from db import init_db; init_db()"

# ---------- 4. 向量库 ----------
# 镜像里已经带了 ai/chroma_db。只有从仓库构建、或挂空卷覆盖时才需要现灌。
if [ -f ai/chroma_db/chroma.sqlite3 ]; then
    log "向量库已存在，跳过灌库"
elif [ -n "${DASHSCOPE_API_KEY:-}" ]; then
    log "向量库缺失，开始灌入 20 条维修 FAQ ..."
    python ai/rag/faq_kb.py || log "灌库失败，AI 检索问答会不可用，普通报修流程不受影响"
else
    log "向量库缺失且未提供 DASHSCOPE_API_KEY，AI 检索问答会不可用"
fi

# ---------- 5. 邮件配置体检 ----------
if [ -z "${SMTP_PASSWORD:-}" ]; then
    if [ "${DEMO_LOGIN_CODE:-0}" = "1" ]; then
        log "未配置 SMTP_PASSWORD，已启用演示模式：验证码会打印在本日志里"
    else
        log "警告：未配置 SMTP_PASSWORD，登录收不到验证码；临时演示可设 DEMO_LOGIN_CODE=1"
    fi
fi

if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
    log "警告：未配置 DASHSCOPE_API_KEY，AI 助手会返回调用失败"
fi

# ---------- 6. 启动 ----------
# gthread 而非默认 sync：SSE 流式回答会长时间占用连接，
# sync worker 会被一条流堵住，gthread 让同一进程内的线程继续接新请求。
log "启动 gunicorn 0.0.0.0:5000 ..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class gthread \
    --workers "${WEB_WORKERS:-1}" \
    --threads "${WEB_THREADS:-8}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    app:app
