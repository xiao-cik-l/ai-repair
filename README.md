# AI 驱动宿舍维修系统（AI 功能模块）

一个给宿舍维修系统加 AI 能力的模块：**报修自动分类 + FAQ 智能问答**，网页上能问能答。

- 报修分类：一句话描述问题，自动给出类别和紧急度
- 智能问答：基于 FAQ 知识库的 RAG 问答，资料里没有的问题会老实说"不知道"

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.10 + Flask | 后端 + 接口 |
| ChromaDB | 向量数据库，存 FAQ 并做相似度检索 |
| 通义千问 qwen（DashScope API） | 大模型，负责分类和回答 |
| text-embedding-v3 | 把文本转成向量 |

## 目录结构（第一周）

| 文件 | 作用 |
|------|------|
| `classifier.py` | 报修分类：调用大模型，返回 类别 + 紧急度 |
| `faq_kb.py` | FAQ 知识库：20 条维修 FAQ 存进 ChromaDB |
| `rag_qa.py` | RAG 问答核心：检索 → 拼 Prompt → 调大模型回答 |
| `chat_注释版.py` | Flask 接口：POST /api/chat，供网页调用 |
| `chat.html` | 最简聊天框：浏览器里直接问 |
| `qwen_client.py` | 通义千问 API 封装 |
| `prompt_templates.py` | 分类用的 Prompt 模板 |
| `embedding_demo.py` | Embedding 演示（猫/狗 vs 猫/汽车 相似度对比） |
| `8.14调参记录.txt` | Top-K / 阈值调参记录 |

## AI 功能说明

**1. 报修分类（classifier.py）**
用户报修一句话 → 拼 Prompt 约束 JSON 输出 → 大模型返回 `{"类别": "...", "紧急度": "..."}`。

**2. FAQ 智能问答（RAG 三步）**
```
提问 → 向量检索 Top-K 条 FAQ → 拼进 Prompt → 大模型回答
```
- 检索不到相关知识（相似度 > 0.5）就过滤掉，防止 AI 乱编
- 调参结论：Top-K = 3 效果最好（1 太窄、8 混入无关资料），阈值 = 0.5

## 运行步骤

```bash
# 1. 装依赖（本机 Python 在 D:/py/）
D:/py/python.exe -m pip install chromadb dashscope flask flask-cors

# 2. 初始化 FAQ 知识库（跑一次，把 20 条 FAQ 存进 ChromaDB）
D:/py/python.exe faq_kb.py

# 3. 命令行验证问答
D:/py/python.exe rag_qa.py

# 4. 起网页接口
D:/py/python.exe chat_注释版.py
# 浏览器打开 chat.html，即可在网页上问答
```

> 注意：所有命令要在 `第一周/` 目录下运行（代码用相对路径 import 同目录文件）。

## 进度

- [x] 报修分类（8/10）
- [x] Embedding 演示（8/11）
- [x] FAQ 知识库（8/12）
- [x] RAG 问答（8/13）
- [x] 调参（8/14）
- [x] 网页问答接口（8/15）
- [ ] Function Calling：自动建工单（第 2 周）
