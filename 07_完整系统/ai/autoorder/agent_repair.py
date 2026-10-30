import os
import sys

# 直接运行本脚本时（python ai/autoorder/agent_repair.py），sys.path[0] 是 ai/autoorder/，
# 找不到 ai 包，需要把正式版根目录补上；被 Flask 当包导入时这段不执行。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ai.autoorder.tools import tools, create_work_order, check_workers_available
import json
from openai import OpenAI

# LLM 配置（base_url / 模型名 / 备用模型 / 思考开关）走 config.py，换模型只改一处
from config import (LLM_BASE_URL, LLM_ENABLE_THINKING, LLM_FALLBACK_MODEL,
                    LLM_MODEL)

client = OpenAI(
    # 只从环境变量读取，不设兜底值（避免密钥进代码）；缺失时为 None，调用 API 才报错
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=LLM_BASE_URL,
)

# DeepSeek-V4 系默认开启思考模式；这个脚本走 Function Calling，思考链非但没用，
# 还会让 reasoning_content 必须原样回传（漏传服务端直接 400），所以关掉。
_extra = ({"enable_thinking": LLM_ENABLE_THINKING}
          if LLM_MODEL.startswith("deepseek") else None)


def _chat(model, messages, tool_defs=None, tool_choice=None):
    """带降级的模型调用：主模型 429/403 时自动切备用模型（配额是账号级的）。"""
    try:
        return client.chat.completions.create(
            model=model, messages=messages, tools=tool_defs,
            tool_choice=tool_choice, extra_body=_extra,
        )
    except Exception as e:
        # 故意不 import openai 的异常类：用 status_code 判断，SDK 版本无关
        if getattr(e, "status_code", None) in (403, 429) and model != LLM_FALLBACK_MODEL:
            print(f"  ⚠ 主模型 {model} 不可用（HTTP {e.status_code}），降级到 {LLM_FALLBACK_MODEL}")
            return client.chat.completions.create(
                model=LLM_FALLBACK_MODEL, messages=messages,
                tools=tool_defs, tool_choice=tool_choice,
                # 备用模型不一定是 deepseek 系，不能乱带 enable_thinking
                extra_body=({"enable_thinking": LLM_ENABLE_THINKING}
                            if LLM_FALLBACK_MODEL.startswith("deepseek") else None),
            )
        raise


# ===== 1. 用户输入(测试两步联动:换 WX002 试试) =====
# 工号必须是 workers 表里真实存在的（WX001/WX002/WX003），否则守卫①会拒绝建单
messages = [{"role": "user", "content": "505水管爆了，尽快安排维修，工人WX001"}]

# ===== 2. 第一轮:模型决定要不要调工具 =====
resp = _chat(LLM_MODEL, messages, tool_defs=tools, tool_choice="auto")  # auto = 模型自主决定要不要调

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
        resp = _chat(LLM_MODEL, messages, tool_defs=tools)
        msg = resp.choices[0].message
        if msg.tool_calls:
            messages.append(msg)  # 还要调:追加 assistant 消息,继续循环

    # 模型不再调工具了,msg.content 就是最终回答
    print(msg.content)
else:
    # 模型认为不需要调工具,直接回答
    print(msg.content)
