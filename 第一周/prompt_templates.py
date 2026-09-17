"""
Prompt 可配置模板系统（Day 10 学习产出）
==========================================
将 Day 3-8 中硬编码的 Prompt 全部抽成可配置模板。
支持两种渲染方式：str.format()（内置，简单场景）和 Jinja2（需安装，复杂场景）。

使用方式：
    from prompt_templates import build_prompt, build_jinja_prompt
    
    # 方式一：str.format() 渲染
    prompt = build_prompt("repair_classify", user_input="空调不制冷了")
    
    # 方式二：Jinja2 渲染（支持条件/循环）
    prompt = build_jinja_prompt("repair_classify_v2", user_input="空调不制冷", urgent_only=True)
"""

import json
from functools import lru_cache

# ============================================================
# 第一部分：str.format() 模板（覆盖 Day 3-8 所有 Prompt）
# ============================================================

PROMPT_TEMPLATES = {

    # ---- Day 3：Prompt 工程五大场景 ----

    "summarize": (
        "请用一句话总结以下用户评论的要点，限 {max_words} 字以内：\n\n"
        "\"\"\"{content}\"\"\""
    ),

    "infer_sentiment": (
        "请从以下评论中提取信息，以 JSON 格式输出：\n"
        "1. 情感倾向（正面/负面/中性）\n"
        "2. 提及的优缺点（列表）\n"
        "3. 是否推荐购买（是/否）\n\n"
        "\"\"\"{content}\"\"\""
    ),

    "transform_translate": (
        "请将以下{text_label}翻译为{target_lang}，语气调整为{tone}：\n\n"
        "\"{content}\""
    ),

    "expand_content": (
        "你是一位{role}。根据以下信息，写一封回复邮件：\n"
        "- 客户问题：{issue}\n"
        "- 解决方案：{solution}\n"
        "- 语气：{tone}\n\n"
        "邮件长度 {min_len}-{max_len} 字。"
    ),

    "chatbot_system": (
        "你是一个{domain}的客服助手。只回答与{domain}相关的问题。\n"
        "不知道的就说'{fallback_msg}'。不要编造信息。"
    ),

    # ---- Day 6/7：智能报修分类 ----

    "repair_classify": (
        "请将以下报修描述分类，以json格式输出"
        "（直接输出json，不要markdown代码块），包含：\n"
        "category：维修类别（{categories}）\n"
        "urgent：是否紧急（是/否）\n"
        "报修描述：{user_input}"
    ),

    "repair_classify_system": "你是一个{domain}，用中文回答。",

    "work_order_generate": (
        "根据以下报修信息，生成一份标准化工单描述（50字以内）：\n"
        "报修类别：{category}\n"
        "报修描述：{user_input}\n"
        "紧急程度：{urgent}"
    ),

    "urgency_check": (
        "判断以下报修描述的紧急程度，输出 JSON：\n"
        "{{\"level\": \"紧急/常规/低优先级\", \"reason\": \"判断理由\"}}\n\n"
        "报修描述：{user_input}"
    ),

    # ---- Day 8：JSON 结构化输出三层约束 ----

    # Level 1：基础格式约束
    "json_level1": (
        "请从以下内容中提取信息，以 JSON 格式输出。\n"
        "要求：\n"
        "- 直接输出 JSON，不要 markdown 代码块\n"
        "- 不要输出任何解释性文字\n\n"
        "JSON 结构：\n"
        "{schema}\n\n"
        "内容：\n"
        "\"\"\"{content}\"\"\""
    ),

    # Level 2：格式 + 输出示例
    "json_level2": (
        "请从以下内容中提取信息，以 JSON 格式输出。\n\n"
        "# 格式要求 #\n"
        "1. 直接输出 JSON，不要 markdown 代码块\n"
        "2. 不要输出任何解释性文字\n"
        "3. 严格按以下结构输出，不能增减字段\n\n"
        "# JSON 结构 #\n"
        "{schema}\n\n"
        "# 输出示例 #\n"
        "{example}\n\n"
        "# 待处理内容 #\n"
        "\"\"\"{content}\"\"\""
    ),

    # Level 3：格式 + 示例 + 字段说明
    "json_level3": (
        "请从以下内容中提取信息，以 JSON 格式输出。\n\n"
        "# 任务 #\n"
        "从用户输入中提取结构化信息，严格按照指定 JSON 格式输出。\n\n"
        "# 格式要求 #\n"
        "1. 只输出 JSON，不输出任何其他文字\n"
        "2. 不使用 markdown 代码块\n"
        "3. 严格按以下结构输出，不能增减字段\n"
        "4. 字段值不能为空，缺少信息填 \"未知\"\n\n"
        "# JSON 结构 #\n"
        "{schema}\n\n"
        "# 字段说明 #\n"
        "{field_descriptions}\n\n"
        "# 输出示例 #\n"
        "{example}\n\n"
        "# 待处理内容 #\n"
        "\"\"\"{content}\"\"\"\n\n"
        "# 输出 #\n"
    ),
}


# ============================================================
# 第二部分：str.format() 渲染函数
# ============================================================

def build_prompt(template_name: str, **kwargs) -> str:
    """
    用 str.format() 渲染 Prompt 模板。

    参数：
        template_name: PROMPT_TEMPLATES 中的键名
        **kwargs:       模板变量

    返回：
        渲染后的 Prompt 字符串

    示例：
        prompt = build_prompt("repair_classify", user_input="空调不制冷")
    """
    if template_name not in PROMPT_TEMPLATES:
        raise KeyError(
            f"模板 '{template_name}' 不存在，可选：{list(PROMPT_TEMPLATES.keys())}"
        )
    template = PROMPT_TEMPLATES[template_name]
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise KeyError(f"模板 '{template_name}' 缺少变量：{e}")


# ============================================================
# 第三部分：Jinja2 模板（复杂场景：条件/循环/宏）
# ============================================================

JINJA_TEMPLATES = {

    "repair_classify_v2": (
        "请将以下报修描述分类，以 JSON 格式输出（直接输出 JSON，不要 markdown 代码块）。\n\n"
        "可选维修类别：{{ categories | join('、') }}。\n"
        "{% if urgent_only %}仅判断是否紧急（是/否）。\n{% endif %}"
        "报修描述：{{ user_input }}"
    ),

    "json_level3_v2": (
        "请从以下内容中提取信息，以 JSON 格式输出。\n\n"
        "# 格式要求 #\n"
        "1. 只输出 JSON，不输出任何其他文字\n"
        "2. 不使用 markdown 代码块\n"
        "3. 严格按以下结构输出，不能增减字段\n\n"
        "# JSON 结构 #\n"
        "{{ schema }}\n\n"
        "{% if field_descriptions %}"
        "# 字段说明 #\n"
        "{% for field, desc in field_descriptions.items() %}"
        "- {{ field }}：{{ desc }}\n"
        "{% endfor %}"
        "{% endif %}\n"
        "{% if examples %}"
        "# 输出示例 #\n"
        "{% for ex in examples %}"
        "示例 {{ loop.index }}：{{ ex }}\n"
        "{% endfor %}"
        "{% endif %}\n"
        "# 待处理内容 #\n"
        "\"\"\"{{ content }}\"\"\""
    ),

    "few_shot_classify": (
        "任务：将用户报修描述分类。\n\n"
        "{% for ex in examples %}"
        "示例 {{ loop.index }}：\n"
        "输入：{{ ex.input }}\n"
        "输出：{{ ex.output }}\n\n"
        "{% endfor %}"
        "现在请分类：\n"
        "输入：{{ user_input }}\n"
        "输出："
    ),

    "chatbot_with_context": (
        "你是一个{{ domain }}的智能助手。\n\n"
        "{% if system_rules %}"
        "规则：\n"
        "{% for rule in system_rules %}"
        "{{ loop.index }}. {{ rule }}\n"
        "{% endfor %}\n"
        "{% endif %}"
        "{% if knowledge_context %}"
        "参考知识：\n"
        "{{ knowledge_context }}\n"
        "{% endif %}"
        "用户问题：{{ user_input }}"
    ),

    "work_order_generate_v2": (
        "根据以下报修信息，生成标准化工单。\n\n"
        "{% if category %}报修类别：{{ category }}{% endif %}\n"
        "{% if location %}报修位置：{{ location }}{% endif %}\n"
        "报修描述：{{ user_input }}\n"
        "{% if urgent %}紧急程度：{{ urgent }}{% endif %}\n\n"
        "工单要求：\n"
        "- 描述客观准确，50字以内\n"
        "- 包含关键故障信息\n"
        "- 便于维修人员快速理解"
    ),
}


# ============================================================
# 第四部分：Jinja2 渲染函数
# ============================================================

@lru_cache(maxsize=1)
def _get_jinja_env():
    """懒加载 Jinja2 环境，没装 jinja2 时自动降级"""
    try:
        from jinja2 import Environment, DictLoader
        env = Environment(
            loader=DictLoader(JINJA_TEMPLATES),
            trim_blocks=True,       # 自动去除块标签后的换行
            lstrip_blocks=True,     # 自动去除行首到块标签的空白
            keep_trailing_newline=False,
        )
        return env
    except ImportError:
        return None


def build_jinja_prompt(template_name: str, **kwargs) -> str:
    """
    用 Jinja2 渲染 Prompt 模板（支持条件/循环/过滤器）。

    参数：
        template_name: JINJA_TEMPLATES 中的键名
        **kwargs:       模板变量

    返回：
        渲染后的 Prompt 字符串

    示例：
        prompt = build_jinja_prompt("repair_classify_v2",
                                    user_input="空调不制冷",
                                    categories=["电器","水管","门窗"],
                                    urgent_only=True)
    """
    env = _get_jinja_env()
    if env is None:
        raise ImportError(
            "Jinja2 未安装。请运行：pip install jinja2\n"
            "或使用 build_prompt() 替代（基于 str.format）"
        )
    if template_name not in JINJA_TEMPLATES:
        raise KeyError(
            f"Jinja2 模板 '{template_name}' 不存在，可选：{list(JINJA_TEMPLATES.keys())}"
        )
    template = env.get_template(template_name)
    return template.render(**kwargs)


# ============================================================
# 第五部分：统一调用入口（自动选择渲染方式）
# ============================================================

def render_prompt(template_name: str, _use_jinja: bool = False, **kwargs) -> str:
    """
    统一 Prompt 渲染入口。

    参数：
        template_name: 模板名称（自动在两个字典中查找）
        _use_jinja:    是否使用 Jinja2 渲染（默认 False，用 str.format）
        **kwargs:      模板变量

    返回：
        渲染后的 Prompt 字符串
    """
    if _use_jinja:
        return build_jinja_prompt(template_name, **kwargs)
    else:
        return build_prompt(template_name, **kwargs)


# ============================================================
# 第六部分：预设参数（常用的默认配置）
# ============================================================

PRESETS = {
    "repair_classify": {
        "categories": "电器/水管/门窗/家具",
    },
    "repair_classify_system": {
        "domain": "物业报修分类助手",
    },
    "summarize": {
        "max_words": 30,
    },
    "transform_translate": {
        "text_label": "中文",
        "target_lang": "英文",
        "tone": "正式商务风格",
    },
    "expand_content": {
        "role": "客服助理",
        "tone": "专业、关怀",
        "min_len": 100,
        "max_len": 150,
    },
    "chatbot_system": {
        "domain": "宿舍维修系统",
        "fallback_msg": "请拨打维修热线 400-xxx",
    },
    "json_level1": {
        "schema": '{\n  "category": "",\n  "urgent": ""\n}',
    },
    "json_level2": {
        "schema": '{\n  "category": "",\n  "urgent": "",\n  "description": ""\n}',
        "example": '{\n  "category": "水管",\n  "urgent": "否",\n  "description": "厕所管道不下水"\n}',
    },
    "json_level3": {
        "schema": '{\n  "category": "",\n  "urgent": "",\n  "priority": "",\n  "description": ""\n}',
        "field_descriptions": (
            "- category：维修类别，可选：电器/水管/门窗/家具\n"
            "- urgent：是否紧急，是/否\n"
            "- priority：优先级，紧急/常规/低优先级\n"
            "- description：标准化工单描述，50字以内"
        ),
        "example": '{\n  "category": "电器",\n  "urgent": "是",\n  "priority": "紧急",\n  "description": "空调不制冷，需尽快维修"\n}',
    },
}


def build_with_preset(template_name: str, **override_kwargs) -> str:
    """
    使用预设默认值 + 自定义覆盖来渲染 Prompt。

    参数：
        template_name: 模板名称
        **override_kwargs: 覆盖预设的变量

    返回：
        渲染后的 Prompt 字符串

    示例：
        # 预设已有 categories，只需传 user_input
        prompt = build_with_preset("repair_classify", user_input="空调不制冷")
    """
    preset = PRESETS.get(template_name, {})
    merged = {**preset, **override_kwargs}
    return build_prompt(template_name, **merged)


# ============================================================
# 使用示例
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("示例1：报修分类（str.format + 预设）")
    print("=" * 60)
    prompt = build_with_preset("repair_classify", user_input="厕所管道不下水了，已经三天了")
    print(prompt)
    print()

    print("=" * 60)
    print("示例2：报修分类系统角色（str.format + 预设）")
    print("=" * 60)
    system = build_with_preset("repair_classify_system")
    print(system)
    print()

    print("=" * 60)
    print("示例3：JSON Level 3 约束（str.format + 预设）")
    print("=" * 60)
    prompt = build_with_preset("json_level3", content="502宿舍空调完全不制冷，已经两天了")
    print(prompt)
    print()

    print("=" * 60)
    print("示例4：Few-shot 分类（Jinja2）")
    print("=" * 60)
    try:
        prompt = build_jinja_prompt(
            "few_shot_classify",
            user_input="宿舍门锁坏了打不开",
            examples=[
                {"input": "空调不制冷", "output": "电器"},
                {"input": "水龙头漏水", "output": "水管"},
            ]
        )
        print(prompt)
    except ImportError as e:
        print(f"（需安装 Jinja2：pip install jinja2）")
        print(f"错误：{e}")
    print()

    print("=" * 60)
    print("示例5：带上下文的聊天机器人（Jinja2）")
    print("=" * 60)
    try:
        prompt = build_jinja_prompt(
            "chatbot_with_context",
            domain="宿舍维修系统",
            system_rules=[
                "只回答与宿舍维修相关的问题",
                "不知道的就说'请拨打维修热线'",
                "不要编造信息",
            ],
            knowledge_context="常见维修：空调维修请联系物业8号楼201室，周一至周五8:00-17:00。",
            user_input="空调坏了找谁？",
        )
        print(prompt)
    except ImportError as e:
        print(f"（需安装 Jinja2：pip install jinja2）")
        print(f"错误：{e}")
