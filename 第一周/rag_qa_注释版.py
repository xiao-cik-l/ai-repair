"""
8/13 学习任务：RAG 三步法（手写，不学 LangChain）
================================================
目标产出：rag_qa.py（本文件是带注释的参考版，逻辑完全一致）

RAG 三步流水线（背这个锚）：
    查库（top3）→ 拼话（资料+问题）→ 问AI（qwen 基于资料回答）

关键认知：RAG = 2 个已有套路 + 1 行新代码
    ① 检索  → 抄 8/12 faq_kb.py 的查询写法
    ② 拼Prompt → 全程序唯一的新代码（join 拼资料 + 格式化问题）
    ③ 回答  → 抄 7/31 qwen_client.py 的一行调用

运行方式（必须在 ai-repair 目录下跑）：
    D:/py/python.exe rag_qa_注释版.py
    注意：from faq_kb import ... 是相对当前目录找文件，别在别的目录跑
"""

# ============================================================
# 准备工作：复用（import 不会触发存数据，faq_kb 的 main 被保护在
# if __name__ == "__main__" 里，import 只加载配置和函数）
# ============================================================
import chromadb
from faq_kb import DashscopeEmbedding, DB_DIR, COLLECTION_NAME   # 抄 8/12
from qwen_client import call_qwen, get_response_text             # 抄 7/31

# 连同一个库：不是新建，是打开 8/11 存好的 20 条 FAQ
# get_or_create_collection：有就直接用，没有才建（幂等）
client = chromadb.PersistentClient(path=DB_DIR)
col = client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=DashscopeEmbedding(),
    metadata={"hnsw:space": "cosine"},
)


def rag_answer(question: str) -> str:
    """RAG 三步，输入一个问题，返回基于 FAQ 资料的回答。"""

    # ---------- ① 检索 top3 ----------
    # 抄 faq_kb.py 第 147-151 行：问题转向量 → 在库里找最像的 3 条
    r = col.query(query_texts=[question], n_results=3)
    docs = r["documents"][0]     # 命中的 FAQ 问题（列表）
    metas = r["metadatas"][0]    # 命中的元数据（分类 + 标准答复）

    # ---------- ② 拼 Prompt（唯一的新代码） ----------
    # zip：把 docs 和 metas 一对一配对；join：拼成多行"资料"
    # 格式示例：
    #   空调不制冷怎么办：先检查遥控器是否调到制冷模式……
    #   空调滴水漏水：多为排水管堵塞……
    context = "\n".join(f"{d}：{m['solution']}" for d, m in zip(docs, metas))
    prompt = (f"你是宿舍维修助手，只根据下面的资料回答，资料里没有的就直说不知道。\n"
              f"资料：\n{context}\n\n问题：{question}")

    # ---------- ③ 调 qwen 回答 ----------
    # 抄 qwen_client.py：call_qwen 带重试/备用模型，get_response_text 取文本
    resp = call_qwen(prompt)
    return get_response_text(resp) if resp else "（API 调用失败，稍后再试）"


if __name__ == "__main__":
    # ---------- 验收：连续问 5 个维修问题 ----------
    tests = [
        "空调不制冷怎么办",
        "热水器没热水了",
        "马桶堵了怎么弄",
        "宿舍灯不亮",
        "WiFi 连不上",
    ]
    for q in tests:
        print(f"问：{q}")
        print(f"答：{rag_answer(q)}\n")
