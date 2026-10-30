"""
学生公寓报修系统 —— 程序入口 (app.py)
====================================
基于 Flask 的轻量级报修管理系统，包含三种角色：
  - 学生：注册、登录、提交报修工单、查看工单状态
  - 维修工：登录、接单、完成维修
  - 管理员：登录、审核/退回工单、分配维修工

技术栈：Flask + MySQL + QQ邮箱验证码
数据库设计：students、workers、admins 三张独立表，支持同一邮箱登录不同角色

模块拆分：
  - config.py      配置常量
  - db.py          数据库连接与初始化
  - verification.py 邮箱验证码生成/发送/校验
  - auth.py        登录权限装饰器
  - routes.py      所有 HTTP 路由
  - routes_ai.py   AI 模块路由（/student/ai、/api/ai/chat、/api/ai/chat/stream、/api/ai/chat/reset）
  - ai/            AI 能力包（分类 / RAG / 自动建单 / 三合一入口）
"""

import os

from flask import Flask

from config import (
    CODE_EXPIRE_MINUTES,
    FLASK_SECRET_KEY,
    MAX_CONTENT_LENGTH,
    UPLOAD_FOLDER,
)
from db import init_db

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY
app.config["CODE_EXPIRE_MINUTES"] = CODE_EXPIRE_MINUTES
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# 注册所有路由（routes.py 不导入 app，由 app.py 传入 app 实例，避免循环导入）
from routes import register_routes

register_routes(app)

# 注册 AI 模块路由（与上面同一套风格：路由文件不 import app）
from routes_ai import register_routes_ai

register_routes_ai(app)

if __name__ == "__main__":
    init_db()
    # 容器里必须监听 0.0.0.0，本地默认仍是 127.0.0.1，行为不变。
    # debug 也交给环境变量：容器里关掉，否则 reloader 会起两个进程。
    app.run(
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
        host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
    )
