import os
import sys

# 直接运行本脚本时（python ai/autoorder/auto_order.py），sys.path[0] 是 ai/autoorder/，
# 找不到 ai 包，需要把正式版根目录补上；被 Flask 当包导入时这段不执行。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ai.autoorder.tools import tools, create_work_order,check_workers_available
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


messages = [{"role": "user", "content": "505厕所都堵了三天了，麻烦尽快安排工号W002维修"}]

resp = _chat(LLM_MODEL, messages, tool_defs=tools, tool_choice="auto")  # auto = 模型自主决定要不要调

msg = resp.choices[0].message

if msg.tool_calls:
   messages.append(msg)  # assistant 消息只追加一次(放循环外,多个调用时别重复)
   for tc in msg.tool_calls:
       func_name = tc.function.name
       func_args = json.loads(tc.function.arguments)
       

       if func_name =="check_workers_available":
           result = check_workers_available(**func_args)
       elif func_name =="create_work_order":
           result = create_work_order(**func_args)
       
       messages.append({
           "role":"tool",
           "tool_call_id":tc.id,
           "content":json.dumps(result)
           })
       
   final_resp = _chat(LLM_MODEL, messages, tool_defs=tools)
   print(final_resp.choices[0].message.content)  # 把最终回答打印出来
else:
    # 模型认为不需要调工具，直接回答（fc_demo 原版也有这个分支，别删）
    print(msg.content)
