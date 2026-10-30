"""
认证模块 (auth.py)
==================
提供登录权限控制：
  - login_required：路由装饰器，校验用户是否登录及角色权限
  - check_mx001：判断当前管理员是否为超级管理员 MX001
"""

from functools import wraps

from flask import flash, redirect, session, url_for


def login_required(role: str | None = None):
    """【登录权限装饰器】拒绝仅通过 MX001 第一阶段验证的 session"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("请先登录。")
                return redirect(url_for("index"))

            # 如果处于 MX001 密钥待验证状态，拒绝访问
            if session.get("pending_mx001_verify"):
                flash("请先完成 MX001 密钥验证。")
                return redirect(url_for("admin_mx001_verify"))

            if role and session.get("role") != role:
                flash("当前账号无权访问该页面。")
                return redirect(url_for("index"))

            return func(*args, **kwargs)

        return wrapper
    return decorator


def check_mx001() -> bool:
    """检查当前管理员是否为 MX001"""
    return session.get("role") == "admin" and session.get("admin_no") == "MX001"
