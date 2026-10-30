"""三合一 AI 入口（service.py）
==============================

一次调用，模型自己决定走哪条路：
  描述设施故障            → create_work_order（分类 + 建单，真实写库）
  问「怎么办 / 注意什么」  → answer_faq（ChromaDB 检索 + 模型回答）
  指定了维修工工号        → check_workers_available（在岗校验，守卫①）
  信息不全                → 追问，不建单

2026-10-25 的四个稳定性改造（面试可讲）：
  1. 工具循环上限 AI_MAX_TOOL_ROUNDS：模型反复调工具时不再无限循环。
  2. 模型请求超时 AI_REQUEST_TIMEOUT + 关闭 SDK 重试：卡住的请求不再占死 worker。
  3. 幂等：tools.create_work_order 内部按 学生+房间+类别 5 分钟去重。
  4. 多轮：handle() 接收 history，追问房间号能接上。
另外把「关键词硬匹配」换成了「模型自主路由」——「水管爆了」不含
修/坏/漏/堵/响/裂 任何一个字，老逻辑会判去问答、不建单。

分类环节仍然保留且是确定性的：模型自填的 category / priority 一律不采信，
建单前用 classify_repair 重新算一遍，分类失败（category=未知）就拒绝建单。
"""

import json
import os
import sys

from ai.classify.classifier import classify_repair
from ai.common.format_utils import extract_building, is_valid_room
from ai.autoorder.tools import (answer_faq, check_workers_available,
                                create_work_order, tools)
from openai import OpenAI

# LLM 配置（base_url / 模型名 / 备用模型 / 思考开关）统一走 config.py。
# try/except 兼容直接运行本脚本：那时 sys.path[0] 是 ai/，正式版根目录不在路径上。
try:
    from config import (AI_MAX_TOOL_ROUNDS, AI_REQUEST_TIMEOUT, LLM_BASE_URL,
                        LLM_ENABLE_THINKING, LLM_FALLBACK_MODEL, LLM_MODEL)
except ImportError:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from config import (AI_MAX_TOOL_ROUNDS, AI_REQUEST_TIMEOUT, LLM_BASE_URL,
                        LLM_ENABLE_THINKING, LLM_FALLBACK_MODEL, LLM_MODEL)

# 分类器的 urgent 取值 → 工单优先级
URGENT_TO_PRIORITY = {"是": "high", "否": "medium"}

# 系统提示词。按「模型可能犯的错」逐条写：
#   · 不许编工单号 → 防幻觉（面试官一定会问「它会不会瞎编」）
#   · 缺房间号先追问 → 配合代码里的守卫②（is_valid_room）
#   · 只补房间号要接上文 → 配合 history 实现多轮
SYSTEM_PROMPT = """你是南京审计大学金桥学院学生公寓报修系统的 AI 助手。你可以调用工具，必须遵守以下规则：

1. 用户描述具体的设施故障（坏了、堵了、漏水、不制冷、跳闸等）→ 调用 create_work_order 建单。
   - 缺少房间号时不要建单，先追问「请问是哪一间宿舍？」。
   - 建单成功后告诉用户工单号，并说明已进入管理员审核队列。
2. 用户明确指定了维修工工号（如 WX001）→ 先调用 check_workers_available 查在岗；
   返回 available=false 时不要建单，把原因如实告诉用户。
3. 用户在问「怎么处理 / 怎么办 / 要注意什么」这类知识问题 → 调用 answer_faq 查知识库后回答，不要建单。
4. 与报修无关的闲聊或超出范围的问题 → 简短礼貌回答，不要调用建单工具。
5. 如果用户这一轮只补充了房间号（上一轮你在问房间号，他回「505」），请直接用该房间号建单，
   不要追问楼栋——楼栋系统会自动推断；报修单里楼栋本来就是可选项。
6. 不要编造工单号、工单状态或维修进度。所有事实只能来自工具返回的结果。"""


def _build_client():
    """建模型客户端。

    timeout：SDK 默认 600 秒，卡住的请求会占死一个 Flask worker，压到 20 秒。
    max_retries=0：重试由本文件的降级逻辑负责，不让 SDK 再叠一层，
                 否则「模型不可用」时要等 (SDK 重试 × 超时) 才返回。
    """
    return OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],  # 缺失时直接 KeyError，不写兜底密钥
        base_url=LLM_BASE_URL,
        timeout=AI_REQUEST_TIMEOUT,
        max_retries=0,
    )


def _sanitize_history(history, limit=None):
    """清洗前端/session 传回来的历史。

    只允许 user / assistant 两种角色、只保留字符串内容、单条截断 800 字。
    为什么必须洗：session 存在客户端 cookie 里，内容可被篡改；把任意 role
    （比如 system）塞进来就等于让用户改写系统提示词。
    """
    limit = limit or AI_MAX_TOOL_ROUNDS * 2
    out = []
    if not isinstance(history, list):
        return out
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if content:
            out.append({"role": role, "content": content[:800]})
    return out


def _create_order(args, identity, user_input, state):
    """执行 create_work_order 的全部业务守卫。

    state 是可变 dict，记录维修工在岗状态（守卫①跨工具调用要记住）。
    """
    # 守卫①：查过岗且不在岗 → 拒绝建单。规则写在代码里，不交给模型判断。
    if not state.get("available", True):
        return {"error": "维修员不在岗，按规则拒绝建单，请更换维修员"}

    # 守卫②：房间号缺失（空串 / "未知" / "宿舍" 等）→ 先追问
    room = args.get("room")
    if not is_valid_room(room):
        return {"error": "房间号缺失，请先询问用户房间号后再建单"}

    issue = (args.get("issue") or "").strip() or user_input

    # 确定性分类：不采信模型自填的 category / priority
    cls = classify_repair(issue)
    if cls.get("category") == "未知":
        # 分类失败绝不建单：否则会落一条 category=未知 的脏数据，
        # 管理员既不能按类别筛选、也看不出这是 AI 判断失败的痕迹。
        return {"error": "分类失败：无法判断故障类型，请让用户补充更具体的描述（哪里坏了、什么现象）"}

    priority = URGENT_TO_PRIORITY.get(cls.get("urgent", "否"), "medium")
    building = args.get("building")
    if not str(building or "").strip():
        # 模型没显式给楼栋时，从用户原话正则提取（"我是2楼208宿舍的" → "2号楼"）
        building = extract_building(user_input)

    return create_work_order(
        room=room,
        issue=issue,
        priority=priority,
        category=cls["category"],
        identity=identity,
        building=building,
    )


def _run_tool(tool_call, identity, user_input, state):
    """执行一个工具调用。任何异常都转成 {"error": ...} 回给模型，不让程序崩。"""
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        return {"error": f"{name} 的参数不是合法 JSON：{tool_call.function.arguments!r}"}
    if not isinstance(args, dict):
        return {"error": f"{name} 的参数格式错误"}

    try:
        if name == "check_workers_available":
            result = check_workers_available(**args)
            state["available"] = bool(result.get("available", True))  # 记住在岗状态
            return result

        if name == "answer_faq":
            return answer_faq(args.get("question") or user_input)

        if name == "create_work_order":
            return _create_order(args, identity, user_input, state)

        return {"error": f"未知工具: {name}"}
    except Exception as exc:  # 工具内部异常（数据库断了、参数对不上）不该让整轮崩
        return {"error": f"{name} 执行失败: {exc}"}


def handle(user_input, identity=None, history=None):
    """三合一入口。

    identity: 调用方（Flask 路由）传入的当前登录学生身份，
              形如 {"student_id": 12, "student_no": "js23150301"}。
              传了就往建单工具透传；不传则沿用 tools.py 里的默认值，
              独立脚本（auto_order.py 等）的行为完全不变。
    history:  最近几轮的 [{role, content}]，用于多轮追问（可传 None）。
    """
    user_input = (user_input or "").strip()
    if not user_input:
        return "请输入你想报修或咨询的内容。"

    client = _build_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_sanitize_history(history))
    messages.append({"role": "user", "content": user_input})

    def _chat(model, msgs, tool_defs=None, tool_choice=None):
        """带降级的模型调用：主模型 429 限流 / 403 配额耗尽时自动切备用模型。

        备用模型不一定是 deepseek 系，所以 enable_thinking 要按模型名重算。
        """
        body = ({"enable_thinking": LLM_ENABLE_THINKING}
                if model.startswith("deepseek") else None)
        try:
            return client.chat.completions.create(
                model=model, messages=msgs, tools=tool_defs,
                tool_choice=tool_choice, extra_body=body,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (403, 429) and model != LLM_FALLBACK_MODEL:
                print(f"  ⚠ 主模型 {model} 不可用（HTTP {status}），降级到 {LLM_FALLBACK_MODEL}")
                fallback_body = ({"enable_thinking": LLM_ENABLE_THINKING}
                                 if LLM_FALLBACK_MODEL.startswith("deepseek") else None)
                return client.chat.completions.create(
                    model=LLM_FALLBACK_MODEL, messages=msgs, tools=tool_defs,
                    tool_choice=tool_choice, extra_body=fallback_body,
                )
            raise

    resp = _chat(LLM_MODEL, messages, tool_defs=tools, tool_choice="auto")
    msg = resp.choices[0].message

    # ===== Agent 主循环：模型想调工具就继续，但最多 AI_MAX_TOOL_ROUNDS 轮 =====
    state = {"available": True}  # 守卫①的跨轮状态；默认允许建单
    rounds = 0
    while msg.tool_calls:
        rounds += 1
        if rounds > AI_MAX_TOOL_ROUNDS:
            # 没有这个上限时，只要模型每轮都返回 tool_calls 就会一直循环：
            # 烧 token、占住请求线程，前端只会看到「思考中」永远转。
            print(f"  ✗ 工具调用超过 {AI_MAX_TOOL_ROUNDS} 轮，转人工处理")
            return ("这个问题我这边反复确认也没能定下来，已经帮你转给管理员。"
                    "你也可以点右上角「手动填写表单」直接提交，会更快一些。")

        messages.append(msg)  # assistant 消息（含 tool_calls）只追加一次

        for tc in msg.tool_calls:  # 同一轮内可能有多个调用，逐个执行
            result = _run_tool(tc, identity=identity,
                               user_input=user_input, state=state)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),  # 必须是字符串（老坑）
            })

        # 把工具结果发回模型，看它是否还要继续调
        resp = _chat(LLM_MODEL, messages, tool_defs=tools)
        msg = resp.choices[0].message

    return msg.content or "我没太理解你的意思，可以说得再具体一点吗？"


if __name__ == "__main__":
    tests = [
        "505水管爆了，尽快安排维修",        # 报修 → 分类 → 建单
        "空调不制冷怎么办",                # 提问 → RAG 问答
        "厕所堵了三天了",                  # 缺房间号 → 追问，不建单
    ]
    for t in tests:
        print(f"用户:{t}")
        print(f"系统：{handle(t)}")
        print("=" * 30)
