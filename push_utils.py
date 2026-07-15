#!/usr/bin/env python3
import json
import os
from typing import Dict, List

import requests


def load_config() -> Dict:
    config_str = os.environ.get("MONITOR_CONFIG", "") or ""
    if not config_str.strip():
        return {}
    try:
        return json.loads(config_str)
    except Exception:
        return {}


def push_bark(config: Dict, title: str, content: str):
    url = config.get("url")
    if not url:
        return
    group = config.get("group", "")
    try:
        # POST JSON 方式，避免 URL 路径含换行/特殊字符导致请求失败
        payload = {
            "title": title,
            "body": content,
            "group": group,
        }
        # 如果 content 里有 🔊 url 行，提取作为跳转链接
        import re
        link_match = re.search(r'^🔗 (.+)$', content, flags=re.MULTILINE)
        if link_match:
            payload["url"] = link_match.group(1)
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


def push_wecom(config: Dict, title: str, content: str):
    webhook = config.get("webhook")
    if not webhook:
        return
    try:
        data = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
        requests.post(webhook, json=data, timeout=10)
    except Exception:
        pass


def _to_markdown(content: str) -> str:
    """把 '🔗 url' 行转成 Markdown 链接，便于支持 MD 的渠道渲染。"""
    import re
    return re.sub(r'^🔗 (.+)$', r'🔗 [点击查看](\1)', content, flags=re.MULTILINE)


def push_serverchan(config: Dict, title: str, content: str):
    sendkey = config.get("sendkey")
    if not sendkey:
        return
    try:
        requests.post(f"https://sctapi.ftqq.com/{sendkey}.send",
                      data={"title": title, "desp": _to_markdown(content)}, timeout=10)
    except Exception:
        pass


def push_pushplus(config: Dict, title: str, content: str):
    token = config.get("token")
    if not token:
        return
    topic = config.get("topic", "")
    try:
        requests.post("http://www.pushplus.plus/send",
                      data={"token": token, "title": title, "content": _to_markdown(content),
                            "topic": topic, "template": "markdown"},
                      timeout=10)
    except Exception:
        pass


def push_telegram(config: Dict, title: str, content: str):
    token = config.get("token")
    chat = config.get("chat")
    if not token or not chat:
        return
    # Telegram 用 HTML 链接，更可点
    import re
    html = re.sub(r'^🔗 (.+)$', r'🔗 <a href="\1">点击查看</a>', content, flags=re.MULTILINE)
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": f"{title}\n{html}",
                            "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass


def push_notification(title: str, content: str):
    config = load_config()
    push_config = config.get("push", {})
    if not push_config:
        return

    push_type = push_config.get("type")
    if not push_type:
        return

    if push_type == "bark":
        push_bark(push_config, title, content)
    elif push_type == "wecom":
        push_wecom(push_config, title, content)
    elif push_type == "serverchan":
        push_serverchan(push_config, title, content)
    elif push_type == "pushplus":
        push_pushplus(push_config, title, content)
    elif push_type == "telegram":
        push_telegram(push_config, title, content)


def push_notifications(messages: List[str], title: str = "直播监控通知"):
    if not messages:
        return

    if len(messages) == 1:
        push_notification(title, messages[0])
    else:
        content = "\n".join(messages)
        push_notification(title, content)


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        push_notification(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2:
        push_notification("直播监控", sys.argv[1])
