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

BILIBILI_API = "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo"
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


def check_bilibili(room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str], Optional[str]]:
    """检测B站直播状态。

    使用 getRoomBaseInfo 接口：无论开播/下播都返回 title、uname、online 等字段，
    无需像 room_init 方案那样下播时再抓 HTML 兜底。
    """
    try:
        resp = requests.get(
            BILIBILI_API,
            params={"req_biz": "web_room_componet", "room_ids": room_id},
            headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            info = data.get("data", {}).get("by_room_ids", {}).get(str(room_id), {})
            if not info:
                return "error", None, None, None, None
            # live_status: 0=offline 1=live 2=replay
            status_code = info.get("live_status", 0)
            status = "live" if status_code == 1 else "offline"
            title = info.get("title")
            viewers = info.get("online")
            uid = info.get("uid")
            uname = info.get("uname")
            avatar = None

            # getRoomBaseInfo 不返回头像，从 Master/info 接口取（用 uid）
            if uid:
                try:
                    u_resp = requests.get(
                        f"https://api.live.bilibili.com/live_user/v1/Master/info?uid={uid}",
                        headers=HEADERS, timeout=10)
                    u_data = u_resp.json()
                    if u_data.get("code") == 0:
                        uinfo = u_data.get("data", {}).get("info", {})
                        uname = uinfo.get("uname") or uname
                        avatar = uinfo.get("face")
                except Exception:
                    pass
            return status, title, viewers, uname, avatar
        return "error", None, None, None, None
    except Exception:
        return "error", None, None, None, None


def check_douyin(room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str], Optional[str]]:
    """检测抖音直播状态。

    抖音新版页面使用 RSC（__pace_f）格式存储数据。
    判断逻辑（优先级从高到低）：
    1. web_stream_url 不是 null → 直播中（普通直播，有拉流地址）
    2. HTML 含"该直播类型或玩法电脑端暂未支持" → 直播中（特殊类型：电脑横屏/手游等，PC端不支持但确实在直播）
    3. 有 roomId 或 nickname → 未直播
    4. 都没有 → 房间无效
    """
    try:
        headers = {**HEADERS, "Referer": "https://live.douyin.com/"}
        resp = requests.get(DOUYIN_URL.format(room_id), headers=headers, timeout=15)
        html = resp.text

        # 兼容旧版 __INITIAL_STATE__（已弃用，保留兜底）
        match = re.search(r'window.__INITIAL_STATE__=(.*?);', html)
        if match:
            try:
                data = json.loads(match.group(1))
                room_info = data.get("room", {}).get("roomInfo", {})
                status = "live" if room_info.get("roomStatus") == 2 else "offline"
                title = room_info.get("title")
                viewers = room_info.get("userCount")
                uname = room_info.get("owner", {}).get("nickname")
                avatar = room_info.get("owner", {}).get("avatar_thumb", {}).get("url_list", [None])[0]
                return status, title, viewers, uname, avatar
            except Exception:
                pass

        # 新版：解析 __pace_f 数据块
        pace_blocks = re.findall(r'self\.__pace_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
        target_rid_marker = f'"web_rid":"{room_id}"'
        room_block = None
        for block in pace_blocks:
            try:
                unescaped = block.encode().decode('unicode_escape')
            except Exception:
                unescaped = block
            if target_rid_marker in unescaped and '"广告投放"' not in unescaped.split(target_rid_marker)[0][-200:]:
                room_block = unescaped
                break

        if not room_block:
            for block in pace_blocks:
                try:
                    unescaped = block.encode().decode('unicode_escape')
                except Exception:
                    unescaped = block
                if target_rid_marker in unescaped:
                    room_block = unescaped
                    break

        if not room_block:
            return "error", None, None, None, None

        # 解析字段
        room_id_match = re.search(r'"roomId":"([^"]*)"', room_block)
        stream_match = re.search(r'"web_stream_url"\s*:\s*(null|"[^"]*"|\{)', room_block)
        nick_match = re.search(r'"nickname":"([^"]+)"', room_block)
        count_match = re.search(r'"user_count"\s*:\s*(\d+)', room_block)
        if not count_match:
            count_match = re.search(r'"watching_count"\s*:\s*(\d+)', room_block)
        avatar_match = re.search(r'"avatar_thumb":\{[^}]*"url_list":\["([^"]+)"', room_block)

        real_room_id = room_id_match.group(1) if room_id_match else ""
        stream_val = stream_match.group(1) if stream_match else "null"
        avatar = avatar_match.group(1) if avatar_match else None

        # 昵称（修复 latin1 → utf-8 编码）
        uname = None
        if nick_match and nick_match.group(1) != "$undefined":
            try:
                uname = nick_match.group(1).encode('latin1').decode('utf-8')
            except Exception:
                uname = nick_match.group(1)

        # 标题：在 roomInfo 上下文中精确匹配，避免误匹配分类标签(如"舞蹈")
        title = None
        room_title_match = re.search(r'"status_str":"\d*","title":"([^"]+)"', room_block)
        if not room_title_match:
            room_title_match = re.search(r'"roomInfo":\{[^}]*"title":"([^"]+)"', room_block)
        if room_title_match and room_title_match.group(1) not in ("广告投放", "$undefined"):
            try:
                title = room_title_match.group(1).encode('latin1').decode('utf-8')
            except Exception:
                title = room_title_match.group(1)

        viewers = int(count_match.group(1)) if count_match else None

        # 判断直播状态
        # 1. web_stream_url 非 null → 直播中（普通直播）
        if stream_val and stream_val != "null":
            status = "live"
        # 2. HTML 含"暂未支持" → 直播中（特殊类型：电脑横屏/手游等，PC端不支持但确实在直播）
        elif "该直播类型或玩法电脑端暂未支持" in html or "暂未支持" in html:
            status = "live"
            if not title:
                title = "电脑端不支持的直播类型"
        # 3. 有 roomId 或 nickname → 未直播
        elif real_room_id:
            status = "offline"
        elif uname:
            status = "offline"
        # 4. 都没有 → 房间无效
        else:
            return "error", None, None, None, None

        return status, title, viewers, uname, avatar
    except Exception as e:
        print(f"抖音检测异常 {room_id}: {e}")
        return "error", None, None, None, None


def get_status(platform: str, room_id: str) -> Tuple[str, Optional[str], Optional[int], Optional[str], Optional[str]]:
    if platform == "bilibili":
        return check_bilibili(room_id)
    elif platform == "douyin":
        return check_douyin(room_id)
    return "error", None, None, None, None


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

        status, title, viewers, uname, avatar = get_status(platform, room_id)
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

        # 下播且API未返回标题时，保留上次直播的标题
        if not title and status == "offline":
            title = current_status.get(key, {}).get("title")

        current_status[key] = {
            "platform": platform,
            "id": room_id,
            "name": name,
            "uname": uname or name,
            "avatar": avatar or current_status.get(key, {}).get("avatar"),
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
