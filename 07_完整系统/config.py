"""
配置模块 (config.py)
====================
集中管理系统所有配置常量：MySQL 连接、SMTP 邮箱、Flask 应用、文件上传、大模型等。
"""

import os

# ============================================================
# MySQL 连接配置
# ============================================================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
MYSQL_DB = os.getenv("MYSQL_DB", "cjl_505")

# ============================================================
# Flask 应用配置
# ============================================================
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
CODE_EXPIRE_MINUTES = int(os.getenv("CODE_EXPIRE_MINUTES", "5"))
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 最大上传 16MB

# 上传目录（基于项目根目录的 static/uploads）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

# ============================================================
# 文件上传配置
# ============================================================
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许上传"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ============================================================
# QQ 邮箱 SMTP 配置
# ============================================================
QQ_SMTP_HOST = "smtp.qq.com"
QQ_SMTP_PORT = 465
# 只从环境变量读，不给明文默认值 —— 公开仓库里更不能带授权码。
# 没有 .env 时验证码功能不可用，属预期行为：页面能打开，但永远收不到验证码。
QQ_SMTP_USER = os.getenv("SMTP_USER", "")
QQ_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# 默认演示账号使用的邮箱。公开版本不写死具体地址，
# 直接取发件邮箱 SMTP_USER —— 演示账号收验证码走的就是这个邮箱。
DEMO_EMAIL = os.getenv("SMTP_USER", "demo@example.com")
QQ_SMTP_SENDER = os.getenv("SMTP_SENDER", QQ_SMTP_USER)

# 没有邮箱授权码时的兜底：设为 1 则验证码打印到日志、不真实发信。
# 只用于本地和容器演示，正式环境必须保持 0。
DEMO_LOGIN_CODE = os.getenv("DEMO_LOGIN_CODE", "0").lower() in ("1", "true", "yes")

# ============================================================
# 大模型（LLM）配置 —— 2026-10-24 由通义千问切换为 DeepSeek-V4-Pro
# ============================================================
# 模型仍托管在阿里云百炼（Model Studio），走百炼的 OpenAI 兼容端点，
# 所以 Key 还是百炼控制台创建的那把（2026 年新版格式 sk-ws-...），
# 与向量模型 text-embedding-v3 共用同一个环境变量 DASHSCOPE_API_KEY。
#
# 两个必须知道的事实：
#   1. 配额是账号级的 —— 重新创建 API Key 不会重置免费额度。主模型额度耗尽
#      （403 AllocationQuota.FreeTierOnly）时，qwen_client.py / service.py 会
#      自动降级到 LLM_FALLBACK_MODEL，额度恢复后自动回到主模型。
#   2. DeepSeek-V4 系列默认开启思考模式。分类/建单/FAQ 都不需要思维链，且思考
#      模式下 temperature=0 不生效、思考 token 还会挤占 max_tokens，所以默认
#      关闭。老 qwen 模型没有 enable_thinking 参数，传了会 400 —— 代码里按
#      模型名前缀判断是否传（见 ai/common/qwen_client.py 和 ai/service.py）。
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
#  3. 必须用「具体快照名」而不是「别名」（2026-10-24 实测踩坑）：
#     百炼的免费额度是按「模型快照」独立发放的。别名 deepseek-v4-pro 指向的是
#     平台当前最新快照，那条额度已耗尽 → 403 AllocationQuota.FreeTierOnly；
#     而控制台给用户展示并发放额度的是快照 deepseek-v4-pro-0813（剩余 1M tokens
#     100%），用全名调用直接 200。别名的解析目标会随平台升级而漂移，写死快照名
#     反而稳定。代价是平台下线该快照时要手动改这里。
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro-0813")
# 备用模型选 qwen-turbo 的原因（2026-10-24 用新 Key 实测）：
#   qwen-plus / qwen-max / qwen-flash 免费额度均已耗尽（403）；
#   deepseek-v4-flash 在该账号不存在（model_not_found）；
#   只有 qwen-turbo 还有额度（返回 429 限流而非 403 配额）。
# 注意：qwen-turbo 免费档 RPM 很低，被连打时 429 会持续较久，重试间隔不能太短
#（见 qwen_client.py / service.py 的退避参数）。
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "qwen-turbo")
LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING", "0").lower() in ("1", "true", "yes")

# ============================================================
# AI 链路稳定性参数（2026-10-25 新增，围绕「模型会抽风」做的四道闸）
# ============================================================
# ① 单次模型请求超时（秒）。openai SDK 默认 600 秒，一个卡住的请求会占死
#    一个 Flask worker；压到 20 秒，超时后走自己的重试/降级逻辑。
AI_REQUEST_TIMEOUT = float(os.getenv("AI_REQUEST_TIMEOUT", "20"))

# ② 工具调用最大轮数。模型如果反复调工具（工具一直返回 error 时最容易发生），
#    没有上限就是无限循环、无限烧 token。超过就交人工，不再继续。
AI_MAX_TOOL_ROUNDS = int(os.getenv("AI_MAX_TOOL_ROUNDS", "5"))

# ③ 幂等窗口（分钟）。同一学生 + 同一房间 + 同一类别，在这个窗口内重复提交
#    直接返回上一张工单号，不再 INSERT —— 防手抖连点、防网络重试重复建单。
AI_DEDUP_MINUTES = int(os.getenv("AI_DEDUP_MINUTES", "5"))

# ④ 多轮上下文保留轮数（一问一答算一轮）。存 Flask session，太少接不上追问，
#    太多会把 cookie 撑大（session 默认存客户端）。
AI_HISTORY_ROUNDS = int(os.getenv("AI_HISTORY_ROUNDS", "4"))
