"""
8/15 学习任务：后端加接口（Flask 版）
====================================
目标：把 8/13 的 rag_answer 包装成网页能调的 HTTP 接口。
验收：浏览器打开 chat.html，能问能答。

为什么用 Flask 不用 FastAPI：
    宿舍维修系统（桌面 dorm_repair _code）后端就是 Flask，
    用 Flask 写，下周直接把路由挂进 app.py 就能并入正式系统。

运行方式（必须在 ai-repair 目录下跑，否则 import 找不到 faq_kb）：
    D:/py/python.exe chat_注释版.py
    然后浏览器打开 chat.html

核心只有 4 行（④ 行处），其余全是模板：
    request.get_json()  →  从请求里拿 JSON
    data.get("question") → 取出问题
    rag_answer(question) → 调你写的 RAG 函数
    jsonify(...)         → 把结果包成 JSON 返回
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from rag_qa import rag_answer   # 复用 8/13 写的 RAG 问答函数

app = Flask(__name__)
CORS(app)   # 允许网页跨域调用，不加浏览器会拦截（报 CORS 错）

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()            # ① 取请求体（前端发来的 JSON）
    question = data.get("question", "")  # ② 从 JSON 里拿问题
    answer = rag_answer(question)        # ③ 调你的 RAG（唯一核心逻辑）
    return jsonify({"answer": answer})   # ④ 包成 JSON 返回给前端

if __name__ == "__main__":
    app.run(port=8000)   # Flask 自带服务器，不需要 uvicorn
