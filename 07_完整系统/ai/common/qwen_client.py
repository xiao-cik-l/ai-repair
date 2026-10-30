"""
带错误处理的 API 调用封装模块
============================================
把 try/except、重试、指数退避、备用模型切换 全部封装好
以后调用大模型只需要一行：response = call_qwen("你的问题")

2026-10-24 起主力模型由通义千问（qwen-max / qwen-plus）切换为
DeepSeek-V4-Pro —— 模型仍托管在阿里云百炼（Model Studio），所以还是走
dashscope SDK，只是换模型名。模型名/备用模型集中在 config.py 的 LLM_* 配置。
文件名沿用旧称 qwen_client.py：classifier.py 和 rag_qa.py 都 import 它，
改名收益为零、风险不为零。
"""

import dashscope
from dashscope import Generation
import time
import os
import sys

# ============================================================
# 第一部分：基础配置
# ============================================================

# LLM 配置（模型名 / 备用模型 / 思考开关）统一走 config.py，换模型只改一处。
# try/except 只为兼容「直接跑本目录脚本」：那时 sys.path[0] 是 ai/common/，
# 正式版根目录不在路径上，需要补一次；作为 ai 包被导入时这段不会触发。
try:
    from config import LLM_ENABLE_THINKING, LLM_FALLBACK_MODEL, LLM_MODEL
except ImportError:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from config import LLM_ENABLE_THINKING, LLM_FALLBACK_MODEL, LLM_MODEL

# 只从环境变量读取 API Key，不设兜底值（避免密钥进代码）
# 注意：这里用 .get()，读不到时返回 None 而不报错，要等调用 API 才暴露；
# 若想启动即报错，改用 os.environ["DASHSCOPE_API_KEY"]。
# 这把 Key 同时供对话模型（DeepSeek-V4-Pro）和向量模型（text-embedding-v3）
# 使用 —— 百炼的配额是账号级的，重新创建 Key 不会重置免费额度。
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# 主模型和备用模型（默认值见 config.py，可用环境变量 LLM_MODEL / LLM_FALLBACK_MODEL 覆盖）
PRIMARY_MODEL = LLM_MODEL                   # 主模型：DeepSeek-V4-Pro
FALLBACK_MODEL = LLM_FALLBACK_MODEL         # 主模型用不了时切到这个（qwen-turbo）

# 重试配置
# MAX_RETRIES=4 而不是 3：第 1 次固定用来打主模型，切成备用模型后只剩 3 次机会。
# 只给 3 次的话，备用模型实际只能试 2 次，限流窗口稍长就必然失败。
MAX_RETRIES = 4
BASE_DELAY = 1               # 基础等待 1 秒（5xx/网络类，指数退避：1→2→4→8）
# 429 单独用更长的间隔：qwen-turbo 免费档是「每分钟」级限流，
# 等 1~2 秒几乎必然还落在同一个窗口里，等 5→10→20 秒才有意义。
RATE_LIMIT_DELAY = 5
RATE_LIMIT_DELAY_MAX = 20
MAX_TOKENS_DEFAULT = 2000    # 默认最大输出 Token 数


def _supports_thinking_switch(model: str) -> bool:
    """判断模型是否接受 enable_thinking 参数。

    DeepSeek-V4 系列默认开启思考模式，需要显式关掉（原因见 call_qwen 注释）；
    老 qwen 模型（qwen-max / qwen-plus）没有这个参数，传了会直接 400。
    所以按模型名前缀判断，不盲目传。
    """
    return model.startswith("deepseek")


# ============================================================
# 第二部分：参数校验（温度/top_p/seed 不能乱填）
# ============================================================

def validate_params(temperature, top_p, seed):
    """
    参数校验函数，拦截不合法的参数值，提前报错而不是等 API 返错。
    
    名词解释：
    - temperature（温度）：0~2，越大回答越随机，越小越保守
    - top_p（核采样）：0~1，模型只从概率最高的几个词里选
    - seed（随机种子）：>=0，固定后相同输入能得到相同输出
    """
    if temperature is not None and (temperature < 0 or temperature >= 2):
        raise ValueError(f"temperature 必须在 0.0~2.0（不含2）之间，你填了 {temperature}")
    if top_p is not None and (top_p <= 0 or top_p > 1):
        raise ValueError(f"top_p 必须在 0.0~1.0（不含0，含1）之间，你填了 {top_p}")
    if seed is not None and seed < 0:
        raise ValueError(f"seed 必须 >= 0，你填了 {seed}")


# ============================================================
# 第三部分：核心调用函数（重中之重）
# ============================================================

def call_qwen(prompt, system_prompt=None, model=None,
              temperature=None, top_p=None, seed=None,
              max_tokens=None, max_retries=None, response_format=None):
    """
    带完整错误处理的大模型调用函数（2026-10-24 起主力为 DeepSeek-V4-Pro）。

    参数说明：
    - prompt:       必填，用户说的话
    - system_prompt: 选填，系统角色设定（比如"你是一个客服..."）
    - model:        选填，不传就用主模型（config.LLM_MODEL，默认 deepseek-v4-pro）
    - temperature:  选填，控制随机性 0~2
    - top_p:        选填，核采样 0~1
    - seed:         选填，随机种子 >=0
    - max_tokens:   选填，限制输出长度，默认 2000
    - max_retries:  选填，最多重试次数，默认 4
    - response_format: 选填，结构化输出开关。传 {"type": "json_object"}
                   可让模型只返回合法 JSON（注意 prompt 里必须出现 "JSON" 字样）。
                   默认 None = 不传这个参数给 API，行为与之前完全一致。

    切换到 DeepSeek-V4-Pro 后新增的两个行为（面试能讲）：
    1. 自动关闭思考模式：DeepSeek-V4 系列默认开启思考，思考 token 会挤占
       max_tokens、还会让 temperature=0 失效。分类/RAG 不需要思维链，
       因此对 deepseek 系模型自动带 enable_thinking=False
       （可用 config.LLM_ENABLE_THINKING 或环境变量 LLM_ENABLE_THINKING 改回）。
    2. 403 配额耗尽时换模型而不是重试：百炼免费额度是账号级的，
       403 AllocationQuota.FreeTierOnly 重试一万次也不会好。此时和 429
       一样切换到备用模型；两个模型都没额度时直接失败并打印充值指引。

    返回：API 返回的完整 response 对象，或者 None（全失败时）
    """
    # -------- 0. 参数校验 --------
    validate_params(temperature, top_p, seed)

    # 设置默认值
    if model is None:
        model = PRIMARY_MODEL
    if max_retries is None:
        max_retries = MAX_RETRIES
    if max_tokens is None:
        max_tokens = MAX_TOKENS_DEFAULT

    # -------- 1. 构造 messages --------
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # -------- 2. 构造调用参数 --------
    call_params = {
        "model": model,
        "messages": messages,
        "result_format": "message",
    }
    # 只传非 None 的可选参数（不传 None 给 API）
    if temperature is not None:
        call_params["temperature"] = temperature
    if top_p is not None:
        call_params["top_p"] = top_p
    if seed is not None:
        call_params["seed"] = seed
    if max_tokens is not None:
        call_params["max_tokens"] = max_tokens
    if response_format is not None:
        call_params["response_format"] = response_format
    # DeepSeek-V4 系默认开思考，这里按需关掉（只对 deepseek 传，老 qwen 会 400）
    if _supports_thinking_switch(model):
        call_params["enable_thinking"] = LLM_ENABLE_THINKING

    # -------- 3. 带重试的调用逻辑 --------
    for attempt in range(1, max_retries + 1):
        try:
            # --- 3a. 发起调用 ---
            response = Generation.call(**call_params)

            # --- 3b. 检查 HTTP 状态码 ---
            if response.status_code == 200:
                return response  # 成功，直接返回

            error_msg = response.message if hasattr(response, 'message') else str(response.status_code)
            error_text = str(error_msg).lower()
            # 403 配额耗尽（AllocationQuota.FreeTierOnly）：账号免费额度用完。
            # 账号级问题，重试和换 Key 都没用，但换模型有用。
            is_quota_403 = response.status_code == 403 and (
                "quota" in error_text or "freetier" in error_text)

            # --- 3c. 429 限流 / 403 配额耗尽：换模型，别傻等 ---
            if response.status_code == 429 or is_quota_403:
                # 第一次不可用 → 切备用模型
                if attempt == 1 and model == PRIMARY_MODEL:
                    reason = "被限流(429)" if response.status_code == 429 else "免费额度已用完(403)"
                    print(f"  ⚠ 主模型 {model} {reason}，尝试切换到备用模型 {FALLBACK_MODEL}...")
                    call_params["model"] = FALLBACK_MODEL
                    # 思考开关跟着模型走：备用模型不一定是 deepseek 系
                    if _supports_thinking_switch(FALLBACK_MODEL):
                        call_params["enable_thinking"] = LLM_ENABLE_THINKING
                    elif "enable_thinking" in call_params:
                        del call_params["enable_thinking"]
                    continue  # 立即用备用模型重试，不等待

                if is_quota_403:
                    # 主模型和备用模型都没额度了：重试无意义，直接失败并说清楚原因
                    print("  ✗ 主模型与备用模型的免费额度均已耗尽")
                    print("    → 请到阿里云百炼控制台充值，或关闭「免费额度用完即停」开关")
                    print("    → 注意：配额是账号级的，重新创建 API Key 不会重置额度")
                    return None

                # 后面再 429 → 退避等待。用 RATE_LIMIT_DELAY 而不是 BASE_DELAY：
                # 分钟级限流下等 1~2 秒等于白等（2026-10-24 实测：2 秒/4 秒各等一次，
                # 三次全部 429）。最后一次不再 sleep —— 等了也不会再重试，白卡 20 秒。
                if attempt < max_retries:
                    wait_time = min(RATE_LIMIT_DELAY * (2 ** (attempt - 2)),
                                    RATE_LIMIT_DELAY_MAX)
                    print(f"  ⚠ 被限流(429)，第 {attempt}/{max_retries} 次重试，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                else:
                    print(f"  ✗ 被限流(429)，已达最大重试次数({max_retries})")

            # --- 3d. 网络超时 ---
            elif response.status_code in [502, 503, 504]:
                if attempt < max_retries:
                    wait_time = BASE_DELAY * (2 ** (attempt - 1))
                    print(f"  ⚠ 服务端不稳定({response.status_code})，第 {attempt}/{max_retries} 次重试，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                else:
                    print(f"  ✗ 服务端不稳定({response.status_code})，已达最大重试次数({max_retries})")

            # --- 3e. 其他错误 ---
            else:
                print(f"  ✗ API 调用失败: status={response.status_code}, message={error_msg}")
                # Token 超限类错误不重试（重试也没用）
                if "exceeded" in error_text or "too long" in error_text:
                    print(f"  ✗ Token 超限，请缩短输入或调小 max_tokens")
                    return None
                # 配额/鉴权类错误不重试（重试也不会让账单变好）
                if response.status_code in (401, 403) or "quota" in error_text \
                        or "api_key" in error_text or "authentication" in error_text:
                    if "quota" in error_text or "freetier" in error_text:
                        print("    → 百炼账号免费额度已用完：控制台充值，或关闭「免费额度用完即停」")
                    else:
                        print("    → 鉴权失败：检查环境变量 DASHSCOPE_API_KEY 是否为百炼控制台创建的有效 Key")
                    return None
                # 其他错误短暂等待后重试
                wait_time = BASE_DELAY * attempt
                time.sleep(wait_time)

        except Exception as e:
            # --- 3f. 网络层面的异常（连接中断、DNS 失败等） ---
            print(f"  ⚠ 网络异常: {type(e).__name__} - {e}")
            if attempt < max_retries:
                wait_time = BASE_DELAY * (2 ** (attempt - 1))
                print(f"  第 {attempt}/{max_retries} 次重试，等待 {wait_time} 秒...")
                time.sleep(wait_time)
            else:
                print(f"  ✗ 已达最大重试次数({max_retries})，放弃")
                return None

    # 所有重试都失败了
    print(f"  ✗ 经过 {max_retries} 次重试仍然失败")
    return None


# ============================================================
# 第四部分：快捷方法（从 response 里取文本）
# ============================================================

def get_response_text(response):
    """
    从 API 返回的 response 里取出纯文本内容。
    调用前建议先判断 response 是否为 None。
    
    示例：
        resp = call_qwen("你好")
        if resp:
            print(get_response_text(resp))
    """
    if response is None:
        return None
    if response.output and response.output.choices:
        return response.output.choices[0].message.content
    return None
