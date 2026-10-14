"""报修分类评测脚本：跑一遍评测集，算出准确率。

会真实调用大模型 API（默认 24 条，费用可忽略）。
想先确认能跑通、不想花钱，用 --limit 2 只跑前两条。

用法（任意目录下都能跑）：
    D:/py/python.exe "02_报修分类/评测/eval_classifier.py" --limit 2      # 冒烟测试
    D:/py/python.exe "02_报修分类/评测/eval_classifier.py" --tag before   # 正式跑，结果存档

输出三组数字：
    category 准确率   —— 类别分对了多少
    urgent   准确率   —— 紧急程度判对了多少
    完全正确率        —— 两个字段都对，才算整条对（最严格）
另外会把每条判错的列出来，方便定位是「哪类错哪类」。
"""

import sys
import os
import argparse
import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))   # 02_报修分类/评测/
_PARENT = os.path.dirname(_THIS)                     # 02_报修分类/ —— classifier.py 在这一层
# 挂两个目录：本目录找 eval_cases，父目录找 classifier。
# （classifier 自己会再挂 01_公共模块，所以这里不用管它。）
sys.path[:0] = [_THIS, _PARENT]

from classifier import classify_repair   # noqa: E402
from eval_cases import CASES             # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="只跑前 N 条（0 = 全跑），用于冒烟测试省钱")
    ap.add_argument("--tag", default="run",
                    help="结果文件后缀，如 before / after")
    args = ap.parse_args()

    cases = CASES[:args.limit] if args.limit > 0 else CASES

    ok_cat = ok_urg = ok_both = 0
    wrong = []

    print("=" * 66)
    print(f"报修分类评测   共 {len(cases)} 条   tag={args.tag}")
    print("=" * 66)

    for i, c in enumerate(cases, 1):
        got = classify_repair(c["text"])
        gc = got.get("category")
        gu = got.get("urgent")

        good_c = (gc == c["category"])
        good_u = (gu == c["urgent"])
        ok_cat += good_c
        ok_urg += good_u
        ok_both += (good_c and good_u)

        mark = "OK  " if (good_c and good_u) else "MISS"
        print(f"[{i:>2}/{len(cases)}] {mark} {c['text']}")
        print(f"        期望 {c['category']}/{c['urgent']}   "
              f"实得 {gc}/{gu}")

        if not (good_c and good_u):
            wrong.append((c["text"], c["category"], gc, c["urgent"], gu))

    n = len(cases)
    lines = []
    lines.append("=" * 66)
    lines.append(f"结果  tag={args.tag}  样本 {n} 条   "
                 f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append("=" * 66)
    lines.append(f"category 准确率 : {ok_cat}/{n} = {ok_cat / n:.1%}")
    lines.append(f"urgent   准确率 : {ok_urg}/{n} = {ok_urg / n:.1%}")
    lines.append(f"完全正确率      : {ok_both}/{n} = {ok_both / n:.1%}")
    lines.append("")
    if wrong:
        lines.append(f"判错的 {len(wrong)} 条：")
        for text, ec, gc, eu, gu in wrong:
            lines.append(f"  · {text}")
            lines.append(f"      期望 {ec}/{eu} → 实得 {gc}/{gu}")
    else:
        lines.append("全部正确。")
    report = "\n".join(lines)
    print()
    print(report)

    # 结果存档：改前跑一次 with --tag before，改后跑一次 with --tag after，
    # 两个文件对比就是「这次优化到底有没有用」的凭据。
    out = os.path.join(_THIS, f"eval_result_{args.tag}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print()
    print(f"（结果已存到 {out}）")


if __name__ == "__main__":
    main()
