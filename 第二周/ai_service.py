import sys,os,json
sys.path.insert(0,os.path.join(os.path.dirname(__file__),"..","第一周"))
from classifier import classify_repair
from rag_qa import rag_answer
from tools import tools,create_work_order,check_workers_available
from openai import OpenAI

def handle(user_input):
    if any(k in user_input for k in ["修","坏","漏","堵","响","裂"]):

        cls = classify_repair(user_input)
        print("系统分类:",cls)

        urgent_map = {"是":"high","否":"medium"}
        priority = urgent_map.get(cls.get("urgent","否"),"medium")

        messages = [
            {"role":"system","content":(
            f"系统已经自动分类：category = {cls.get('category')},priority = {priority}。"
            "请调用create_work_order建单,category和priority必须使用上述值,"
            "不要自己编。"
            )},
            {"role":"user","content":user_input},
        ]

        worker_available = True  # 默认允许建单;查到不在岗后改为 False


        client = OpenAI(
    # 必须从环境变量读取；缺失时直接抛 KeyError，不设兜底值（避免密钥进代码）
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

        resp = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
        msg = resp.choices[0].message

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
                            elif not str(func_args.get("room", "")).strip() or func_args.get("room") in ("未知", "unknown", "无", "null"):
                                     # 守卫2：房间号缺失（新增）
                                result = {"error": "房间号缺失,请先询问用户房间号后再建单"}
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
            return msg.content
        else:
            # 模型认为不需要调工具,直接回答
            return msg.content
    else:
        return rag_answer(user_input)


if __name__ =="__main__":
    tests = [
        "505水管爆了，尽快安排维修",      # 报修 → 分类 → 建单
        "空调不制冷怎么办",               # 提问 → RAG 问答
        "厕所堵了三天了",                 # 报修
    ]

    for t in tests:
        print(f"用户:{t}")
        print(f"系统：{handle(t)}")
        print("="* 30)
