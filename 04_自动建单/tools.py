import pymysql
from datetime import datetime

def get_conn():
    return pymysql.connect(
        host = "localhost",port = 3306,user = "root",password = "123456",
        database = "cjl_505",charset = "utf8mb4",
        cursorclass = pymysql.cursors.DictCursor,autocommit = False,
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

def create_work_order(room,issue,priority,category = "其他"):
   conn = get_conn()
   try:
       with conn.cursor() as cursor:
           cursor.execute(
               """INSERT INTO repair_orders
               (student_id,student_no,dorm_building,room_no,category,
               description,status,created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
               (1,"js23150301","1号楼",room,category,
                f"[优先级:{priority}]{issue}","pending_review",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
           )
       conn.commit()
       return {"order_id":cursor.lastrowid,"room":room,"issue":issue,
               "priority":priority,"status":"pending_review"}
   finally:
       conn.close()
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
                    "description":"房间号",
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
    }
]

if __name__ == "__main__":
    # 守卫①的三种情况：真实工号 / 不存在的工号
    print(check_workers_available("WX001"))   # 库里真有 → available=True
    print(check_workers_available("W001"))    # 格式不对的旧测试值 → available=False
    # 注意：下面这句会真的往 repair_orders 写一条记录（AI 建单走的就是它）
    print(create_work_order("505", "厕所堵了，需要维修", "high"))


















