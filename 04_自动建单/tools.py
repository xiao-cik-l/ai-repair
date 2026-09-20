import pymysql
from datetime import datetime

def get_conn():
    return pymysql.connect(
        host = "localhost",port = 3306,user = "root",password = "123456",
        database = "cjl_505",charset = "utf8mb4",
        cursorclass = pymysql.cursors.DictCursor,autocommit = False,
    )

def check_workers_available(worker_id):
    available = worker_id =="W001"
    return {"worker_id": worker_id, "available": available}

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
            "description":"检查工人空闲状态",
            "parameters":{
                "type":"object",
                "properties":{
                    "worker_id":{
                        "type":"string",
                        "description":"工人id",

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
    print(check_workers_available("W001"))
    print(create_work_order("505", "厕所堵了，需要维修", "high"))


















