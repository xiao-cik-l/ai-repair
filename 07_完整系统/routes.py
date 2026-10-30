"""
路由模块 (routes.py)
====================
集中管理系统所有 HTTP 路由，按功能域分组：
  - 首页与验证码发送
  - 学生注册与登录
  - 维修工与管理员登录
  - 学生功能（仪表盘、提交工单）
  - 维修工功能（仪表盘、接单、完成工单、删除图片）
  - 管理员功能（仪表盘、审核、退回、人员变动管理）
  - 退出登录

通过 register_routes(app) 函数将所有路由注册到 Flask 应用实例，
避免循环导入（routes.py 不导入 app，由 app.py 传入 app）。
"""

import os
import re
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from auth import check_mx001, login_required
from config import allowed_file
from db import get_db
from verification import check_code, random_code, save_code, send_email_code, verify_code

# 宿舍格式统一走 ai/common/format_utils（AI 建单那边用的是同一份函数，
# 保证「学生表单提交」和「AI 自动建单」落库的格式完全一致）
from ai.common.format_utils import normalize_building, normalize_room


def register_routes(app) -> None:
    """将所有路由注册到给定的 Flask 应用实例"""

    # ============================================================
    # 首页与验证码发送
    # ============================================================

    @app.route("/")
    def index():
        """【首页路由】"""
        return render_template("index.html")

    @app.route("/send_code", methods=["POST"])
    def send_code():
        """【发送验证码路由】"""
        email = request.form.get("email", "").strip().lower()
        purpose = request.form.get("purpose", "login").strip()

        if not email:
            flash("请先填写邮箱。")
            return redirect(request.referrer or url_for("index"))

        code = random_code()
        save_code(email, purpose, code)
        send_email_code(email, code, purpose)

        flash("验证码已发送到您的 QQ 邮箱，请查收。")
        return redirect(request.referrer or url_for("index"))

    @app.route("/verify_code", methods=["POST"])
    @login_required("admin")
    def verify_code_ajax():
        """【验证码校验接口】AJAX 调用，仅校验不消耗验证码"""
        email = request.form.get("email", "").strip().lower()
        purpose = request.form.get("purpose", "").strip()
        code = request.form.get("code", "").strip()

        if not email or not purpose or not code:
            return jsonify({"success": False, "message": "请填写邮箱和验证码。"}), 400

        # 仅校验，不标记为已使用
        ok = check_code(email, purpose, code)
        if ok:
            return jsonify({"success": True, "message": "验证码正确，可以修改信息。"})
        else:
            return jsonify({"success": False, "message": "验证码错误或已过期。"}), 400

    # ============================================================
    # 学生注册与登录
    # ============================================================

    @app.route("/student/register", methods=["GET", "POST"])
    def student_register():
        """【学生注册路由】"""
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            student_no = request.form.get("student_no", "").strip().lower()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            code = request.form.get("code", "").strip()

            # 验证学号格式：js + 八位数字
            if not re.match(r'^js\d{8}$', student_no):
                flash("学号格式错误，必须是 js 开头加八位数字，例如：js23150301")
                return redirect(url_for("student_register"))

            if not verify_code(email, "register", code):
                flash("验证码错误或已过期。")
                return redirect(url_for("student_register"))

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT id FROM students WHERE email = %s", (email,))
                    exists = cursor.fetchone()
                    if exists:
                        flash("该邮箱已注册，请直接登录。")
                        return redirect(url_for("student_login"))

                    cursor.execute(
                        """
                        INSERT INTO students(name, student_no, email, password_hash, phone, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (name, student_no, email, generate_password_hash(password), "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    )
                conn.commit()
            finally:
                conn.close()

            flash("注册成功，请登录。")
            return redirect(url_for("student_login"))

        return render_template("student_register.html")

    @app.route("/student/login", methods=["GET", "POST"])
    def student_login():
        """【学生登录路由】支持学号+邮箱双重验证"""
        if request.method == "POST":
            student_no = request.form.get("student_no", "").strip().lower()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            code = request.form.get("code", "").strip()

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    # 同时验证学号和邮箱是否匹配
                    cursor.execute(
                        "SELECT * FROM students WHERE student_no = %s AND email = %s",
                        (student_no, email),
                    )
                    user = cursor.fetchone()
            finally:
                conn.close()

            if not user or not check_password_hash(user["password_hash"], password):
                flash("学号、邮箱或密码错误。")
                return redirect(url_for("student_login"))

            if not verify_code(email, "student_login", code):
                flash("验证码错误或已过期。")
                return redirect(url_for("student_login"))

            session.clear()
            session.update({
                "user_id": user["id"],
                "name": user["name"],
                "student_no": user["student_no"],
                "role": "student",
                "email": email,
            })
            # 学生登录后直接进 AI 报修助手（手动表单从助手页右上角「手动填写表单」进入）
            return redirect(url_for("student_ai"))

        return render_template("student_login.html")

    # ============================================================
    # 维修工与管理员登录
    # ============================================================

    @app.route("/worker/login", methods=["GET", "POST"])
    def worker_login():
        """【维修工登录路由】工号 + 邮箱 + 密码 + 验证码"""
        if request.method == "POST":
            worker_no = request.form.get("worker_no", "").strip().upper()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            code = request.form.get("code", "").strip()

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM workers WHERE email = %s AND worker_no = %s",
                        (email, worker_no),
                    )
                    user = cursor.fetchone()
            finally:
                conn.close()

            if not user:
                flash("工号或邮箱不匹配。")
                return redirect(url_for("worker_login"))

            if not check_password_hash(user["password_hash"], password):
                flash("密码错误。")
                return redirect(url_for("worker_login"))

            if not verify_code(email, "worker_login", code):
                flash("验证码错误或已过期。")
                return redirect(url_for("worker_login"))

            session.clear()
            session.update({
                "user_id": user["id"],
                "name": user["name"],
                "role": "worker",
                "email": email,
                "worker_no": worker_no,
            })
            return redirect(url_for("worker_dashboard"))

        return render_template("worker_login.html")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        """【管理员登录路由】管理工号 + 邮箱 + 密码 + 验证码；MX001 额外需要密钥验证"""
        if request.method == "POST":
            admin_no = request.form.get("admin_no", "").strip().upper()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            code = request.form.get("code", "").strip()

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM admins WHERE admin_no = %s AND email = %s", (admin_no, email))
                    user = cursor.fetchone()
            finally:
                conn.close()

            if not user:
                flash("管理工号或邮箱不匹配。")
                return redirect(url_for("admin_login"))

            if not check_password_hash(user["password_hash"], password):
                flash("密码错误。")
                return redirect(url_for("admin_login"))

            if not verify_code(email, "admin_login", code):
                flash("验证码错误或已过期。")
                return redirect(url_for("admin_login"))

            # MX001 需要额外密钥验证，先不设置完整 session
            if user["admin_no"] == "MX001":
                session.clear()
                session.update({
                    "pending_mx001_verify": True,
                    "pending_admin_id": user["id"],
                    "pending_admin_name": user["name"],
                    "pending_email": email,
                })
                return redirect(url_for("admin_mx001_verify"))

            # 普通管理员直接登录
            session.clear()
            session.update({
                "user_id": user["id"],
                "name": user["name"],
                "role": "admin",
                "email": email,
                "admin_no": user["admin_no"],
            })
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_login.html")

    @app.route("/admin/mx001_verify", methods=["GET", "POST"])
    def admin_mx001_verify():
        """【MX001 密钥二次验证】仅 pending_mx001_verify 状态可访问"""
        if not session.get("pending_mx001_verify"):
            flash("非法访问。")
            return redirect(url_for("index"))

        if request.method == "POST":
            input_key = request.form.get("secret_key", "").strip()

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT secret_key FROM admins WHERE id = %s", (session.get("pending_admin_id"),))
                    result = cursor.fetchone()
            finally:
                conn.close()

            if not result or result["secret_key"] != input_key:
                flash("密钥错误，请重新输入。")
                return redirect(url_for("admin_mx001_verify"))

            # 密钥验证通过，设置完整 session
            pending_id = session.get("pending_admin_id")
            pending_name = session.get("pending_admin_name")
            pending_email = session.get("pending_email")
            session.clear()
            session.update({
                "user_id": pending_id,
                "name": pending_name,
                "role": "admin",
                "email": pending_email,
                "admin_no": "MX001",
            })
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_mx001_verify.html")

    # ============================================================
    # 学生功能
    # ============================================================

    @app.route("/student/dashboard")
    @login_required("student")
    def student_dashboard():
        """【学生仪表盘】"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ro.id, ro.student_id, ro.worker_id, ro.dorm_building, ro.room_no,
                           ro.category, ro.description, ro.status, ro.audit_note, ro.result_note,
                           ro.result_image, ro.created_at, ro.reviewed_at, ro.accepted_at, ro.finished_at,
                           s.student_no AS student_no
                    FROM repair_orders ro
                    JOIN students s ON ro.student_id = s.id
                    WHERE ro.student_id = %s
                    ORDER BY ro.id DESC
                    """,
                    (session["user_id"],),
                )
                orders = cursor.fetchall()
        finally:
            conn.close()
        return render_template("student_dashboard.html", orders=orders)

    @app.route("/student/order/new", methods=["GET", "POST"])
    @login_required("student")
    def new_order():
        """【提交报修工单】记录学生学号以确定报修人身份"""
        if request.method == "POST":
            # 宿舍格式规范化：楼栋统一「X号楼」、房间统一「XXX宿舍」，
            # 与 AI 建单（tools.create_work_order）走同一份 format_utils，落库格式一致
            dorm_building = normalize_building(request.form.get("dorm_building", ""))
            room_no = normalize_room(request.form.get("room_no", ""))
            category = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()

            # 后端兜底校验（前端 required 只是第一道关，直接构造 POST 可绕过）
            if not dorm_building or not room_no or not category or not description:
                flash("请完整填写宿舍楼、宿舍号、报修类型和问题描述。")
                return redirect(url_for("new_order"))

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO repair_orders
                        (student_id, student_no, dorm_building, room_no, category, description, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'pending_review', %s)
                        """,
                        (session["user_id"], session["student_no"], dorm_building, room_no, category, description, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    )
                conn.commit()
            finally:
                conn.close()

            flash("报修工单已提交，等待管理员审核。")
            return redirect(url_for("student_dashboard"))

        return render_template("order_create.html")

    # ============================================================
    # 维修工功能
    # ============================================================

    @app.route("/worker/dashboard")
    @login_required("worker")
    def worker_dashboard():
        """【维修工仪表盘】"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ro.id, ro.student_id, ro.worker_id, ro.dorm_building, ro.room_no,
                           ro.category, ro.description, ro.status, ro.audit_note, ro.result_note,
                           ro.result_image, ro.created_at, ro.reviewed_at, ro.accepted_at, ro.finished_at,
                           s.name AS student_name, s.student_no AS student_no, s.email AS student_email
                    FROM repair_orders ro
                    JOIN students s ON ro.student_id = s.id
                    WHERE (
                        ro.status IN ('approved', 'accepted', 'processing')
                        OR (ro.status = 'finished' AND ro.worker_id = %s)
                    )
                    AND (ro.worker_id IS NULL OR ro.worker_id = %s)
                    ORDER BY ro.id DESC
                    """,
                    (session["user_id"], session["user_id"]),
                )
                orders = cursor.fetchall()
        finally:
            conn.close()
        return render_template("worker_dashboard.html", orders=orders)

    @app.route("/worker/order/<int:order_id>/accept", methods=["POST"])
    @login_required("worker")
    def accept_order(order_id: int):
        """【接单】"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE repair_orders
                    SET worker_id = %s, status = 'accepted', accepted_at = %s
                    WHERE id = %s AND status = 'approved'
                    """,
                    (session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id),
                )
            conn.commit()
        finally:
            conn.close()
        flash("接单成功。")
        return redirect(url_for("worker_dashboard"))

    @app.route("/worker/order/<int:order_id>/finish", methods=["POST"])
    @login_required("worker")
    def finish_order(order_id: int):
        """【完成工单】支持上传维修结果图片"""
        result_note = request.form.get("result_note", "").strip()
        result_image = None

        # 处理图片上传
        file = request.files.get("result_image")
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"order_{order_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            result_image = f"uploads/{filename}"
        elif file and file.filename:
            flash("图片格式不支持，仅允许 png、jpg、jpeg、gif、webp 格式。")
            return redirect(url_for("worker_dashboard"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE repair_orders
                    SET status = 'finished', result_note = %s, result_image = %s, finished_at = %s
                    WHERE id = %s AND worker_id = %s
                    """,
                    (result_note, result_image, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id, session["user_id"]),
                )
            conn.commit()
        finally:
            conn.close()
        flash("维修完成，等待管理员归档。")
        return redirect(url_for("worker_dashboard"))

    @app.route("/order/<int:order_id>/delete_image", methods=["POST"])
    @login_required()
    def delete_order_image(order_id: int):
        """【删除维修结果图片】管理员或完成该工单的维修工可删除"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT result_image, worker_id FROM repair_orders WHERE id = %s",
                    (order_id,),
                )
                order = cursor.fetchone()

                if not order:
                    flash("工单不存在。")
                    return redirect(request.referrer or url_for("index"))

                if not order["result_image"]:
                    flash("该工单没有图片。")
                    return redirect(request.referrer or url_for("index"))

                # 权限校验：管理员 或 完成该工单的维修工
                role = session.get("role")
                user_id = session.get("user_id")
                if role != "admin" and not (role == "worker" and order["worker_id"] == user_id):
                    flash("您没有权限删除此图片。")
                    return redirect(request.referrer or url_for("index"))

                # 删除服务器上的文件
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(order["result_image"]))
                if os.path.exists(file_path):
                    os.remove(file_path)

                # 清空数据库字段
                cursor.execute(
                    "UPDATE repair_orders SET result_image = NULL WHERE id = %s",
                    (order_id,),
                )
            conn.commit()
            flash("图片已删除。")
        finally:
            conn.close()

        return redirect(request.referrer or url_for("index"))

    # ============================================================
    # 管理员功能
    # ============================================================

    @app.route("/admin/dashboard")
    @login_required("admin")
    def admin_dashboard():
        """【管理员仪表盘】"""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ro.id, ro.student_id, ro.worker_id, ro.dorm_building, ro.room_no,
                           ro.category, ro.description, ro.status, ro.audit_note, ro.result_note,
                           ro.result_image, ro.created_at, ro.reviewed_at, ro.accepted_at, ro.finished_at,
                           s.name AS student_name, s.student_no AS student_no, w.name AS worker_name
                    FROM repair_orders ro
                    JOIN students s ON ro.student_id = s.id
                    LEFT JOIN workers w ON ro.worker_id = w.id
                    ORDER BY ro.id DESC
                    """
                )
                orders = cursor.fetchall()

                cursor.execute("SELECT * FROM workers ORDER BY id")
                workers = cursor.fetchall()
        finally:
            conn.close()
        return render_template("admin_dashboard.html", orders=orders, workers=workers)

    @app.route("/admin/order/<int:order_id>/approve", methods=["POST"])
    @login_required("admin")
    def approve_order(order_id: int):
        """【审核通过】"""
        worker_id = request.form.get("worker_id") or None
        audit_note = request.form.get("audit_note", "管理员审核通过")
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE repair_orders
                    SET status = 'approved', worker_id = %s, audit_note = %s, reviewed_at = %s
                    WHERE id = %s
                    """,
                    (worker_id, audit_note, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id),
                )
            conn.commit()
        finally:
            conn.close()
        flash("工单已审核通过。")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/order/<int:order_id>/reject", methods=["POST"])
    @login_required("admin")
    def reject_order(order_id: int):
        """【退回工单】"""
        audit_note = request.form.get("audit_note", "信息不完整，退回修改")
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE repair_orders
                    SET status = 'rejected', audit_note = %s, reviewed_at = %s
                    WHERE id = %s
                    """,
                    (audit_note, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id),
                )
            conn.commit()
        finally:
            conn.close()
        flash("工单已退回。")
        return redirect(url_for("admin_dashboard"))

    # ============================================================
    # 人员变动管理（仅管理编号 MX001 可用）
    # ============================================================

    @app.route("/admin/personnel")
    @login_required("admin")
    def admin_personnel():
        """【人员变动管理】仅 MX001 可查看，显示维修工和管理员列表"""
        if not check_mx001():
            flash("您没有权限访问人员变动管理。")
            return redirect(url_for("admin_dashboard"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM workers ORDER BY id")
                workers = cursor.fetchall()
                cursor.execute("SELECT * FROM admins ORDER BY id")
                admins = cursor.fetchall()
        finally:
            conn.close()
        return render_template("admin_personnel.html", workers=workers, admins=admins)

    def generate_next_worker_no() -> str:
        """【自动生成下一个工号】格式：WX001, WX002, ..."""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT worker_no FROM workers WHERE worker_no LIKE 'WX%' ORDER BY id DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    last_no = result["worker_no"]
                    num = int(last_no[2:]) + 1
                else:
                    num = 1
                return f"WX{num:03d}"
        finally:
            conn.close()

    @app.route("/admin/personnel/worker/add", methods=["POST"])
    @login_required("admin")
    def admin_add_worker():
        """【添加维修工】仅 MX001，工号自动生成"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not email or not password:
            flash("请完整填写维修工信息（姓名、邮箱、密码）。")
            return redirect(url_for("admin_personnel"))

        worker_no = generate_next_worker_no()

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workers (name, email, password_hash, worker_no, phone, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (name, email, generate_password_hash(password), worker_no, phone, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
            conn.commit()
            flash(f"维修工 {name}({worker_no}) 添加成功。")
        except Exception as e:
            flash(f"添加失败，可能邮箱已存在：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    @app.route("/admin/personnel/worker/delete/<int:worker_id>", methods=["POST"])
    @login_required("admin")
    def admin_delete_worker(worker_id: int):
        """【删除维修工】仅 MX001"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                # 先解除该维修工关联的工单
                cursor.execute("UPDATE repair_orders SET worker_id = NULL WHERE worker_id = %s", (worker_id,))
                cursor.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
            conn.commit()
            flash("维修工已删除。")
        except Exception as e:
            flash(f"删除失败：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    def generate_next_admin_no() -> str:
        """【自动生成下一个管理编号】格式：MX001, MX002, ..."""
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT admin_no FROM admins WHERE admin_no LIKE 'MX%' ORDER BY id DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    last_no = result["admin_no"]
                    num = int(last_no[2:]) + 1
                else:
                    num = 1
                return f"MX{num:03d}"
        finally:
            conn.close()

    @app.route("/admin/personnel/admin/add", methods=["POST"])
    @login_required("admin")
    def admin_add_admin():
        """【添加管理员】仅 MX001，管理编号自动生成"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not email or not password:
            flash("请完整填写管理员信息（姓名、邮箱、密码）。")
            return redirect(url_for("admin_personnel"))

        admin_no = generate_next_admin_no()

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO admins (name, admin_no, email, password_hash, phone, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (name, admin_no, email, generate_password_hash(password), phone, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
            conn.commit()
            flash(f"管理员 {name}({admin_no}) 添加成功。")
        except Exception as e:
            flash(f"添加失败，可能邮箱已存在：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    @app.route("/admin/personnel/admin/delete/<int:admin_id>", methods=["POST"])
    @login_required("admin")
    def admin_delete_admin(admin_id: int):
        """【删除管理员】仅 MX001，且不能删除自己"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        if admin_id == session.get("user_id"):
            flash("不能删除自己。")
            return redirect(url_for("admin_personnel"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM admins WHERE id = %s", (admin_id,))
            conn.commit()
            flash("管理员已删除。")
        except Exception as e:
            flash(f"删除失败：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    # ============================================================
    # 编辑功能（仅 MX001）
    # ============================================================

    @app.route("/admin/personnel/worker/edit/<int:worker_id>", methods=["POST"])
    @login_required("admin")
    def admin_edit_worker(worker_id: int):
        """【编辑维修工】仅 MX001，任何信息修改都必须通过邮箱验证码验证"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        worker_no = request.form.get("worker_no", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        code = request.form.get("code", "").strip()

        if not name or not email or not worker_no:
            flash("姓名、邮箱、工号不能为空。")
            return redirect(url_for("admin_personnel"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                # 获取当前邮箱（验证码发送到原邮箱以证明身份）
                cursor.execute("SELECT email FROM workers WHERE id = %s", (worker_id,))
                old = cursor.fetchone()
                old_email = old["email"] if old else ""

                # 任何信息修改都必须通过邮箱验证码验证
                if not code or not verify_code(old_email, "edit_worker", code):
                    flash("邮箱验证码错误或已过期，修改信息需要验证。")
                    return redirect(url_for("admin_personnel"))

                if password:
                    cursor.execute(
                        """
                        UPDATE workers
                        SET name = %s, email = %s, worker_no = %s, phone = %s, password_hash = %s
                        WHERE id = %s
                        """,
                        (name, email, worker_no, phone, generate_password_hash(password), worker_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE workers
                        SET name = %s, email = %s, worker_no = %s, phone = %s
                        WHERE id = %s
                        """,
                        (name, email, worker_no, phone, worker_id),
                    )
            conn.commit()
            flash(f"维修工 {name}({worker_no}) 信息已更新。")
        except Exception as e:
            flash(f"更新失败：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    @app.route("/admin/personnel/admin/edit/<int:admin_id>", methods=["POST"])
    @login_required("admin")
    def admin_edit_admin(admin_id: int):
        """【编辑管理员】仅 MX001，任何信息修改都必须通过邮箱验证码验证"""
        if not check_mx001():
            flash("您没有权限执行此操作。")
            return redirect(url_for("admin_dashboard"))

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        admin_no = request.form.get("admin_no", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        code = request.form.get("code", "").strip()

        if not name or not email or not admin_no:
            flash("姓名、邮箱、管理编号不能为空。")
            return redirect(url_for("admin_personnel"))

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                # 获取当前邮箱（验证码发送到原邮箱以证明身份）
                cursor.execute("SELECT email FROM admins WHERE id = %s", (admin_id,))
                old = cursor.fetchone()
                old_email = old["email"] if old else ""

                # 任何信息修改都必须通过邮箱验证码验证
                if not code or not verify_code(old_email, "edit_admin", code):
                    flash("邮箱验证码错误或已过期，修改信息需要验证。")
                    return redirect(url_for("admin_personnel"))

                if password:
                    cursor.execute(
                        """
                        UPDATE admins
                        SET name = %s, email = %s, admin_no = %s, phone = %s, password_hash = %s
                        WHERE id = %s
                        """,
                        (name, email, admin_no, phone, generate_password_hash(password), admin_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE admins
                        SET name = %s, email = %s, admin_no = %s, phone = %s
                        WHERE id = %s
                        """,
                        (name, email, admin_no, phone, admin_id),
                    )
            conn.commit()
            flash(f"管理员 {name}({admin_no}) 信息已更新。")
        except Exception as e:
            flash(f"更新失败：{str(e)}")
        finally:
            conn.close()
        return redirect(url_for("admin_personnel"))

    # ============================================================
    # 退出登录
    # ============================================================

    @app.route("/logout")
    def logout():
        """【退出登录】"""
        session.clear()
        flash("已退出登录。")
        return redirect(url_for("index"))
