"""
数据库模块 (db.py)
==================
提供 MySQL 数据库连接与初始化功能：
  - get_db()：获取数据库连接
  - init_db()：检查表是否存在，插入默认测试账号
  - TABLE_MAP：角色到表名的映射
"""

from datetime import datetime

import pymysql
from werkzeug.security import generate_password_hash

from config import (
    DEMO_EMAIL,
    MYSQL_DB,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)


def get_db():
    """【数据库连接】获取 MySQL 数据库连接对象"""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


# 表名映射
TABLE_MAP = {
    "student": "students",
    "worker": "workers",
    "admin": "admins",
}


def init_db() -> None:
    """【数据库初始化】检查表是否存在，插入默认账号"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'students'
            """, (MYSQL_DB,))
            result = cursor.fetchone()
            if result and result["cnt"] == 0:
                print("[WARNING] 数据库表不存在，请先通过 Navicat 执行 schema_mysql.sql 建表！")
                return

            # 插入默认学生
            cursor.execute(
                """
                INSERT IGNORE INTO students (id, name, student_no, email, password_hash, phone, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (1, "测试学生", "js23150301", DEMO_EMAIL, generate_password_hash("123123"), "13800000003", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

            # 插入默认维修工
            cursor.execute(
                """
                INSERT IGNORE INTO workers (id, name, email, password_hash, worker_no, phone, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (1, "张维修", DEMO_EMAIL, generate_password_hash("123123"), "WX001", "13800000001", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

            # 插入默认管理员（MX001 固定密钥在首次启动时生成）
            cursor.execute(
                """
                INSERT IGNORE INTO admins (id, name, admin_no, email, password_hash, secret_key, phone, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (1, "李管理员", "MX001", DEMO_EMAIL, generate_password_hash("123123"), "7a3f9e2d8b1c4560a7f3e9d2b8c1a456", "13800000002", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            # 如果 MX001 已存在但没有 secret_key，补填固定密钥
            cursor.execute(
                """
                UPDATE admins
                SET secret_key = %s
                WHERE admin_no = 'MX001' AND (secret_key IS NULL OR secret_key = '')
                """,
                ("7a3f9e2d8b1c4560a7f3e9d2b8c1a456",),
            )
        conn.commit()
    finally:
        conn.close()
