"""
验证码模块 (verification.py)
============================
负责邮箱验证码的生成、发送、保存与验证：
  - random_code()：生成 6 位随机验证码
  - send_email_code()：通过 QQ 邮箱 SMTP 发送验证码
  - save_code()：将验证码哈希后存入数据库
  - verify_code()：校验验证码是否正确且未过期
"""

import random
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from werkzeug.security import check_password_hash, generate_password_hash

from config import (
    CODE_EXPIRE_MINUTES,
    DEMO_LOGIN_CODE,
    QQ_SMTP_HOST,
    QQ_SMTP_PASSWORD,
    QQ_SMTP_PORT,
    QQ_SMTP_SENDER,
    QQ_SMTP_USER,
)
from db import get_db


def random_code() -> str:
    """【生成随机验证码】"""
    return f"{random.randint(100000, 999999)}"


def send_email_code(email: str, code: str, purpose: str) -> None:
    """【通过 QQ 邮箱发送验证码】"""
    subject = "学生公寓报修系统验证码"
    body = f"您好，您正在进行【{purpose}】操作，本次验证码为：{code}，{CODE_EXPIRE_MINUTES}分钟内有效。请勿泄露给他人。"

    # 没配授权码时不硬发信：容器演示没有邮箱凭据时，把验证码打到日志里，
    # 用 docker compose logs -f web 就能看到。默认 DEMO_LOGIN_CODE=0，行为不变。
    if not QQ_SMTP_PASSWORD:
        if DEMO_LOGIN_CODE:
            print(f"[演示模式] 未配置 SMTP 授权码，验证码不真实发信：{email} -> {code}")
            return
        raise RuntimeError(
            "未配置 SMTP_PASSWORD，无法发送验证码。"
            "如需临时演示，设置 DEMO_LOGIN_CODE=1 让验证码打印到日志。"
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = QQ_SMTP_SENDER
    msg["To"] = email
    msg["Subject"] = subject

    with smtplib.SMTP_SSL(QQ_SMTP_HOST, QQ_SMTP_PORT) as server:
        server.login(QQ_SMTP_USER, QQ_SMTP_PASSWORD)
        server.sendmail(QQ_SMTP_SENDER, [email], msg.as_string())


def save_code(email: str, purpose: str, code: str) -> None:
    """【保存验证码】"""
    expire_at = datetime.now() + timedelta(minutes=CODE_EXPIRE_MINUTES)
    code_hash = generate_password_hash(code)
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO email_codes(email, purpose, code_hash, expire_at, used, created_at)
                VALUES (%s, %s, %s, %s, 0, %s)
                """,
                (email, purpose, code_hash, expire_at.strftime("%Y-%m-%d %H:%M:%S"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        conn.commit()
    finally:
        conn.close()


def verify_code(email: str, purpose: str, code: str) -> bool:
    """【验证验证码】"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM email_codes
                WHERE email = %s AND purpose = %s AND used = 0
                ORDER BY id DESC LIMIT 1
                """,
                (email, purpose),
            )
            record = cursor.fetchone()

            if not record:
                return False

            if record["expire_at"] < datetime.now():
                return False

            if not check_password_hash(record["code_hash"], code):
                return False

            cursor.execute("UPDATE email_codes SET used = 1 WHERE id = %s", (record["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def check_code(email: str, purpose: str, code: str) -> bool:
    """【仅校验验证码】不标记为已使用，用于前端 AJAX 预校验"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM email_codes
                WHERE email = %s AND purpose = %s AND used = 0
                ORDER BY id DESC LIMIT 1
                """,
                (email, purpose),
            )
            record = cursor.fetchone()

            if not record:
                return False

            if record["expire_at"] < datetime.now():
                return False

            return check_password_hash(record["code_hash"], code)
    finally:
        conn.close()
