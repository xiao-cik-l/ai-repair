"""
AI 模块路由 (routes_ai.py)
==========================
把 ai 包的 handle() 挂进宿舍报修系统，一个输入框、模型自己决定走哪条路：
  描述故障        → 分类 → Function Calling 自动建单（真实写库）
  问怎么办        → ChromaDB 检索后回答
  信息不全        → 追问（多轮，上下文存服务端）

对外提供的地址：
  GET  /student/ai              AI 助手页面（仅学生角色可进）
  POST /api/ai/chat             对话接口（普通 JSON，流式的降级方案）
  POST /api/ai/chat/stream      对话接口（SSE 分块推送，前端默认走这个）
  POST /api/ai/chat/reset       清空当前学生的对话上下文

设计要点（面试能讲）：
  1. 身份从 Flask session 取，绝不进 tools 的 schema ——
     否则一句 prompt 注入就能让模型替别人报修。
  2. 多轮上下文存在【服务端内存】而不是 session cookie：
     Flask 默认把 session 写进 cookie（浏览器单条 cookie 上限约 4KB），
     中文经 JSON 转义后 1 个字占 6 字节，存 4 轮稍长回答就会把 cookie 撑爆，
     直接后果是登录态丢失。生产环境这一层应换成 Redis。
  3. 流式是「分块推送」而不是模型逐 token 流式：模型那一段仍然一次性返回
     （工具循环要完整拿到 tool_calls 才能继续），回答落定后再按 24 字一块推给前端。
     好处是前端首字节立刻到达、观感是打字机；代价是首块之前仍要等模型。
  4. AI 调用整体包 try：AI 挂掉时返回 500 + 人话，不让整个请求变成 Flask 默认的
     HTML 错误页（前端 fetch 拿到 HTML 会解析 JSON 失败，错误信息反而看不清）。

通过 register_routes_ai(app) 注册，与 routes.py 的 register_routes 保持同一种风格
（路由文件不 import app，由 app.py 传入实例，避免循环导入）。
"""

import json
import time

from flask import Response, jsonify, render_template, request, session

from auth import login_required
from config import AI_HISTORY_ROUNDS
from ai.service import handle

# ============================================================
# 多轮上下文（服务端内存）
# ============================================================
# key = 学生 user_id，value = [{role, content}, ...]（最多 AI_HISTORY_ROUNDS 轮）
# 为什么不开线程锁：Flask 开发服务器默认单进程多线程，最坏情况是同一学生的
# 两条消息交错覆盖上下文（只会丢一轮记忆，不会崩）；上生产换 Redis 时这层自然消失。
_HISTORY = {}
_HISTORY_MAX_USERS = 500  # 防止长期运行内存无限增长（按插入顺序淘汰最旧的）


def _history_key():
    return str(session.get("user_id") or "anonymous")


def _get_history():
    """取当前学生的历史（返回副本，避免调用方改到存储里的列表）"""
    return list(_HISTORY.get(_history_key(), []))


def _remember(question, answer, key=None):
    """把这一问一答并入历史，只保留最近 AI_HISTORY_ROUNDS 轮

    key 显式传入是为了流式接口：生成器在响应返回之后才被消费，那时
    session 已经失效（拿不到 user_id），必须在请求上下文里先取好再传进来。
    """
    key = key if key is not None else _history_key()
    history = _HISTORY.get(key, [])
    history = (history + [
        {"role": "user", "content": question[:300]},
        {"role": "assistant", "content": (answer or "")[:300]},
    ])[-(AI_HISTORY_ROUNDS * 2):]
    _HISTORY[key] = history

    # 简单的容量控制：按插入顺序淘汰最旧的会话
    while len(_HISTORY) > _HISTORY_MAX_USERS:
        _HISTORY.pop(next(iter(_HISTORY)))


def _identity():
    """身份只从 session 取，不接收前端传参（前端传什么都不信）"""
    return {
        "student_id": session.get("user_id"),
        "student_no": session.get("student_no"),
    }


def _sse(payload):
    """把一条消息打包成 SSE 帧"""
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def register_routes_ai(app) -> None:
    """把 AI 相关路由注册到给定的 Flask 应用实例"""

    # ============================================================
    # 页面：AI 报修助手
    # ============================================================
    @app.route("/student/ai")
    @login_required("student")
    def student_ai():
        """【AI 助手页面】仅学生角色可访问，未登录会被 login_required 重定向到首页"""
        return render_template("student_ai.html", title="AI 报修助手")

    # ============================================================
    # 接口：对话（普通 JSON，流式失败时的降级通道）
    # ============================================================
    @app.route("/api/ai/chat", methods=["POST"])
    @login_required("student")
    def api_ai_chat():
        """【AI 对话接口】JSON 收发"""
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            return jsonify({"ok": False, "answer": "请输入内容再发送。"}), 400

        try:
            answer = handle(question, identity=_identity(), history=_get_history())
        except Exception as exc:  # AI 链路整体兜底，别把异常抛成 Flask 错误页
            return jsonify({
                "ok": False,
                "answer": "AI 服务暂时不可用（%s）。请稍后再试，或返回用普通表单提交报修。" % exc,
            }), 500

        if not answer:
            answer = "AI 没有返回内容，请换个说法再试一次。"

        _remember(question, answer)
        return jsonify({"ok": True, "answer": answer})

    # ============================================================
    # 接口：对话（SSE 分块推送，前端默认用这个）
    # ============================================================
    @app.route("/api/ai/chat/stream", methods=["POST"])
    @login_required("student")
    def api_ai_chat_stream():
        """【流式对话接口】text/event-stream，事件形如 {"type": chunk|done|error}"""
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            # 400 也是合法 JSON，前端按 ok=false 处理
            return jsonify({"ok": False, "answer": "请输入内容再发送。"}), 400

        # ⚠ 生成器是在 Response 返回之后才被消费的，那一刻请求上下文已经出栈，
        # 在生成器里再读 session 会抛 "Working outside of request context"
        # （Flask 的经典坑，本地跑可能碰巧不报、一上 WSGI 必炸）。
        # 所以身份、历史、存储 key 全部在视图函数里先取好，生成器只用局部变量。
        identity = _identity()
        history = _get_history()
        hist_key = _history_key()

        def generate():
            # 先发一个 SSE 注释帧，让连接立刻建立（避免浏览器一直 pending、
            # 也避免某些代理把响应缓冲到整个请求结束）
            yield ": thinking\n\n"

            try:
                answer = handle(question, identity=identity, history=history)
            except Exception as exc:
                yield _sse({"type": "error",
                            "text": "AI 服务暂时不可用（%s）。请稍后再试，或返回用普通表单提交报修。" % exc})
                return

            if not answer:
                answer = "AI 没有返回内容，请换个说法再试一次。"

            _remember(question, answer, key=hist_key)

            # 每 24 字一块推给前端做打字机效果；最后再发一条 done 带完整文本，
            # 前端以 done 的 text 为准（防止分块边界丢字）。
            # 0.03 秒/块的间隔：不 sleep 的话所有块会在同一瞬间到达，
            # 打字机效果等于没有；800 字的回答也只多花约 1 秒。
            for i in range(0, len(answer), 24):
                yield _sse({"type": "chunk", "text": answer[i:i + 24]})
                time.sleep(0.03)
            yield _sse({"type": "done", "text": answer})

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 关掉 Nginx 一类反向代理的缓冲
                "Connection": "keep-alive",
            },
        )

    # ============================================================
    # 接口：清空上下文
    # ============================================================
    @app.route("/api/ai/chat/reset", methods=["POST"])
    @login_required("student")
    def api_ai_chat_reset():
        """【清空对话】演示和调试用：丢掉当前学生的多轮上下文"""
        _HISTORY.pop(_history_key(), None)
        return jsonify({"ok": True, "answer": "对话上下文已清空。"})
