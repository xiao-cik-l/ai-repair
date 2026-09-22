from tools import tools, create_work_order, check_workers_available
import json
import os
from openai import OpenAI

client = OpenAI(
    # 优先读环境变量；没设时用下面的 key 兜底（建议之后改用环境变量，别把 key 写死在代码里）
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ===== 1. 用户输入(测试两步联动:换 WX002 试试) =====
# 工号必须是 workers 表里真实存在的（WX001/WX002/WX003），否则守卫①会拒绝建单
messages = [{"role": "user", "content": "505水管爆了，尽快安排维修，工人WX001"}]

# ===== 2. 第一轮:模型决定要不要调工具 =====
resp = client.chat.completions.create(
    model="qwen-plus",
    messages=messages,
    tools=tools,
    tool_choice="auto"  # auto = 模型自主决定要不要调
)

msg = resp.choices[0].message

# ===== 业务状态:记录维修员是否在岗,联动决策用 =====
worker_available = True  # 默认允许建单;查到不在岗后改为 False

# ===== 3. Agent 主循环:模型想调工具就一直调 =====
if msg.tool_calls:
    messages.append(msg)  # assistant 消息只追加一次

    while msg.tool_calls:  # 多轮:模型看完结果可能还要调(两步联动的关键)
        for tc in msg.tool_calls:  # 每一轮内,可能有多个调用,逐个执行
            func_name = tc.function.name
            func_args = json.loads(tc.function.arguments)

            # ===== 容错:任何工具都可能出错,包起来不让程序崩 =====
            try:
                if func_name == "check_workers_available":
                    result = check_workers_available(**func_args)
                    worker_available = result.get("available", True)  # 记住在岗状态
                elif func_name == "create_work_order":
                    if not worker_available:
                        # 业务规则写死在代码里:不在岗就拒绝建单,不让模型自行决定
                        result = {"error": "维修员不在岗,按规则拒绝建单,请更换维修员"}
                    else:
                        result = create_work_order(**func_args)
                else:
                    result = {"error": f"未知工具: {func_name}"}
            except Exception as e:
                # 出错不崩:把错误当结果回传,让模型兜底回复
                result = {"error": f"{func_name} 执行失败: {e}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result)  # 必须是字符串(老坑)
            })

        # 把这一轮的所有结果发回给模型,看它是否还要继续调
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            tools=tools
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            messages.append(msg)  # 还要调:追加 assistant 消息,继续循环

    # 模型不再调工具了,msg.content 就是最终回答
    print(msg.content)
else:
    # 模型认为不需要调工具,直接回答
    print(msg.content)
