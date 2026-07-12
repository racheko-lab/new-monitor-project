#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

STATUS_FILE = "status.json"
STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
ROOMS_FILE = "rooms.json"
HISTORY_MAX = 200

BILIBILI_API = "https://api.live.bilibili.com/room/v1/Room/room_init?id={}"
DOUYIN_URL = "https://live.douyin.com/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://live.bilibili.com/",
    "Origin": "https://live.bilibili.com",
}


def load_rooms() -> List[Dict]:
    with open(ROOMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_status() -> Dict:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


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


def save_status(status: Dict):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def save_rooms(rooms: List[Dict]):
    with open(ROOMS_FILE, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=2)


def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def save_history(history: List[Dict]):
    history = history[-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_history(message: str, event_type: str = "status"):
    history = load_history()
    history.append({
        "time": datetime.now().isoformat(),
        "type": event_type,
        "message": message
    })
    save_history(history)


def check_bilibili(room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str]]:
    try:
        resp = requests.get(BILIBILI_API.format(room_id), headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            info = data.get("data", {})
            status = "live" if info.get("live_status") == 1 else "offline"
            title = info.get("title")
            viewers = info.get("online")
            uid = info.get("uid")
            uname = None
            if uid:
                try:
                    u_resp = requests.get(
                        f"https://api.live.bilibili.com/live_user/v1/Master/info?uid={uid}",
                        headers=HEADERS, timeout=10)
                    u_data = u_resp.json()
                    if u_data.get("code") == 0:
                        uname = u_data.get("data", {}).get("info", {}).get("uname")
                except Exception:
                    pass
            return status, title, viewers, uname
        return "error", None, None, None
    except Exception:
        return "error", None, None, None


def check_douyin(room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str]]:
    try:
        headers = {**HEADERS, "Referer": "https://live.douyin.com/"}
        resp = requests.get(DOUYIN_URL.format(room_id), headers=headers, timeout=10)
        html = resp.text
        match = re.search(r'window.__INITIAL_STATE__=(.*?);', html)
        if match:
            data = json.loads(match.group(1))
            room_info = data.get("room", {}).get("roomInfo", {})
            status = "live" if room_info.get("roomStatus") == 2 else "offline"
            title = room_info.get("title")
            viewers = room_info.get("userCount")
            uname = room_info.get("owner", {}).get("nickname")
            return status, title, viewers, uname
        return "error", None, None, None
    except Exception:
        return "error", None, None, None


def get_status(platform: str, room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str]]:
    if platform == "bilibili":
        return check_bilibili(room_id)
    elif platform == "douyin":
        return check_douyin(room_id)
    return "error", None, None, None


def get_status_key(platform: str, room_id: str) -> str:
    return f"{platform}_{room_id}"


def update_duration(state: Dict, platform: str, room_id: str, is_live: bool) -> Dict:
    key = get_status_key(platform, room_id)
    now = datetime.now().isoformat()

    if key not in state:
        state[key] = {"last_live_start": None, "duration": 0, "last_live_time": None}

    if is_live:
        if not state[key]["last_live_start"]:
            state[key]["last_live_start"] = now
        state[key]["last_live_time"] = now
    else:
        if state[key]["last_live_start"]:
            start = datetime.fromisoformat(state[key]["last_live_start"])
            end = datetime.fromisoformat(state[key]["last_live_time"] or now)
            duration = int((end - start).total_seconds())
            state[key]["duration"] += duration
            state[key]["last_live_start"] = None

    return state


def check_all() -> Tuple[List[Dict], List[str]]:
    rooms = load_rooms()
    current_status = load_status()
    state = load_state()
    notifications = []
    rooms_updated = False

    for room in rooms:
        platform = room["platform"]
        room_id = room["id"]
        name = room["name"]
        key = get_status_key(platform, room_id)

        status, title, viewers, uname = get_status(platform, room_id)
        is_live = status == "live"

        # 自动获取真实昵称：若 rooms.json 里 name 还是房间号/ID，则用获取到的 uname 替换
        if uname and (name == room_id or not name):
            room["name"] = uname
            name = uname
            rooms_updated = True

        state = update_duration(state, platform, room_id, is_live)

        previous_status = current_status.get(key, {}).get("status")
        if previous_status != status:
            if status == "live":
                msg = f"🎉 {name} 开播了！"
                if title:
                    msg += f" 标题: {title}"
                if viewers:
                    msg += f" 观看人数: {viewers}"
                notifications.append(msg)
                add_history(msg, "live_start")
            elif status == "offline":
                duration = state[key].get("duration", 0)
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                msg = f"🏁 {name} 下播了"
                if hours > 0 or minutes > 0:
                    msg += f"，本次直播时长: {hours}小时{minutes}分钟"
                notifications.append(msg)
                add_history(msg, "live_end")
            elif status == "error":
                msg = f"⚠️ {name} 检测失败"
                add_history(msg, "error")

        current_status[key] = {
            "platform": platform,
            "id": room_id,
            "name": name,
            "uname": uname or name,
            "status": status,
            "title": title,
            "viewers": viewers,
            "last_check": datetime.now().isoformat(),
            "duration": state[key].get("duration", 0)
        }

    save_status(current_status)
    save_state(state)
    if rooms_updated:
        save_rooms(rooms)

    return current_status, notifications


def cleanup_status() -> bool:
    """清理 status.json 中不在 rooms.json 里的残留记录（已删除的主播）。
    返回是否有改动。"""
    rooms = load_rooms()
    status = load_status()
    valid_keys = {get_status_key(r["platform"], r["id"]) for r in rooms}
    dirty = False
    for key in list(status.keys()):
        if key not in valid_keys:
            del status[key]
            dirty = True
    if dirty:
        save_status(status)
    return dirty


if __name__ == "__main__":
    status, notifications = check_all()
    cleanup_status()
    for msg in notifications:
        print(msg)
