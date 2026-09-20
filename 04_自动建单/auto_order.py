from tools import tools, create_work_order,check_workers_available
import json
import os
from openai import OpenAI

client = OpenAI(
    # 优先读环境变量；没设时用下面的 key 兜底（建议之后改用环境变量，别把 key 写死在代码里）
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

messages = [{"role": "user", "content": "505厕所都堵了三天了，麻烦尽快安排工号W002维修"}]

resp = client.chat.completions.create(
    model="qwen-plus",
    messages=messages,
    tools=tools,
    tool_choice="auto"  # auto = 模型自主决定要不要调
)

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
       
   final_resp = client.chat.completions.create(
        model = "qwen-plus",messages = messages,tools = tools 
    )
   print(final_resp.choices[0].message.content)  # 把最终回答打印出来
else:
    # 模型认为不需要调工具，直接回答（fc_demo 原版也有这个分支，别删）
    print(msg.content)
