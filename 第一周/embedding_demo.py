"""
8/11 学习任务：Embedding 入门
=============================
用 text-embedding-v3 把 3 句话转成向量，算两两相似度并打印。

验收标准：能说出「猫/狗」相似度 > 「猫/汽车」。

名词回顾（大白话）：
- Embedding / 向量：把一句话变成一串数字，意思相近的数字也接近
- 相似度：两串数字的接近程度，这里用余弦相似度（0~1，越接近 1 越像）

运行方式：python embedding_demo.py
"""

import os

import dashscope
from dashscope import TextEmbedding

# ============================================================
# 第一部分：基础配置（和 qwen_client.py 同一套 API Key）
# ============================================================

# 优先从环境变量读取，没有就兜底（正式项目不要硬编码 Key）
DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
)

# 把 Key 设置给 dashscope（不设置就会报 "No api key provided"）
dashscope.api_key = DASHSCOPE_API_KEY

# 模型名：text-embedding-v3（通义千问的向量模型，比 v1/v2 更强）
EMBEDDING_MODEL = "text-embedding-v3"

# ============================================================
# 第二部分：要转向量的 3 句话
# ============================================================

# 故意选「猫 / 狗 / 汽车」，预期：猫-狗（都是宠物）比 猫-汽车 更接近
SENTENCES = [
    "我的猫喜欢趴在沙发上睡觉",
    "我的狗喜欢在院子里追球玩",
    "今天天气真好，适合出去放风筝",
]


# ============================================================
# 第三部分：核心函数
# ============================================================

def get_embeddings(texts, model=EMBEDDING_MODEL):
    """
    把一批句子转成向量。

    参数：
    - texts: 字符串列表，比如 ["猫...", "狗...", "汽车..."]
    - model: 向量模型名，默认 text-embedding-v3

    返回：
    - embeddings: 列表，每个元素是一串数字（text-embedding-v3 默认 1024 维）
    - dimension: 向量维度（方便打印出来看看）

    注意：返回的嵌入顺序和输入顺序一致（靠 text_index 字段对应）。
    """
    response = TextEmbedding.call(model=model, input=texts)

    if response.status_code != 200:
        raise RuntimeError(f"Embedding 调用失败: status={response.status_code}, message={response.message}")

    # 按 text_index 排序，保证和输入顺序一致
    items = sorted(response.output["embeddings"], key=lambda x: x["text_index"])
    embeddings = [item["embedding"] for item in items]
    dimension = len(embeddings[0])
    return embeddings, dimension


def cosine_similarity(vec1, vec2):
    """
    余弦相似度：两个向量夹角的余弦值。
    公式：cos = (a·b) / (|a| * |b|)
    - 完全一样 = 1
    - 完全不相关 ≈ 0
    """
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    return dot / (norm1 * norm2)


# ============================================================
# 第四部分：主流程
# ============================================================

def main():
    print("=" * 56)
    print("① 把 3 句话转成向量（text-embedding-v3）")
    print("=" * 56)
    for i, s in enumerate(SENTENCES, 1):
        print(f"   句子{i}: {s}")

    embeddings, dimension = get_embeddings(SENTENCES)
    print(f"\n   转换完成！每句话变成了 {dimension} 维向量")
    print(f"   第一句向量的前 8 个数字: {[round(x, 4) for x in embeddings[0][:8]]} ...")

    print("\n" + "=" * 56)
    print("② 计算两两相似度（余弦相似度）")
    print("=" * 56)

    # 两两配对：0-1、0-2、1-2
    pairs = [(i, j) for i in range(len(SENTENCES)) for j in range(i + 1, len(SENTENCES))]
    results = []
    for i, j in pairs:
        score = cosine_similarity(embeddings[i], embeddings[j])
        results.append((score, i, j))

    # 打印明细
    for score, i, j in sorted(results, reverse=True):
        print(f"   「{SENTENCES[i]}」  vs  「{SENTENCES[j]}」")
        print(f"     相似度 = {score:.4f}")

    # 验收结论
    print("\n" + "=" * 56)
    print("③ 验收结论")
    print("=" * 56)
    cat_dog = cosine_similarity(embeddings[0], embeddings[1])
    cat_car = cosine_similarity(embeddings[0], embeddings[2])
    if cat_dog > cat_car:
        print(f"   ✓ 通过！「猫/狗」相似度({cat_dog:.4f}) > 「猫/汽车」相似度({cat_car:.4f})")
        print("   说明：Embedding 把意思相近的句子映射到了更接近的位置——这就是向量相似度的意义。")
    else:
        print(f"   ✗ 未达预期：猫/狗({cat_dog:.4f}) 竟然不大于 猫/汽车({cat_car:.4f})")
        print("   可以换个更典型的句子（比如把'汽车'换成'火车'再试），或调整句子写法。")


if __name__ == "__main__":
    main()
