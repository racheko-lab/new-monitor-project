#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

CONFIG_FILE = "config.json"
STATUS_FILE = "status.json"
HISTORY_FILE = "history.json"
HISTORY_MAX = 200


def load_config() -> Dict:
    if os.environ.get("MONITOR_CONFIG"):
        return json.loads(os.environ["MONITOR_CONFIG"])
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_status() -> Dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_history() -> List:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_status(status: Dict):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def save_history(history: List):
    history = history[-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_history(event_type: str, message: str):
    history = load_history()
    history.append({
        "time": datetime.now().isoformat(),
        "type": event_type,
        "message": message
    })
    save_history(history)


def push_notification(config: Dict, title: str, content: str):
    push_config = config.get("push", {})
    if not push_config:
        return

    push_type = push_config.get("type")
    if not push_type:
        return

    try:
        if push_type == "bark":
            url = push_config.get("url")
            group = push_config.get("group", "")
            requests.get(f"{url}/{title}/{content}?group={group}")
        elif push_type == "wecom":
            webhook = push_config.get("webhook")
            data = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
            requests.post(webhook, json=data)
        elif push_type == "serverchan":
            sendkey = push_config.get("sendkey")
            requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                          data={"title": title, "desp": content})
        elif push_type == "pushplus":
            token = push_config.get("token")
            topic = push_config.get("topic", "")
            requests.post("http://www.pushplus.plus/send",
                          data={"token": token, "title": title, "content": content, "topic": topic})
        elif push_type == "telegram":
            token = push_config.get("token")
            chat = push_config.get("chat")
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": f"{title}\n{content}"})
    except Exception as e:
        print(f"推送失败: {e}")


def check_target(target: Dict) -> Dict:
    url = target.get("url")
    try:
        response = requests.get(url, timeout=10)
        return {
            "id": target["id"],
            "name": target["name"],
            "url": url,
            "status": "online" if response.status_code == 200 else "offline",
            "status_code": response.status_code,
            "last_check": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "id": target["id"],
            "name": target["name"],
            "url": url,
            "status": "error",
            "error": str(e),
            "last_check": datetime.now().isoformat()
        }


def main():
    config = load_config()
    targets = config.get("targets", [])
    current_status = load_status()
    need_push = []

    for target in targets:
        result = check_target(target)
        target_id = target["id"]

        previous_status = current_status.get(target_id, {}).get("status")
        if previous_status != result["status"]:
            event_type = "status_change"
            message = f"{target['name']} 状态变更: {previous_status or '未知'} -> {result['status']}"
            print(message)
            add_history(event_type, message)

            if result["status"] == "online":
                need_push.append((f"✅ {target['name']} 上线", f"URL: {target['url']}"))
            elif result["status"] == "offline":
                need_push.append((f"❌ {target['name']} 下线", f"URL: {target['url']}"))

        current_status[target_id] = result

    save_status(current_status)

    for title, content in need_push:
        push_notification(config, title, content)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        config = load_config()
        interval = config.get("check_interval", 60)
        print(f"持续监控模式，每 {interval} 秒检测一次")
        while True:
            main()
            time.sleep(interval)
    else:
        main()
