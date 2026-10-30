"""ai 包 —— 宿舍报修系统的 AI 能力集合。

子包划分（对应 ai-repair 原来的 01~05 目录）：
  ai.common     模型调用封装 + Prompt 模板
  ai.classify   报修分类
  ai.rag        知识库问答（ChromaDB）
  ai.autoorder  Function Calling 自动建单
  ai.service    三合一入口 handle()

注意：本包内一律用「包导入」（from ai.xxx import yyy），
不再往 sys.path 插目录 —— 那是 ai-repair 时期的跨目录 hack，
混进 Flask 工程会和 routes.py / config.py 等同名模块撞车。
"""
