"""
8/12 学习任务：ChromaDB 入门
=============================
1. 自编 20 条维修 FAQ 存进 ChromaDB（持久化，落在 ./chroma_db/ 目录）
2. 测试查询：问"空调不制冷"能查到相关 FAQ

验收标准：query("空调不制冷") 返回的第一条是空调相关的 FAQ。

设计说明（面试能讲）：
- 用 text-embedding-v3 做向量化（复用 8/11 的 embedding 知识），而不是 chromadb 自带的
  onnx 小模型 —— 商业模型效果更好，真实项目也这么接
- 存储用 PersistentClient 持久化，重启不丢数据（明天 RAG 直接复用这个库）
- 相似度空间用 cosine（余弦），和 8/11 学的余弦相似度口径一致

运行方式：python faq_kb.py
"""

import os

import chromadb
import dashscope
from dashscope import TextEmbedding

# ============================================================
# 第一部分：基础配置（API Key 与 embedding_demo.py 同一套）
# ============================================================

DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
)
dashscope.api_key = DASHSCOPE_API_KEY

EMBEDDING_MODEL = "text-embedding-v3"   # 和 8/11 用的同一个向量模型
# 向量数据随 ai 包一起发布：本文件在 ai/rag/，向上一级就是 ai/，库就在 ai/chroma_db。
# 原来写的是 "../chroma_db"（相对 ai-repair 根），搬进正式版后若沿用会指向 ai/chroma_db
# 的正上方一级而落空，所以这里改成显式的「本目录上级的 chroma_db」。
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")
COLLECTION_NAME = "faq"                  # 集合名：维修 FAQ


# ============================================================
# 第二部分：自定义 Embedding 函数（让 ChromaDB 用百炼 embedding 模型转向量）
# ============================================================

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class DashscopeEmbedding(EmbeddingFunction):
    """
    把 text-embedding-v3 包装成 ChromaDB 认识的 EmbeddingFunction。
    ChromaDB 存数据、查数据时都会自动调用它来转向量。

    注意：text-embedding-v3 单次最多批量 10 条，超过要分批调（这里自动分批）。
    """

    def __init__(self, model: str = EMBEDDING_MODEL, batch_size: int = 10):
        self.model = model
        self.batch_size = batch_size

    def _embed_batch(self, texts: list) -> list:
        """调用一次 API 把一批文本转成向量。"""
        response = TextEmbedding.call(model=self.model, input=texts)
        if response.status_code != 200:
            raise RuntimeError(
                f"Embedding 调用失败: status={response.status_code}, message={response.message}"
            )
        # 按 text_index 排序，保证和输入顺序一致
        items = sorted(response.output["embeddings"], key=lambda x: x["text_index"])
        return [item["embedding"] for item in items]

    def __call__(self, input: Documents) -> Embeddings:
        # 超过 batch_size 就分批，每批结果按顺序拼接
        embeddings = []
        for i in range(0, len(input), self.batch_size):
            batch = list(input[i:i + self.batch_size])
            embeddings.extend(self._embed_batch(batch))
        return embeddings


# ============================================================
# 第三部分：20 条维修 FAQ（问题 + 分类 + 标准答复）
# ============================================================

FAQS = [
    # (id, 问题, 分类, 标准答复)
    ("f01", "空调不制冷怎么办", "电器", "先检查遥控器是否调到制冷模式、温度是否低于室温；若正常请报修，空调加氟或清洗滤网由维修师傅处理。"),
    ("f02", "空调滴水漏水", "电器", "多为排水管堵塞或滤网太脏，先断电，报修后师傅上门清理排水管。"),
    ("f03", "空调噪音很大", "电器", "可能是外机松动或内部异物，先报修，师傅检查固定和清理。"),
    ("f04", "热水器不出热水", "电器", "检查是否通电、温度设定是否过低；仍无热水请报修，可能加热管损坏。"),
    ("f05", "宿舍电灯不亮", "电器", "先看其他电器是否有电：有电多为灯泡坏了，报修换灯泡；都没电可能是跳闸，联系宿管合闸。"),
    ("f06", "插座没电", "电器", "先确认是不是大功率电器跳闸，重启房间空气开关；仍无电请报修。"),
    ("f07", "电风扇不转", "电器", "检查插头与开关，若电机有异响请报修，可能是电容或电机故障。"),
    ("f08", "水龙头漏水", "水管", "关闭角阀，先观察是滴漏还是喷射：滴漏多为垫圈老化，报修更换；喷射先关总阀再报修。"),
    ("f09", "马桶堵塞", "水管", "先用皮搋子疏通，若无效不要继续冲水，报修师傅用疏通机处理。"),
    ("f10", "下水道反味", "水管", "多为地漏干涸或存水弯失效，可先倒水封住地漏；反复反味请报修。"),
    ("f11", "花洒水流太小", "水管", "多为花洒头水垢堵塞，可拆下用醋泡清洗；仍小可能是管道水压问题，报修。"),
    ("f12", "水管爆裂漏水", "水管", "紧急情况：立即关闭宿舍总水阀，并用毛巾堵住，同时报修（报修单注明紧急）。"),
    ("f13", "门锁打不开", "家具", "先确认是否反锁，用钥匙正常操作；钥匙拧不动不要硬掰，报修师傅上门。"),
    ("f14", "门锁卡住", "家具", "可喷少量润滑油试一下，仍卡住请报修，可能是锁芯损坏。"),
    ("f15", "床板断裂", "家具", "先不要继续睡该位置防止受伤，报修更换床板。"),
    ("f16", "衣柜门脱落", "家具", "多为合页螺丝松动，报修后师傅重新固定；损坏严重则更换合页。"),
    ("f17", "窗户关不上", "家具", "检查滑轨是否有异物或变形，报修师傅调整或更换滑轨。"),
    ("f18", "桌椅摇晃", "家具", "多为螺丝松动，可自行拧紧；螺丝滑丝或断裂请报修更换。"),
    ("f19", "宿舍网络连不上", "网络", "先重启路由器，再检查网线是否插紧；仍不行报修，网络维护由信息中心处理。"),
    ("f20", "网口没网速很慢", "网络", "尝试换一个网口或换根网线；同宿舍都慢可能是宽带问题，报修并反馈信息中心。"),
]

# 拆分列表方便 col.add
FAQ_IDS = [f[0] for f in FAQS]
FAQ_DOCS = [f[1] for f in FAQS]            # documents 存"问题"
FAQ_META = [{"cate": f[2], "solution": f[3]} for f in FAQS]


# ============================================================
# 第四部分：主流程（建库 → 存数据 → 测试查询）
# ============================================================

def main():
    print("=" * 56)
    print("① 连接/创建 ChromaDB（持久化到 ./chroma_db/）")
    print("=" * 56)
    client = chromadb.PersistentClient(path=DB_DIR)

    # 用 get_or_create：已存在就直接用，不重复建；cosine 空间和余弦相似度口径一致
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=DashscopeEmbedding(),
        metadata={"hnsw:space": "cosine"},
    )

    print(f"   集合名: {COLLECTION_NAME}，当前条数: {collection.count()}")

    # 如果之前存过数据，先清空再存（保证每次运行都是最新的 20 条，幂等）
    if collection.count() > 0:
        print("   检测到旧数据，先清空...")
        collection.delete(ids=collection.get()["ids"])

    print("\n" + "=" * 56)
    print(f"② 存入 {len(FAQS)} 条维修 FAQ")
    print("=" * 56)
    collection.add(ids=FAQ_IDS, documents=FAQ_DOCS, metadatas=FAQ_META)
    print(f"   存好了！当前条数: {collection.count()}")
    for i in range(0, len(FAQS), 5):   # 每行 5 条，展示一下
        print(f"   {', '.join(f'{fid}:{doc}' for fid, doc in zip(FAQ_IDS[i:i+5], FAQ_DOCS[i:i+5]))}")

    print("\n" + "=" * 56)
    print("③ 测试查询：问「空调不制冷」")
    print("=" * 56)
    results = collection.query(query_texts=["空调不制冷"], n_results=3)

    docs = results["documents"][0]
    distances = results["distances"][0]
    metas = results["metadatas"][0]

    for rank, (doc, dist, meta) in enumerate(zip(docs, distances, metas), 1):
        print(f"   第{rank}名: {doc}   相似度={1 - dist:.4f}   分类={meta['cate']}")
        print(f"           答复: {meta['solution'][:36]}...")

    # 验收结论
    print("\n" + "=" * 56)
    print("④ 验收结论")
    print("=" * 56)
    if "空调" in docs[0]:
        print("   ✓ 通过！问「空调不制冷」第一条就命中空调 FAQ —— 检索有效")
        print("   这就是向量检索：问题转成向量后，和库里最接近的 FAQ 被捞出来。")
        print("   明天(8/13)的 RAG 就是：检索 top3 → 拼 Prompt → 调 qwen 回答。")
    else:
        print("   ✗ 未命中，检查数据或调整查询词后再试")


if __name__ == "__main__":
    main()
