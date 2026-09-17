from prompt_templates import build_with_preset
from qwen_client import call_qwen,get_response_text
import json

def classify_repair(text:str) ->dict:
    prompt = build_with_preset("repair_classify",user_input = text)
    response = call_qwen(prompt = prompt, temperature = 0.1,max_tokens = 200)
    return json.loads(get_response_text(response))

if __name__ =="__main__":
    texts = [
        "厕所洗手池坏了，都五天了",
        "宿舍空调漏水，一直在滴答滴答的",
        "床老是吱吱响，睡觉都不舒服",
        "椅子坏了，坐上去就会倒",
        "墙上有个裂缝，会掉渣下来"
    ]
    for t in texts:
        result  = classify_repair(t)
        print(f"报修:{t}")
        print(f"分类:{result}")
        print("===================================")