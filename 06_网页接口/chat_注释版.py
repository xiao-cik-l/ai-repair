"""
网页接口（Flask 版）：一个输入框接到 ai_service 的三合一入口
==========================================================
最初是 8/15 的任务：把 rag_answer 包装成网页能调的 HTTP 接口。
现在扩到完整入口 —— 一个输入框，两条路都通：
    报修类描述（含 修/坏/漏/堵/响/裂）→ 分类 → 自动建单（会真实写库）
    其他提问                          → RAG 知识库问答（只读，不写库）

验收：浏览器打开 chat.html，报修能建单、提问能回答。

为什么用 Flask 不用 FastAPI：
    宿舍维修系统（桌面 dorm_repair _code）后端就是 Flask，
    用 Flask 写，以后可以直接把路由挂进 app.py 并入正式系统。

运行方式（本文件在 06_网页接口/，路径已在下面自动挂好，任意目录下都能跑）：
    D:/py/python.exe 06_网页接口/chat_注释版.py
    然后浏览器打开同目录下的 chat.html

核心只有 4 行（④ 行处），其余全是模板：
    request.get_json()   →  从请求里拿 JSON
    data.get("question") →  取出问题
    handle(question)     →  调三合一入口（内部分流：报修建单 / 问知识）
    jsonify(...)         →  把结果包成 JSON 返回
"""
import os, sys  # 跨目录导入：ai_service 在 05_整合入口/，它内部会再挂 01/02/03/04 四个目录
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
sys.path[:0] = [os.path.join(_ROOT, d) for d in ("01_公共模块", "03_知识库问答", "05_整合入口")]

from flask import Flask, request, jsonify
from flask_cors import CORS
from ai_service import handle   # 三合一入口：内部按关键词分流到 报修建单 / RAG 问答

app = Flask(__name__)
CORS(app)   # 允许网页跨域调用，不加浏览器会拦截（报 CORS 错）

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()            # ① 取请求体（前端发来的 JSON）
    question = data.get("question", "")  # ② 从 JSON 里拿问题
    answer = handle(question)            # ③ 调三合一入口（内部自动分流：报建单 / 问知识）
    return jsonify({"answer": answer})   # ④ 包成 JSON 返回给前端

if __name__ == "__main__":
    app.run(port=8000)   # Flask 自带服务器，不需要 uvicorn
