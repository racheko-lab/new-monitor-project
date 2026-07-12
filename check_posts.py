#!/usr/bin/env python3
"""新作品监控：独立账号列表，检测每个账号最新作品并输出 posts_status.json 供前端展示。

与直播监控完全独立：
- 读取 posts_rooms.json（而非 rooms.json）
- 输出 posts_status.json：每个账号的最新作品信息
- 新作品写入 history.json 触发通知
"""
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

POSTS_ROOMS_FILE = "posts_rooms.json"
POSTS_STATUS_FILE = "posts_status.json"
STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
POSTS_FILE = "posts.json"
HISTORY_MAX = 200
POSTS_MAX = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def load_posts_rooms() -> List[Dict]:
    if not os.path.exists(POSTS_ROOMS_FILE):
        return []
    try:
        with open(POSTS_ROOMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_posts_rooms(rooms: List[Dict]):
    with open(POSTS_ROOMS_FILE, "w", encoding="utf-8") as f:
        json.dump(rooms, f, ensure_ascii=False, indent=2)


def load_posts_status() -> Dict:
    if not os.path.exists(POSTS_STATUS_FILE):
        return {}
    try:
        with open(POSTS_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_posts_status(status: Dict):
    with open(POSTS_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def load_state() -> Dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_history() -> List[Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history: List[Dict]):
    history = history[-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_posts() -> List[Dict]:
    if os.path.exists(POSTS_FILE):
        try:
            with open(POSTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_posts(posts: List[Dict]):
    posts = posts[-POSTS_MAX:]
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def add_history(message: str, event_type: str = "post"):
    history = load_history()
    history.append({
        "time": datetime.now().isoformat(),
        "type": event_type,
        "message": message
    })
    save_history(history)


def get_sec_uid_from_html(html: str) -> Optional[str]:
    """从抖音直播页 HTML 中提取 sec_uid（兼容新版 __pace_f RSC 格式）。"""
    pace_blocks = re.findall(r'self\.__pace_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    for block in pace_blocks:
        try:
            unescaped = block.encode().decode('unicode_escape')
        except Exception:
            unescaped = block
        m = re.search(r'"sec_uid":"([^"]+)"', unescaped)
        if m and m.group(1) != "$undefined":
            return m.group(1)
    m = re.search(r'"sec_uid":"([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'sec_uid=([^&"]+)', html)
    if m:
        return m.group(1)
    return None


def get_nickname_from_html(html: str) -> Optional[str]:
    """从抖音直播页 HTML 中提取昵称（latin1 → utf-8 修复）。"""
    pace_blocks = re.findall(r'self\.__pace_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    for block in pace_blocks:
        try:
            unescaped = block.encode().decode('unicode_escape')
        except Exception:
            unescaped = block
        m = re.search(r'"nickname":"([^"]+)"', unescaped)
        if m and m.group(1) not in ("$undefined", "广告投放"):
            try:
                return m.group(1).encode('latin1').decode('utf-8')
            except Exception:
                return m.group(1)
    return None


def fetch_douyin_page(room_id: str) -> Tuple[str, Optional[str], Optional[str]]:
    """获取抖音直播页 HTML，返回 (html, sec_uid, nickname)。"""
    headers = {**HEADERS, "Referer": "https://live.douyin.com/"}
    resp = requests.get(f"https://live.douyin.com/{room_id}", headers=headers, timeout=15)
    html = resp.text
    sec_uid = get_sec_uid_from_html(html)
    nickname = get_nickname_from_html(html)
    return html, sec_uid, nickname


def fetch_posts_web_api(sec_uid: str) -> Optional[List[Dict]]:
    """抖音 Web API（需要签名，多数情况返回空）。"""
    try:
        s = requests.Session()
        s.get("https://live.douyin.com/", headers=HEADERS, timeout=10)
        api_url = (
            f"https://www.douyin.com/aweme/v1/web/aweme/post/"
            f"?sec_uid={sec_uid}&count=20&max_cursor=0"
            f"&aid=6383&device_platform=web&channel=channel_pc_web&version_code=170400"
        )
        resp = s.get(api_url, headers={
            **HEADERS,
            "Referer": f"https://www.douyin.com/user/{sec_uid}",
        }, timeout=15)
        if resp.status_code == 200 and resp.text.strip():
            data = resp.json()
            if data.get("status_code") == 0:
                return data.get("aweme_list", []) or []
    except Exception:
        pass
    return None


def fetch_posts_app_api(sec_uid: str) -> Optional[List[Dict]]:
    """抖音 App API（较宽松，但部分账号返回空）。"""
    try:
        url = (
            f"https://api.amemv.com/aweme/v1/aweme/post/"
            f"?sec_user_id={sec_uid}&count=20&max_cursor=0&aid=1128"
        )
        headers = {
            "User-Agent": "com.ss.android.ugc.aweme/110801 (Linux; U; Android 8.1.0; "
                          "en_US; Build/OPM1.171019.026; Cronet/TTNetVersion:b3020049ac)",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and resp.text.strip():
            data = resp.json()
            if data.get("status_code") == 0:
                return data.get("aweme_list", []) or []
    except Exception:
        pass
    return None


def parse_aweme(post: Dict, room_name: str) -> Optional[Dict]:
    """将抖音 API 返回的 aweme 对象转换为前端可用的 post 结构。"""
    try:
        aweme_id = post.get("aweme_id")
        if not aweme_id:
            return None
        desc = post.get("desc", "") or "无标题"
        create_time = post.get("create_time")
        time_str = None
        if create_time:
            try:
                time_str = datetime.fromtimestamp(int(create_time)).isoformat()
            except Exception:
                time_str = None
        stats = post.get("statistics", {}) or {}
        views = stats.get("play_count") or 0
        likes = stats.get("digg_count") or 0
        cover = None
        video = post.get("video", {}) or {}
        cover_obj = video.get("cover") or video.get("origin_cover") or {}
        url_list = cover_obj.get("url_list") or []
        if url_list:
            cover = url_list[0]
        post_url = f"https://www.douyin.com/video/{aweme_id}"
        return {
            "id": str(aweme_id),
            "platform": "douyin",
            "name": room_name,
            "title": desc[:100],
            "views": int(views),
            "likes": int(likes),
            "cover": cover,
            "url": post_url,
            "time": time_str or datetime.now().isoformat(),
        }
    except Exception:
        return None


def get_status_key(platform: str, room_id: str) -> str:
    return f"{platform}_{room_id}"


def check_douyin_posts(room_id: str, name: str) -> Tuple[Optional[str], Optional[str], Optional[Dict], List[Dict], List[str]]:
    """检测一个抖音账号，返回 (sec_uid, display_name, latest_post, new_posts, notifications)。

    latest_post: 最新作品（可能为 None）
    new_posts: 本次检测到的新作品（不在 seen 列表里的）
    notifications: 新作品通知消息列表
    """
    notifications = []
    new_posts_data = []
    latest_post = None
    sec_uid = None
    display_name = name

    try:
        html, sec_uid, nickname = fetch_douyin_page(room_id)
        if not sec_uid:
            return None, display_name, None, [], []
        display_name = nickname or name

        aweme_list = fetch_posts_web_api(sec_uid)
        if aweme_list is None:
            aweme_list = fetch_posts_app_api(sec_uid)
        if not aweme_list:
            return sec_uid, display_name, None, [], []

        # 解析所有作品
        parsed_posts = []
        for post in aweme_list:
            parsed = parse_aweme(post, display_name)
            if parsed:
                parsed_posts.append(parsed)

        if not parsed_posts:
            return sec_uid, display_name, None, [], []

        # 最新作品 = 按时间倒序第一个
        parsed_posts.sort(key=lambda x: x.get("time", ""), reverse=True)
        latest_post = parsed_posts[0]

        # 新作品检测
        state = load_state()
        key = f"douyin_posts_{room_id}"
        seen_posts = state.get(key, {}).get("seen_posts", [])

        for p in parsed_posts:
            if p.get("id") and p["id"] not in seen_posts:
                new_posts_data.append(p)
                seen_posts.append(p["id"])
                title = p.get("title", "")[:50] or "新作品"
                time_str = ""
                try:
                    t = datetime.fromisoformat(p["time"])
                    time_str = t.strftime("%H:%M")
                except Exception:
                    pass
                msg = f"🎵 {display_name} 发布了新作品: {title}"
                if time_str:
                    msg += f" ({time_str})"
                notifications.append(msg)
                add_history(msg, "new_post")

        if new_posts_data:
            seen_posts = seen_posts[-50:]
            state[key] = {
                "seen_posts": seen_posts,
                "last_check": datetime.now().isoformat(),
            }
            save_state(state)
    except Exception as e:
        print(f"抖音作品检测异常 {room_id}: {e}")

    return sec_uid, display_name, latest_post, new_posts_data, notifications


def check_all_posts() -> Tuple[List[str], List[Dict]]:
    """检测所有新作品监控账号，返回 (通知消息列表, 新作品列表)。"""
    rooms = load_posts_rooms()
    posts_status = load_posts_status()
    all_notifications = []
    all_new_posts = []
    now = datetime.now().isoformat()

    for room in rooms:
        platform = room.get("platform", "douyin")
        room_id = room.get("id", "")
        name = room.get("name", room_id)
        key = get_status_key(platform, room_id)

        if platform != "douyin":
            continue

        sec_uid, display_name, latest_post, new_posts, notifications = check_douyin_posts(room_id, name)

        # 自动补全昵称
        if display_name and display_name != name:
            room["name"] = display_name

        posts_status[key] = {
            "platform": platform,
            "id": room_id,
            "name": display_name or name,
            "sec_uid": sec_uid,
            "latest_post": latest_post,
            "total_seen": load_state().get(f"douyin_posts_{room_id}", {}).get("seen_posts", []).__len__(),
            "new_count": len(new_posts),
            "last_check": now,
            "status": "ok" if latest_post else ("no_data" if sec_uid else "error"),
        }

        all_notifications.extend(notifications)
        all_new_posts.extend(new_posts)

    # 清理已删除账号的残留记录
    valid_keys = {get_status_key(r["platform"], r["id"]) for r in rooms}
    for k in list(posts_status.keys()):
        if k not in valid_keys:
            del posts_status[k]

    save_posts_status(posts_status)
    save_posts_rooms(rooms)

    # 新作品合并到 posts.json（历史归档）
    if all_new_posts:
        existing = load_posts()
        existing_ids = {p.get("id") for p in existing if p.get("id")}
        for p in all_new_posts:
            if p.get("id") not in existing_ids:
                existing.append(p)
        existing.sort(key=lambda x: x.get("time", ""), reverse=True)
        save_posts(existing[:POSTS_MAX])

    return all_notifications, all_new_posts


if __name__ == "__main__":
    notifications, new_posts = check_all_posts()
    for msg in notifications:
        print(msg)
    print(f"检测完成，新作品 {len(new_posts)} 条")
