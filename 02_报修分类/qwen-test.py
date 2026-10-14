"""
演示：用封装好的 qwen_client 改造报修分类脚本
===========================================================
对比「直接调 dashscope SDK 的原始写法」vs「用 qwen_client 封装后的写法」
"""

import os, sys  # 跨目录导入：qwen_client 在 01_公共模块/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
sys.path.insert(0, os.path.join(_ROOT, "01_公共模块"))

from qwen_client import call_qwen, get_response_text
import json

# ============================================================
# 使用方式：把 prompt 拼好，一行调用 + 一行取结果
# ============================================================

template = """请将以下报修描述分类，以json格式输出(直接输出json，不要markdown代码块)，包含：
category：维修类别（电器/水管/门窗/家具/其他）
urgent：是否紧急（是/否）
报修描述：{user_input}
"""

prompt = template.format(user_input="宿舍的墙皮脱落，差点砸到人了，请尽快处理。")

# ★ 这是核心：一行调用，所有错误处理都在 qwen_client 里了
response = call_qwen(
    prompt=prompt,
    system_prompt="你是一个物业报修分类助手，用中文回答。",
    max_tokens=200,        # 控制输出长度，省 Token
    temperature=0.1,       # 分类任务要精准，越低越好
)

# 取结果
result_text = get_response_text(response)

if result_text:
    print("原始返回：", result_text)
    try:
        result = json.loads(result_text)
        print("解析成功：", result)
        print("类别：", result["category"])
        print("是否紧急：", result["urgent"])
    except json.JSONDecodeError:
        print("模型返回的不是合法 JSON，需要调整 prompt")
else:
    print("API 调用失败，请检查网络和 API Key")


# ============================================================
# 进阶演示：故意触发备用模型切换
# ============================================================

print("\n" + "=" * 50)
print("进阶测试：连续调用，如果主模型被限流会自动切备用模型")
print("=" * 50)

for i in range(3):
    response = call_qwen(
        prompt=f"用一句话介绍{i+1}号客服",
        max_tokens=50,
    )
    text = get_response_text(response)
    if text:
        print(f"  第{i+1}次: {text}")
    else:
        print(f"  第{i+1}次: 调用失败")
