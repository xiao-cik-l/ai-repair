import os
import sys

import pymysql
from datetime import datetime

# ============================================================
# 数据库连接参数：统一走 config.py（支持环境变量覆盖）
# ============================================================
# ai-repair 时期这里是硬编码的 root/123456 + 库名 cjl_505。
# 搬进正式版后改从 config 读，密码不再出现在 AI 代码里。
# try/except 只为兼容「直接跑本目录脚本」：那时 sys.path[0] 是 ai/autoorder/，
# 正式版根目录不在路径上，需要补一次；作为 ai 包被 Flask 导入时这段不会触发。
try:
    from config import (AI_DEDUP_MINUTES, MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD,
                        MYSQL_PORT, MYSQL_USER)
except ImportError:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from config import (AI_DEDUP_MINUTES, MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD,
                        MYSQL_PORT, MYSQL_USER)

# 宿舍格式规范化：AI 建单和学生表单提交（routes.py）共用 ai/common/format_utils，
# 保证两条路落库的楼栋/房间格式完全一致（「X号楼-XXX宿舍」）。
# 直接跑本目录脚本时 ai 包的父目录不在 sys.path，这里同样补一次。
try:
    from ai.common.format_utils import (INVALID_ROOMS, extract_building,
                                        infer_building_from_room,
                                        normalize_building, normalize_room,
                                        strip_building_prefix)
except ImportError:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from ai.common.format_utils import (INVALID_ROOMS, extract_building,
                                        infer_building_from_room,
                                        normalize_building, normalize_room,
                                        strip_building_prefix)


def get_conn():
    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
        database=MYSQL_DB, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )

def check_workers_available(worker_id):
    """检查维修工能不能接单 —— 这是守卫①的数据来源。

    worker_id 传的是【工号】，对应 workers 表的 worker_no 列，格式形如 WX001。
    判断规则两条，都用 SQL 落地，不再返回写死的值：
      1. 工号必须真实存在于 workers 表（不存在 = 无效工号，不能派单）
      2. 该维修工手上不能有未完工的工单（status 为 approved 或 accepted）
    返回 available=True 表示可以派单；False 时 reason 说明原因。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, worker_no FROM workers WHERE worker_no = %s",
                (worker_id,),
            )
            worker = cursor.fetchone()

            # 规则1：工号不在 workers 表里，直接拒绝（以前这里是比较写死的字符串）
            if worker is None:
                return {"worker_id": worker_id, "available": False,
                        "reason": f"工号 {worker_id} 在 workers 表中不存在"}

            # 规则2：手上还有没干完的活，就不再派新单
            cursor.execute(
                """SELECT COUNT(*) AS busy FROM repair_orders
                WHERE worker_id = %s AND status IN ('approved', 'accepted')""",
                (worker["id"],),
            )
            busy = cursor.fetchone()["busy"]

            if busy:
                return {"worker_id": worker_id, "worker_name": worker["name"],
                        "available": False,
                        "reason": f"该维修工还有 {busy} 张未完工工单"}

            return {"worker_id": worker_id, "worker_name": worker["name"],
                    "available": True, "reason": "在岗，可派单"}
    finally:
        conn.close()

def create_work_order(room,issue,priority,category = "其他",identity=None,building=None):
   """创建工单。

   identity: 当前登录学生的身份，形如 {"student_id": 12, "student_no": "js23150301",
             "dorm_building": "1号楼"}。由 Flask 路由从 session 注入。
             不传（独立脚本 / 命令行演示）时沿用下面三个默认值，行为与 ai-repair 一致。

   building: 楼栋，格式如「2号楼」。对应 tools schema 里的同名可选参数
             （模型从用户原话显式抽取的值）；service.py 还会在调工具前用
             extract_building(user_input) 兜底注入一次。

   ⚠️ 楼栋解析顺序（从最可靠到兜底）——历史上这里写死 "1号楼"，
      导致用户说「我是2楼208宿舍的」也全部落 1 号楼（工单 #25 就是这个坑）：
         1. building 参数              模型显式抽取 / 调用方从 user_input 正则提取
         2. identity["dorm_building"]  学生身份（session 存真实楼栋后生效）
         3. room / issue 文本里再试一次 extract_building（模型可能把「2楼208」
            整个塞进 room）
         4. infer_building_from_room   房间号首位推断（启发式：505→5 号楼、
            402→4 号楼；仅三位纯数字生效）——「505 水管爆了」这种不提楼号的
            句子靠这一级救回来
         5. 都失败才用默认 "1号楼"
      students 表当前没有宿舍列（阶段③ 库表改造项），第 2 级暂不生效。

   宿舍格式（与 routes.py 表单提交共用 format_utils，全系统唯一口径）：
       room          "505" → "505宿舍"；"2楼208" 先剥掉楼栋再规范化为 "208宿舍"
                     "宿舍"等无效值直接抛 ValueError 拒绝建单
       dorm_building "5"   → "5号楼"
   """
   # 默认身份（历史硬编码，独立脚本演示用）
   student_id, student_no = 1, "js23150301"
   if identity:
       student_id = identity.get("student_id") or student_id
       student_no = identity.get("student_no") or student_no

   # ---- 楼栋五级解析（见上方 docstring）----
   room = strip_building_prefix(str(room or ""))   # 先拆「2楼208」→「208」，楼栋房间分开算
   dorm_building = (
       normalize_building(building)                    # 1. 调用方/模型显式给
       or (identity or {}).get("dorm_building") or ""  # 2. 学生身份
   )
   dorm_building = (dorm_building
                    or extract_building(room)          # 3. room/issue 文本
                    or extract_building(issue)
                    or infer_building_from_room(room)) # 4. 房间号首位启发式
   dorm_building = normalize_building(dorm_building) or "1号楼"  # 5. 默认值

   # ---- 房间号规范化：补「宿舍」后缀 ----
   room = normalize_room(room)
   if room in INVALID_ROOMS:
       raise ValueError("房间号无效或缺失: %r，拒绝建单" % room)

   conn = get_conn()
   try:
       with conn.cursor() as cursor:
           # ---- 幂等去重（2026-10-25 新增）----
           # 同一学生 + 同一房间 + 同一类别，在 AI_DEDUP_MINUTES（默认 5）分钟内
           # 已有未完结的工单 → 直接返回旧单号，不再 INSERT。
           # 防的是三件事：用户手抖连点两次、前端重试、模型在同一轮里重复调工具。
           # 注意 status 只算未完结的：已完成的工单不受影响，下次报修照常新建。
           cursor.execute(
               """SELECT id FROM repair_orders
               WHERE student_id = %s AND room_no = %s AND category = %s
                 AND status IN ('pending_review', 'approved', 'accepted')
                 AND created_at > DATE_SUB(NOW(), INTERVAL %s MINUTE)
               ORDER BY id DESC LIMIT 1""",
               (student_id, room, category, AI_DEDUP_MINUTES),
           )
           dup = cursor.fetchone()
           if dup:
               return {"duplicate": True, "order_id": dup["id"], "room": room,
                       "issue": issue, "priority": priority,
                       "status": "pending_review",
                       "message": "该房间同类问题刚刚提交过，未重复建单"}

           cursor.execute(
               """INSERT INTO repair_orders
               (student_id,student_no,dorm_building,room_no,category,
               description,status,created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
               (student_id,student_no,dorm_building,room,category,
                f"[优先级:{priority}]{issue}","pending_review",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
           )
       conn.commit()
       return {"order_id":cursor.lastrowid,"room":room,"issue":issue,
               "priority":priority,"status":"pending_review"}
   finally:
       conn.close()
def answer_faq(question):
    """查询本地维修知识库并回答（RAG）。

    为什么做成「工具」而不是在主流程里 if/else 判断：让模型自己决定这是提问
    还是报修，取代原来的关键词硬匹配 —— 「水管爆了」不包含
    「修/坏/漏/堵/响/裂」任何一个字，老逻辑会把它判去问答、不建单。
    """
    # 局部 import：faq_kb 会拉起 chromadb（几百 MB），放模块顶层会让
    # 只用到建单的地方也背上这个重依赖。
    from ai.rag.rag_qa import rag_answer

    try:
        answer = rag_answer(question)
    except Exception as exc:  # 知识库异常不该让整轮对话崩掉
        return {"error": f"知识库检索失败: {exc}"}

    if not answer or not answer.strip():
        return {"answer": "资料里没有相关内容，建议提交报修或联系管理员。"}
    return {"answer": answer}


tools = [
    {
        "type":"function",
        "function":{
            "name":"check_workers_available",
            "description":"按工号查询维修工能否接单（是否在岗、手上是否有未完工工单）",
            "parameters":{
                "type":"object",
                "properties":{
                    "worker_id":{
                        "type":"string",
                        "description":"维修工工号，格式形如 WX001（对应 workers.worker_no 列）",

                    }
                },
                "required":["worker_id"]
            }
        }
    }, 
    {
        "type" :"function",
        "function":{
            "name":"create_work_order",
            "description":"创建工单",
            "parameters":{
                "type":"object",
                "properties":{
                    "room":{
                    "type":"string",
                    "description":"房间号，格式如 505宿舍（只填 505 也可以，保存时会自动补全）",
                    },
                    "building":{
                    "type":"string",
                    "description":"宿舍楼栋，格式如 2号楼。用户原话里提到「X楼/X号楼」时必须提取（如「我是2楼208宿舍的」→ building=\"2号楼\"）；用户完全没提楼栋时留空，不要默认填 1号楼",
                    },
                    "issue":{
                        "type":"string",
                        "description":"问题描述",
                    },
                    "priority":{
                        "type":"string",
                        "enum": ["low", "medium", "high"],
                        "description":"优先级：low 低 / medium 中 / high 高",
                    },
                    "category":{
                        "type":"string",
                        "description":"分类"
                    }
                },
                "required":["room","issue","priority","category"]
            } 
        }
    },
    {
        "type": "function",
        "function": {
            "name": "answer_faq",
            "description": (
                "查询宿舍维修知识库并回答用户的问题（报修流程、常见故障怎么处理、"
                "注意事项）。用户是在「问怎么做」而不是「报告一处具体故障」时用它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用户的问题原话，尽量保持原样不要改写",
                    }
                },
                "required": ["question"],
            },
        },
    },
]

if __name__ == "__main__":
    # 守卫①的三种情况：真实工号 / 不存在的工号
    print(check_workers_available("WX001"))   # 库里真有 → available=True
    print(check_workers_available("W001"))    # 格式不对的旧测试值 → available=False
    # 注意：下面这句会真的往 repair_orders 写一条记录（AI 建单走的就是它）
    print(create_work_order("505", "厕所堵了，需要维修", "high"))


















