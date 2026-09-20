# ============================================================
# agent_repair_注释版.py —— 多工具协同 + 容错 + 两步联动
# 和 auto_order.py 的区别(就 3 点,其他都一样):
#   1. for 循环处理"一轮里的多个工具调用"(auto_order 只处理 1 个)
#   2. while 循环处理"多轮",模型想调几次就调几次(Agent 主循环雏形)
#   3. try/except 容错 + 在岗才建单的业务守卫
# ============================================================

# ---- import:把 tools.py 里的两个工具函数和工具清单拿过来用 ----
from tools import tools, create_work_order, check_workers_available
import json
import os
from openai import OpenAI

# ---- 创建客户端:OpenAI 兼容模式,连阿里云百炼 ----
# os.getenv 优先读环境变量;没设时用后面的 key 兜底(建议改成环境变量,别把 key 写死在代码里)
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ============================================================
# 第 1 步:准备用户消息(测试两步联动时,把 W001 换成 W002)
# ============================================================
messages = [{"role": "user", "content": "505水管爆了，尽快安排维修，工人W001"}]

# ============================================================
# 第 2 步:第一轮请求,把工具清单(tools)一起发给模型
# tool_choice="auto"  = 调不调工具,由模型自己判断
# 模型不会真的执行函数,它只会"说":我要调 create_work_order,
# 参数是 {...}。真正执行的是下面我们自己写的代码。
# ============================================================
resp = client.chat.completions.create(
    model="qwen-plus",
    messages=messages,
    tools=tools,
    tool_choice="auto"
)

msg = resp.choices[0].message

# ============================================================
# 业务状态变量:维修员是否在岗
# 这是"两步联动"的开关——查到不在岗,就禁止后续建单
# ============================================================
worker_available = True  # 默认允许建单

# ============================================================
# 第 3 步:Agent 主循环
#
# 先解释两个循环的分工(这是今天的核心,多看两遍):
#   while msg.tool_calls   —— 外层:控制"轮数"
#       模型第一次可能只返回"查维修员";把结果回传后,
#       它看完"在岗"可能还会要求"建单",那就再来一轮。
#       直到它说"不需要调工具了",循环才结束。
#   for tc in msg.tool_calls —— 内层:控制"一轮里的调用数"
#       模型一轮可能同时要求调 2 个工具(并行调用),
#       每个都要执行一遍、回传一条结果。
#
# 所以:for 管"一轮多个",while 管"多轮",合起来 = Agent 会干活了。
# ============================================================
if msg.tool_calls:
    messages.append(msg)  # assistant 消息只追加一次(放循环外,避免重复)

    while msg.tool_calls:
        for tc in msg.tool_calls:
            # tc = 一个工具调用指令,里面有两样东西:
            #   tc.function.name  → 要调哪个函数,如 "create_work_order"
            #   tc.function.arguments → 模型给的参数,是 JSON 字符串
            func_name = tc.function.name
            func_args = json.loads(tc.function.arguments)  # 字符串 → 字典

            # --------------------------------------------------
            # 容错:try/except 把"执行工具"整个包起来
            # 任何一个工具都可能出错(连不上库、参数非法、逻辑 bug),
            # 出错时不能让程序崩,而是把错误写进 result 回传给模型,
            # 让模型组织一句"抱歉,建单失败,原因:..."的话给用户。
            # 这就是"工具失败不崩"的完整闭环。
            # --------------------------------------------------
            try:
                # 分发:按函数名决定调用哪个工具(if/elif 链)
                if func_name == "check_workers_available":
                    # 步骤 A:查维修员
                    result = check_workers_available(**func_args)
                    # ** 是把字典展开成关键字参数,等价于
                    # check_workers_available(worker_id="W001")
                    # 记住在岗状态:联动决策全靠这个开关
                    worker_available = result.get("available", True)

                elif func_name == "create_work_order":
                    # 步骤 B:建工单(但要先过守卫)
                    if not worker_available:
                        # 业务规则写死在代码里,不指望模型自觉:
                        # 维修员不在岗 → 直接拒绝,把原因当结果回传
                        result = {"error": "维修员不在岗,按规则拒绝建单,请更换维修员"}
                    else:
                        result = create_work_order(**func_args)

                else:
                    # 模型要求了清单里没有的工具(防御性兜底)
                    result = {"error": f"未知工具: {func_name}"}

            except Exception as e:
                # 捕获一切异常:函数炸了也不崩,错误当成结果回传
                result = {"error": f"{func_name} 执行失败: {e}"}

            # --------------------------------------------------
            # 回传:把工具结果追加成一条 role="tool" 的消息
            # 三个必须:
            #   1. tool_call_id 必须等于 tc.id(和模型的调用指令配对)
            #   2. content 必须用 json.dumps 转成字符串(老坑,别忘)
            #   3. 有几个调用就 append 几条,一一对应
            # 模型只有读到这些结果,才能决定下一步(继续调 or 收尾)
            # --------------------------------------------------
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result)
            })

        # 这一轮的结果全部回传了,再问模型一次:还调不调?
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            tools=tools
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # 模型看完结果还要求调工具(比如查完要建单)→ 追加消息,继续 while
            messages.append(msg)

    # while 结束 = 模型不再调工具了,msg.content 就是最终回答
    print(msg.content)

else:
    # 模型觉得不需要调工具,直接回答(这种情况也要处理)
    print(msg.content)
