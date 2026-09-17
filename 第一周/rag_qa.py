"""
调参记录（8/14）：
- Top-K: 3 效果最好（1 太窄，8 混入无关资料）
- 阈值: 0.5（距离 > 0.5 过滤，防乱编，洗衣机问题验证通过）
- 切片: FAQ 短文本无需切，以后喂长文档再考虑
"""

import chromadb
from faq_kb import DashscopeEmbedding,DB_DIR,COLLECTION_NAME
from qwen_client import call_qwen,get_response_text
client = chromadb.PersistentClient(path=DB_DIR)
col = client.get_or_create_collection(
    name = COLLECTION_NAME,
    embedding_function = DashscopeEmbedding(),
    metadata  = {"hnsw:space": "cosine"}
)
def rag_answer(question):
    r = col.query(query_texts = [question],n_results = 3)
    docs = r["documents"][0]
    metas = r["metadatas"][0]

    print(r["distances"][0])

    keep = [(d, m) for d, m, s in zip(docs, metas, r["distances"][0]) if s <= 0.5]
    context = "\n".join(f"{d}：{m['solution']}" for d, m in keep)
    prompt = (f"你是宿舍维修助手，只根据下面的资料来回答问题，资料里没有的就直接说不知道。"
              f"资料:\n{context}\n\n问题：{question}")

    resp = call_qwen(prompt)
    return get_response_text(resp) if resp else  " (API调用失败，稍后再试)"

if __name__ == "__main__":
    tests  = ["空调不制冷了，怎么办", "洗衣机坏了，怎么修"]
    for q in tests:
        print(f"问题：{q}\n回答：{rag_answer(q)}\n\n")