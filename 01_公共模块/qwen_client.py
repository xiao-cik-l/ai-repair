"""
带错误处理的 API 调用封装模块
============================================
把 try/except、429重试、指数退避、备用模型切换 全部封装好
以后调用通义千问只需要一行：response = call_qwen("你的问题")
"""

import dashscope
from dashscope import Generation
import time
import os

# ============================================================
# 第一部分：基础配置
# ============================================================

# 只从环境变量读取 API Key，不设兜底值（避免密钥进代码）
# 注意：这里用 .get()，读不到时返回 None 而不报错，要等调用 API 才暴露；
# 若想启动即报错，改用 os.environ["DASHSCOPE_API_KEY"]。
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# 主模型和备用模型
PRIMARY_MODEL = "qwen-max"
FALLBACK_MODEL = "qwen-plus"  # 被限流时切到这个（稍弱但够用）

# 重试配置
MAX_RETRIES = 3              # 最多重试 3 次
BASE_DELAY = 1               # 基础等待 1 秒（指数退避：1→2→4→8）
MAX_TOKENS_DEFAULT = 2000    # 默认最大输出 Token 数


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
              max_tokens=None, max_retries=None):
    """
    带完整错误处理的通义千问调用函数。

    参数说明：
    - prompt:       必填，用户说的话
    - system_prompt: 选填，系统角色设定（比如"你是一个客服..."）
    - model:        选填，不传就用主模型 qwen-max
    - temperature:  选填，控制随机性 0~2
    - top_p:        选填，核采样 0~1
    - seed:         选填，随机种子 >=0
    - max_tokens:   选填，限制输出长度，默认 2000
    - max_retries:  选填，最多重试次数，默认 3

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

    # -------- 3. 带重试的调用逻辑 --------
    for attempt in range(1, max_retries + 1):
        try:
            # --- 3a. 发起调用 ---
            response = Generation.call(**call_params)

            # --- 3b. 检查 HTTP 状态码 ---
            if response.status_code == 200:
                return response  # 成功，直接返回

            # --- 3c. 429：被限流了 ---
            elif response.status_code == 429:
                # 第一次 429 → 切备用模型
                if attempt == 1 and model == PRIMARY_MODEL:
                    print(f"  ⚠ 主模型 {model} 被限流(429)，尝试切换到备用模型 {FALLBACK_MODEL}...")
                    call_params["model"] = FALLBACK_MODEL
                    continue  # 立即用备用模型重试，不等待

                # 后面再 429 → 指数退避等待
                wait_time = BASE_DELAY * (2 ** (attempt - 1))  # 1→2→4→8
                print(f"  ⚠ 被限流(429)，第 {attempt}/{max_retries} 次重试，等待 {wait_time} 秒...")
                time.sleep(wait_time)

            # --- 3d. 网络超时 ---
            elif response.status_code in [502, 503, 504]:
                wait_time = BASE_DELAY * (2 ** (attempt - 1))
                print(f"  ⚠ 服务端不稳定({response.status_code})，第 {attempt}/{max_retries} 次重试，等待 {wait_time} 秒...")
                time.sleep(wait_time)

            # --- 3e. 其他错误 ---
            else:
                error_msg = response.message if hasattr(response, 'message') else str(response.status_code)
                print(f"  ✗ API 调用失败: status={response.status_code}, message={error_msg}")
                # Token 超限类错误不重试（重试也没用）
                if "exceeded" in str(error_msg).lower() or "too long" in str(error_msg).lower():
                    print(f"  ✗ Token 超限，请缩短输入或调小 max_tokens")
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
