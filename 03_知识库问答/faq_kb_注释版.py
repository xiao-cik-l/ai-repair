"""
8/12 学习任务：ChromaDB 入门 —— 逐行注释版
==========================================
本文件是 faq_kb.py 的学习版：代码逻辑与 faq_kb.py 完全一致，
区别只在注释——把每一段代码都讲清楚「做什么、为什么、有什么坑」。

对照阅读方法（三步）：
  1. 先只读注释，尝试自己说出代码该怎么写；
  2. 再看代码，核对思路对不对；
  3. 最后把两段「必打核心」默写一遍（见文件内标注）。

运行方式：python faq_kb_注释版.py（效果与原版完全一样）

整个文件的结构（先看骨架，再看血肉）：
  第一部分：基础配置 —— API Key、模型名、存储路径
  第二部分：自定义 Embedding 函数 —— 让 ChromaDB 用千问做向量化 ★必打
  第三部分：20 条维修 FAQ 数据 —— 纯数据，不用背
  第四部分：main() 主流程 —— 建库 → 存数据 → 测试查询 ★必打
"""

import os  # os 模块：用来读环境变量（API Key 可以放在环境变量里，避免写死在代码中）

import chromadb  # ChromaDB 官方客户端库：负责"向量库"的建库、存、查
import dashscope  # 阿里云百炼（通义千问）的官方 SDK：负责调大模型
from dashscope import TextEmbedding  # 从 SDK 里单独取出"文本向量化"接口


# ============================================================
# 第一部分：基础配置（API Key 与 embedding_demo.py 同一套）
# ============================================================

# 读 API Key：只从环境变量 DASHSCOPE_API_KEY 读取，不设兜底值（避免密钥进代码）。
# 用 .get() 时读不到会返回 None（不立即报错），要等调用 API 才暴露。
# 这样做的意义：Key 只写在一处，多个脚本共用，以后换 Key 只改环境变量。
DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
)
# dashscope 是模块级配置：把 Key 塞进 dashscope.api_key，
# 之后所有 dashscope 的调用（Embedding、Chat 等）都会自动带上这个 Key 去鉴权。
# ⚠️ 坑：如果漏了这行，会报 "No api key provided"（8/11 踩过）。
dashscope.api_key = DASHSCOPE_API_KEY

EMBEDDING_MODEL = "text-embedding-v3"   # 向量模型名：和 8/11 用的同一个，保证口径一致
DB_DIR = "./chroma_db"                   # 数据库目录：向量库文件就存在这个文件夹里（持久化，重启不丢）
COLLECTION_NAME = "faq"                  # 集合名：相当于数据库里的"一张表"，专门存维修 FAQ


# ============================================================
# 第二部分：自定义 Embedding 函数（让 ChromaDB 用千问做向量化）★必打
# ============================================================
# 背景知识：
#   ChromaDB 存文本、查文本时，都需要先把"文字"变成"向量"才能计算相似度。
#   默认它会用自己内置的一个小模型（onnx）做这件事，效果一般。
#   真实项目通常接商业模型（效果更好），所以我们要写一个"适配器"，
#   让 ChromaDB 每次需要转向量时，都去调 text-embedding-v3。
#   这就是下面这个类的全部意义。

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class DashscopeEmbedding(EmbeddingFunction):
    """
    把 text-embedding-v3 包装成 ChromaDB 认识的 EmbeddingFunction。
    ChromaDB 存数据、查数据时都会自动调用它来转向量。

    注意：text-embedding-v3 单次最多批量 10 条，超过要分批调（这里自动分批）。
    """

    def __init__(self, model: str = EMBEDDING_MODEL, batch_size: int = 10):
        # __init__：创建这个类的实例时自动执行，用来"记住"两个参数。
        #   model       —— 用哪个向量模型（默认 text-embedding-v3）
        #   batch_size  —— 一次最多给 API 传几条文本（v3 上限就是 10，别改大）
        self.model = model          # self.model：把参数存到"自己身上"，其他方法才能用
        self.batch_size = batch_size

    def _embed_batch(self, texts: list) -> list:
        """调用一次 API 把一批文本转成向量。"""
        # TextEmbedding.call()：调百炼的向量接口，把一批文本发过去，返回结果对象
        response = TextEmbedding.call(model=self.model, input=texts)
        if response.status_code != 200:
            # 网络问题 / Key 失效 / 参数错误时，status_code 不是 200。
            # 这里主动抛异常，避免拿着坏数据继续往下跑（fail fast，尽早暴露问题）。
            raise RuntimeError(
                f"Embedding 调用失败: status={response.status_code}, message={response.message}"
            )
        # response.output["embeddings"] 是一组向量结果，格式形如：
        #   [{"text_index": 0, "embedding": [0.1, 0.2, ...]}, {"text_index": 1, ...}]
        # text_index 表示这条向量对应输入里的第几条。
        # 理论上顺序和输入一致，但官方建议按 text_index 显式排序，保证万无一失。
        items = sorted(response.output["embeddings"], key=lambda x: x["text_index"])
        # 排序后，只把"向量本体"（embedding 那一串数字）抽出来返回
        return [item["embedding"] for item in items]

    def __call__(self, input: Documents) -> Embeddings:
        # __call__：让类的实例可以"像函数一样被调用"。
        # 比如 ef = DashscopeEmbedding() 之后，ef(["文本1", "文本2"]) 就会执行这里。
        # ChromaDB 内部就是通过这个约定来调我们的适配器的——它不知道也不关心
        # 里面用的是千问还是别的，只要"给文本、还向量"就行。（这叫"接口约定"）
        embeddings = []  # 收集所有批次的结果
        for i in range(0, len(input), self.batch_size):
            # range(0, 总数, 10)：按 10 条一组切分，比如 25 条 → [0:10] [10:20] [20:25]
            batch = list(input[i:i + self.batch_size])  # 切出本批文本（转成 list 稳妥）
            embeddings.extend(self._embed_batch(batch))  # 调 API 转向量，拼到总结果里
        return embeddings  # 返回"和输入顺序一一对应"的向量列表


# ============================================================
# 第三部分：20 条维修 FAQ（问题 + 分类 + 标准答复）
# ============================================================
# 这就是要存进向量库的"语料"。每条是一个元组：(唯一id, 问题, 分类, 标准答复)
#   id        —— 唯一标识，ChromaDB 要求每条数据必须有 id（类似数据库主键）
#   问题      —— 存成 document（被向量化的部分，查询时和它算相似度）
#   分类/答复 —— 存成 metadata（附带信息，不参与向量化，但查询结果里可以取出来用）

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

# —— 把 FAQS 按"列"拆开，方便直接喂给 col.add() 的对应参数 ——
# 拆分的意义：ChromaDB 的 add() 接口要的是三个平行列表（ids / documents / metadatas），
# 而不是元组列表，所以这里用列表推导式把每条数据"拆成三列"。
FAQ_IDS = [f[0] for f in FAQS]                        # 所有 id        → ["f01", "f02", ...]
FAQ_DOCS = [f[1] for f in FAQS]                       # 所有问题       → 存进 documents（会被向量化）
FAQ_META = [{"cate": f[2], "solution": f[3]} for f in FAQS]  # 所有 分类+答复 → 存进 metadatas（附带信息）


# ============================================================
# 第四部分：主流程（建库 → 存数据 → 测试查询）★必打
# ============================================================

def main():
    # ===== ① 连接 / 创建向量库 =====
    print("=" * 56)
    print("① 连接/创建 ChromaDB（持久化到 ./chroma_db/）")
    print("=" * 56)
    # PersistentClient(path=...)：
    #   带持久化的客户端——库文件落在指定目录，程序退出后再启动，数据还在。
    #   对比：chromadb.Client() 是内存模式，重启就清空（只适合临时试验）。
    #   选持久化的原因：明天(8/13)做 RAG 时，这个库要反复被查，数据不能丢。
    client = chromadb.PersistentClient(path=DB_DIR)

    # get_or_create_collection(...)：
    #   "有就用，没有就建"——脚本重复运行不会报"集合已存在"。
    #   name               —— 集合名（相当于表名）
    #   embedding_function —— 指定用我们的 DashscopeEmbedding（即千问向量化）
    #   metadata={"hnsw:space": "cosine"}：
    #       hnsw 是 ChromaDB 的索引算法，space=cosine 表示用"余弦相似度"来衡量远近。
    #       为什么必须是 cosine：8/11 学的相似度就是余弦，这里口径统一，数值才能对上。
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=DashscopeEmbedding(),
        metadata={"hnsw:space": "cosine"},
    )

    # collection.count()：当前库里有多少条。这里只做展示，确认连接成功。
    print(f"   集合名: {COLLECTION_NAME}，当前条数: {collection.count()}")

    # ===== ② 存数据（幂等：先清空旧数据，再存最新的 20 条）=====
    # 为什么要清空重存？
    #   因为 add() 不允许重复 id——第二次运行时 f01~f20 都已存在，会报错。
    #   清空重存 = 每次运行结果一致（幂等），调试时随时重跑，不会越跑越多。
    if collection.count() > 0:
        print("   检测到旧数据，先清空...")
        # collection.get()["ids"]：取出库里所有数据的 id 列表，然后整体 delete。
        # 注意：是先"查出来"，再"按查到的 id 删"，不能直接 delete() 空调用。
        collection.delete(ids=collection.get()["ids"])

    print("\n" + "=" * 56)
    print(f"② 存入 {len(FAQS)} 条维修 FAQ")
    print("=" * 56)
    # collection.add(ids=..., documents=..., metadatas=...)：
    #   三个参数一一对应（同一下标组成一条完整数据）。
    #   documents 会被向量化 → 查询时用"问题"和它比相似度。
    #   metadatas 不向量化 → 查询结果里原样带回来，方便直接取"分类/答复"。
    collection.add(ids=FAQ_IDS, documents=FAQ_DOCS, metadatas=FAQ_META)
    print(f"   存好了！当前条数: {collection.count()}")
    for i in range(0, len(FAQS), 5):   # 每行展示 5 条，纯为了打印好看
        print(f"   {', '.join(f'{fid}:{doc}' for fid, doc in zip(FAQ_IDS[i:i+5], FAQ_DOCS[i:i+5]))}")

    # ===== ③ 测试查询：问「空调不制冷」=====
    print("\n" + "=" * 56)
    print("③ 测试查询：问「空调不制冷」")
    print("=" * 56)
    # collection.query(query_texts=["空调不制冷"], n_results=3)：
    #   这是"向量检索"的核心一步，内部过程是：
    #     1) 用我们的 Embedding 函数把"空调不制冷"转成向量；
    #     2) 在库里和 20 条 FAQ 的向量逐个算余弦相似度；
    #     3) 取最相似的 3 条（n_results=3）返回。
    #   返回结果是个 dict，结构：{"documents": [...], "distances": [...], "metadatas": [...]}
    #   因为传入的是列表（query_texts=[...]），所以每个字段外面又套了一层 [0] 取第一条。
    results = collection.query(query_texts=["空调不制冷"], n_results=3)

    docs = results["documents"][0]      # 命中的 3 条"问题"文本
    distances = results["distances"][0] # 每条对应的"距离"（cosine 距离，越小越相似）
    metas = results["metadatas"][0]     # 每条对应的"附带信息"（分类 + 标准答复）

    # zip 把三个列表"按位置对齐"打包，enumerate 从 1 开始编号 → 打印排名
    for rank, (doc, dist, meta) in enumerate(zip(docs, distances, metas), 1):
        # 为什么是 1 - dist：ChromaDB 返回的是"距离"（0=完全一样），
        # 我们想展示"相似度"（1=完全一样），所以换算：相似度 = 1 - 距离。
        print(f"   第{rank}名: {doc}   相似度={1 - dist:.4f}   分类={meta['cate']}")
        print(f"           答复: {meta['solution'][:36]}...")  # 只打前 36 字，控制输出长度

    # ===== ④ 验收结论 =====
    print("\n" + "=" * 56)
    print("④ 验收结论")
    print("=" * 56)
    # 验收标准：问"空调不制冷"，第一条命中必须是空调相关（f01~f03 里任意一条）。
    if "空调" in docs[0]:
        print("   ✓ 通过！问「空调不制冷」第一条就命中空调 FAQ —— 检索有效")
        print("   这就是向量检索：问题转成向量后，和库里最接近的 FAQ 被捞出来。")
        print("   明天(8/13)的 RAG 就是：检索 top3 → 拼 Prompt → 调 qwen 回答。")
    else:
        print("   ✗ 未命中，检查数据或调整查询词后再试")


# if __name__ == "__main__"：
#   这段判断的意思是"只有直接运行本文件时才执行 main()"。
#   以后这个文件被 import 成模块时（比如 8/13 的 rag_qa.py 里 import），
#   不会一导入就自动跑，只有主动调用才执行——这是 Python 的标准做法。
if __name__ == "__main__":
    main()
