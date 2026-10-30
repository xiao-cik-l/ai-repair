"""
宿舍格式规范化 (format_utils.py)
===============================
全系统唯一的「宿舍地址格式」定义处。学生表单、AI 建单、三个端的展示、
数据库存量，一律以这里为准：

    楼栋 →「X号楼」      "3" / "3栋" / "3 号 楼" / "3号楼" 全部收敛为 "3号楼"
    房间 →「XXX宿舍」    "502" / "502宿舍" / " 502 "    全部收敛为 "502宿舍"
    完整地址 = 楼栋 + "-" + 房间，即「X号楼-XXX宿舍」

为什么单独放 ai/common/：
    这个格式同时被 routes.py（Flask 表单提交）和 ai/autoorder/tools.py（AI 建单）
    引用。放任何一边都会让另一边 import 时把 Flask 或 pymysql 拖进来；
    ai/common 是纯函数、零第三方依赖，两边都能安全 import。

无效房间号（INVALID_ROOMS）：
    AI 从「我宿舍水管爆了」这种句子里会提取出 room="宿舍"——用户根本没提房间号。
    这类值不能拼成「宿舍宿舍」，必须按「房间号缺失」处理，
    与 service.py 守卫②的拒绝名单保持同一份定义。
"""

import re

# 规范化之后仍视为「没有有效房间号」的取值（守卫②直接复用这份名单）
INVALID_ROOMS = {"", "未知", "unknown", "无", "null", "none", "宿舍", "寝室"}


def normalize_building(raw) -> str:
    """楼栋统一为「X号楼」。

    "3" → "3号楼"    "3栋" → "3号楼"    "3楼" → "3号楼"
    "3 号 楼" → "3号楼"    "3号楼" → 原样返回
    空值原样返回空串（由调用方决定是否报错）。
    """
    s = str(raw or "").strip()
    if not s:
        return s
    s = re.sub(r"\s+", "", s)               # 去掉所有空白
    if s.endswith("号楼"):
        return s
    if s.endswith("栋") or s.endswith("楼"):  # "3栋"/"3楼" → 去掉尾字再补
        s = s[:-1]
    return s + "号楼"


def normalize_room(raw) -> str:
    """房间号统一为「XXX宿舍」。

    "502" → "502宿舍"    "502宿舍" → 原样返回
    " 502 " → "502宿舍"  "502 宿舍" → "502宿舍"
    命中 INVALID_ROOMS 的原样返回（如 "宿舍" → "宿舍"，交由调用方判无效）。
    """
    s = str(raw or "").strip()
    if not s:
        return s
    s = re.sub(r"\s+", "", s)
    if s in INVALID_ROOMS:
        return s
    if not s.endswith("宿舍"):
        s = s + "宿舍"
    return s


def is_valid_room(raw) -> bool:
    """规范化之后仍拿不到有效房间号时返回 False（供 service.py 守卫②使用）。

    注意判定用的是「原始值」：模型可能传 "505"（合法）也可能传 "宿舍"/"未知"/""（缺失）。
    """
    return str(raw or "").strip() not in INVALID_ROOMS


# 楼栋提取：从一句自然话里找「X楼 / X号楼 / X栋」。只认阿拉伯数字——
# 「二楼」这种中文数字在报修场景里极少且易和「二楼层」混淆，不猜。
_BUILDING_RE = re.compile(r"(\d+)\s*号?\s*[楼栋]")


def extract_building(text) -> str:
    """从任意文本里提取楼栋，统一返回「X号楼」；找不到返回空串。

    "我是2楼208宿舍的"   → "2号楼"
    "2号楼208"           → "2号楼"
    "2 号 楼 的床坏了"    → "2号楼"
    "空调不制冷"          → ""
    """
    s = str(text or "")
    m = _BUILDING_RE.search(s)
    if not m:
        return ""
    return normalize_building(m.group(1))


def strip_building_prefix(text) -> str:
    """把文本里的楼栋部分剥掉，只留房间号部分。

    "2楼208"  → "208"    "2号楼208宿舍" → "208宿舍"
    用于 room 参数规范化前：模型有时把「2楼208」整个当房间号传上来，
    先拆开，楼栋归楼栋、房间归房间，否则会存出「2楼208宿舍」这种串味数据。
    """
    s = str(text or "").strip()
    m = _BUILDING_RE.search(s)
    if not m:
        return s
    return (s[:m.start()] + s[m.end():]).strip()


# 三位纯数字房间号，首位 1-9（"505" / "402" / "208"）
_ROOM_3DIGIT_RE = re.compile(r"^([1-9])(\d{2})$")


def infer_building_from_room(room) -> str:
    """从房间号首位推断楼栋（启发式，全链路最弱一级推断）。

    规律：宿舍号第一位一般是楼号——「505」在 5 号楼、「402」在 4 号楼。
    只对**三位纯数字**房间号生效：
      - "1008" 不推断（四位，首位法失效——那可能是 10 楼 08 室）
      - "A208" / "东208" 不推断（非数字开头，不猜）
      - "08" 不推断（两位，且首位 0 没有 0 号楼）
    注意这是经验规律而非系统规则，只用来兜底——用户明说了楼号时永远以明说的为准。
    """
    s = re.sub(r"\s+", "", str(room or ""))
    s = re.sub(r"宿舍$", "", s)             # "505宿舍" → "505"（模型常按 schema 格式带后缀）
    m = _ROOM_3DIGIT_RE.match(s)
    if not m:
        return ""
    return normalize_building(m.group(1))


def full_dorm(building, room) -> str:
    """拼成完整地址「X号楼-XXX宿舍」。任一边缺失（含 INVALID_ROOMS）时
    返回另一边（展示层兜底，不抛错）；两边都缺返回 "-"。"""
    b = normalize_building(building)
    r = normalize_room(room)
    if r in INVALID_ROOMS:
        r = ""
    if b and r:
        return "%s-%s" % (b, r)
    return b or r or "-"
