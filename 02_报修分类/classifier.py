import os, sys  # 跨目录导入：本文件在 02_报修分类/，而模型调用与 Prompt 模板在 01_公共模块/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
sys.path.insert(0, os.path.join(_ROOT, "01_公共模块"))                # 挂上去，任意目录下运行都能 import

from prompt_templates import build_with_preset
from qwen_client import call_qwen,get_response_text
import json

def classify_repair(text: str) -> dict:
    """把报修描述分类为 {category, urgent}。

    失败时不抛异常，返回 {"category": "未知", "urgent": "否"} 作为降级值，
    由调用方（ai_service）决定怎么处理 —— API 的一次抖动不该让整个服务崩掉。
    """
    prompt = build_with_preset("repair_classify", user_input=text)
    response = call_qwen(prompt=prompt, temperature=0.1, max_tokens=200)

    # ① 取文本。call_qwen 在「重试耗尽 / Token 超限 / 网络异常」时返回 None，
    #    这里必须判空，否则 json.loads(None) 会抛 TypeError。
    result_text = get_response_text(response)
    if not result_text:
        print("  ⚠ 分类失败：API 未返回内容（网络异常或重试耗尽）")
        return {"category": "未知", "urgent": "否"}

    # ② 解析 JSON。模型偶尔会带上 markdown 代码块或多余文字，解析失败要兜住。
    try:
        result = json.loads(result_text)
    except json.JSONDecodeError:
        print(f"  ⚠ 分类失败：模型返回的不是合法 JSON → {result_text!r}")
        return {"category": "未知", "urgent": "否"}

    # ③ 结构校验。合法 JSON 也可能是数组或字符串，而调用方是按字典取字段的。
    if not isinstance(result, dict):
        print(f"  ⚠ 分类失败：期望 JSON 对象，实际拿到 {type(result).__name__}")
        return {"category": "未知", "urgent": "否"}

    return result

if __name__ =="__main__":
    texts = [
        "厕所洗手池坏了，都五天了",
        "宿舍空调漏水，一直在滴答滴答的",
        "床老是吱吱响，睡觉都不舒服",
        "椅子坏了，坐上去就会倒",
        "墙上有个裂缝，会掉渣下来"
    ]
    for t in texts:
        result  = classify_repair(t)
        print(f"报修:{t}")
        print(f"分类:{result}")
        print("===================================")