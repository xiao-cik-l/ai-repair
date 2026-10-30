from ai.common.prompt_templates import build_with_preset
from ai.common.qwen_client import call_qwen, get_response_text
import json

# ============================================================
# 允许取值 —— 必须与 prompt_templates.py 里 repair_classify 模板的规则保持一致，
# 改了一边就要改另一边，否则这里会把模型的正确答案判成越界。
# ============================================================
CATEGORIES = ("电器", "水管", "门窗", "家具", "其他")
URGENT_VALUES = ("是", "否")

# 模型偶尔会换个说法（「其它」「家俱」「电气问题」），这里做同义归一化，
# 免得因为一个字之差，把本来正确的判断算成错的。
CATEGORY_ALIASES = {
    "其它": "其他", "其他类": "其他", "墙体": "其他", "房屋本体": "其他",
    "电器类": "电器", "电气": "电器", "电路": "电器",
    "水暖": "水管", "管通": "水管", "给排水": "水管", "上下水": "水管",
    "门窗类": "门窗", "家俱": "家具", "家具类": "家具",
}
URGENT_ALIASES = {
    "紧急": "是", "非常紧急": "是", "高": "是", "高级": "是",
    "true": "是", "True": "是", "1": "是", "yes": "是",
    "普通": "否", "常规": "否", "一般": "否", "低": "否",
    "false": "否", "False": "否", "0": "否", "no": "否",
}

# 调用失败时的降级值。刻意与「其他」分开：
#   「未知」＝这次没分类成功（可用来监控 API 健康状况）
#   「其他」＝分类成功，但确实不属于电器/水管/门窗/家具
FALLBACK = {"category": "未知", "urgent": "否"}


def _normalize(result: dict) -> dict:
    """把模型输出收敛到允许取值。

    为什么必须有这一层：response_format 只保证「返回的是合法 JSON」，
    不保证「里面的值在允许集合内」—— 实测让模型自由发挥时，
    它吐出过 category="电气问题"、urgent="中" 这种值。
    合法 JSON + 越界取值 = 下游按固定集合取字段时对不上，必须在这里拦掉。
    """
    raw_cat = str(result.get("category", "")).strip()
    cat = CATEGORY_ALIASES.get(raw_cat, raw_cat)
    if cat not in CATEGORIES:
        print(f"  ⚠ 类别越界：{raw_cat!r} 不在 {CATEGORIES} 内 → 归入「其他」")
        cat = "其他"

    raw_urg = str(result.get("urgent", "")).strip()
    urg = URGENT_ALIASES.get(raw_urg, raw_urg)
    if urg not in URGENT_VALUES:
        print(f"  ⚠ 紧急程度越界：{raw_urg!r} 不在 {URGENT_VALUES} 内 → 保守取「否」")
        urg = "否"

    return {"category": cat, "urgent": urg}


def classify_repair(text: str) -> dict:
    """把报修描述分类为 {category, urgent}。

    失败时不抛异常，返回 FALLBACK 作为降级值，
    由调用方（ai_service）决定怎么处理 —— API 的一次抖动不该让整个服务崩掉。
    """
    prompt = build_with_preset("repair_classify", user_input=text)
    response = call_qwen(
        prompt=prompt,
        temperature=0,                             # 分类不需要随机性：同一句话应得到同一个答案
        max_tokens=200,
        response_format={"type": "json_object"},   # 强制返回合法 JSON（prompt 里已含 "JSON" 字样）
    )

    # ① 取文本。call_qwen 在「重试耗尽 / Token 超限 / 网络异常」时返回 None，
    #    这里必须判空，否则 json.loads(None) 会抛 TypeError。
    result_text = get_response_text(response)
    if not result_text:
        print("  ⚠ 分类失败：API 未返回内容（网络异常或重试耗尽）")
        return dict(FALLBACK)

    # ② 解析 JSON。模型偶尔会带上 markdown 代码块或多余文字，解析失败要兜住。
    try:
        result = json.loads(result_text)
    except json.JSONDecodeError:
        print(f"  ⚠ 分类失败：模型返回的不是合法 JSON → {result_text!r}")
        return dict(FALLBACK)

    # ③ 结构校验。合法 JSON 也可能是数组或字符串，而调用方是按字典取字段的。
    if not isinstance(result, dict):
        print(f"  ⚠ 分类失败：期望 JSON 对象，实际拿到 {type(result).__name__}")
        return dict(FALLBACK)

    # ④ 取值校验。JSON 合法 ≠ 值合法，收敛到允许集合内。
    return _normalize(result)


if __name__ == "__main__":
    texts = [
        "厕所洗手池坏了，都五天了",
        "宿舍空调漏水，一直在滴答滴答的",
        "床老是吱吱响，睡觉都不舒服",
        "椅子坏了，坐上去就会倒",
        "墙上有个裂缝，会掉渣下来"
    ]
    for t in texts:
        result = classify_repair(t)
        print(f"报修:{t}")
        print(f"分类:{result}")
        print("===================================")
