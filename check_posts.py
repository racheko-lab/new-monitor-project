#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests

ROOMS_FILE = "rooms.json"
STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
HISTORY_MAX = 200


def load_rooms() -> List[Dict]:
    with open(ROOMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> Dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_history() -> List[Dict]:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def save_history(history: List[Dict]):
    history = history[-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_history(message: str, event_type: str = "post"):
    history = load_history()
    history.append({
        "time": datetime.now().isoformat(),
        "type": event_type,
        "message": message
    })
    save_history(history)


def get_sec_uid_from_html(html: str) -> Optional[str]:
    match = re.search(r'"sec_uid":"([^"]+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'sec_uid=([^&"]+)', html)
    if match:
        return match.group(1)
    return None


def check_douyin_posts(room_id: str, name: str) -> List[str]:
    notifications = []
    try:
        resp = requests.get(f"https://live.douyin.com/{room_id}", timeout=10)
        sec_uid = get_sec_uid_from_html(resp.text)

        if not sec_uid:
            return notifications

        api_url = f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_uid={sec_uid}&count=10&cursor=0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(api_url, headers=headers, timeout=10)
        data = resp.json()

        if data.get("status_code") == 0:
            posts = data.get("aweme_list", [])
            state = load_state()
            key = f"douyin_posts_{room_id}"
            seen_posts = state.get(key, {}).get("seen_posts", [])

            new_posts = []
            for post in posts:
                aweme_id = post.get("aweme_id")
                if aweme_id and aweme_id not in seen_posts:
                    new_posts.append(post)

            if new_posts:
                seen_posts.extend([p.get("aweme_id") for p in new_posts])
                seen_posts = seen_posts[-50:]
                state[key] = {"seen_posts": seen_posts, "last_check": datetime.now().isoformat()}
                save_state(state)

                for post in new_posts:
                    title = post.get("desc", "")[:50] or "新作品"
                    create_time = post.get("create_time")
                    if create_time:
                        create_time = datetime.fromtimestamp(create_time).strftime("%H:%M")
                    msg = f"🎵 {name} 发布了新作品: {title}"
                    if create_time:
                        msg += f" ({create_time})"
                    notifications.append(msg)
                    add_history(msg, "new_post")

    except Exception:
        pass

    return notifications


def check_all_posts() -> List[str]:
    rooms = load_rooms()
    all_notifications = []

    for room in rooms:
        if room.get("platform") == "douyin":
            notifications = check_douyin_posts(room["id"], room["name"])
            all_notifications.extend(notifications)

    return all_notifications


if __name__ == "__main__":
    notifications = check_all_posts()
    for msg in notifications:
        print(msg)
