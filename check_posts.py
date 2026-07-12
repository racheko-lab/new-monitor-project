#!/usr/bin/env python3
"""新作品监控：检测抖音主播的最新作品并生成 posts.json 供前端展示。"""
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

ROOMS_FILE = "rooms.json"
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


def load_posts() -> List[Dict]:
    if os.path.exists(POSTS_FILE):
        try:
            with open(POSTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def save_history(history: List[Dict]):
    history = history[-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


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
    """从抖音直播页 HTML 中提取 sec_uid。

    新版页面使用 RSC（__pace_f）格式，数据块经过 unicode_escape 编码，
    需要逐块解码后再匹配 sec_uid。旧版 __INITIAL_STATE__ 作为兜底。
    """
    # 新版：解析 __pace_f 数据块
    pace_blocks = re.findall(r'self\.__pace_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    for block in pace_blocks:
        try:
            unescaped = block.encode().decode('unicode_escape')
        except Exception:
            unescaped = block
        m = re.search(r'"sec_uid":"([^"]+)"', unescaped)
        if m and m.group(1) != "$undefined":
            return m.group(1)
    # 兜底：直接在 HTML 中查找
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
    """尝试抖音 Web API 获取作品列表（需要签名，多数情况会返回空）。"""
    try:
        s = requests.Session()
        s.get("https://live.douyin.com/", headers=HEADERS, timeout=10)
        api_url = (
            f"https://www.douyin.com/aweme/v1/web/aweme/post/"
            f"?sec_uid={sec_uid}&count=10&max_cursor=0"
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
    """尝试抖音 App API 获取作品列表（较宽松，但部分账号返回空）。"""
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
        # 统计数据
        stats = post.get("statistics", {}) or {}
        views = stats.get("play_count") or 0
        likes = stats.get("digg_count") or 0
        # 封面
        cover = None
        video = post.get("video", {}) or {}
        cover_obj = video.get("cover") or video.get("origin_cover") or {}
        url_list = cover_obj.get("url_list") or []
        if url_list:
            cover = url_list[0]
        # 视频链接
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


def check_douyin_posts(room_id: str, name: str) -> Tuple[List[str], List[Dict]]:
    """检测一个抖音主播的新作品，返回 (通知消息列表, 新作品列表)。"""
    notifications = []
    new_posts_data = []
    try:
        html, sec_uid, nickname = fetch_douyin_page(room_id)
        if not sec_uid:
            return notifications, new_posts_data

        display_name = nickname or name

        # 依次尝试 Web API 和 App API
        aweme_list = fetch_posts_web_api(sec_uid)
        if aweme_list is None:
            aweme_list = fetch_posts_app_api(sec_uid)
        if not aweme_list:
            return notifications, new_posts_data

        state = load_state()
        key = f"douyin_posts_{room_id}"
        seen_posts = state.get(key, {}).get("seen_posts", [])

        for post in aweme_list:
            aweme_id = str(post.get("aweme_id", ""))
            if not aweme_id or aweme_id in seen_posts:
                continue
            parsed = parse_aweme(post, display_name)
            if not parsed:
                continue
            new_posts_data.append(parsed)
            seen_posts.append(aweme_id)
            title = (post.get("desc", "") or "新作品")[:50]
            create_time = post.get("create_time")
            time_str = ""
            if create_time:
                try:
                    time_str = datetime.fromtimestamp(int(create_time)).strftime("%H:%M")
                except Exception:
                    pass
            msg = f"🎵 {display_name} 发布了新作品: {title}"
            if time_str:
                msg += f" ({time_str})"
            notifications.append(msg)
            add_history(msg, "new_post")

        # 更新已见记录
        if new_posts_data:
            seen_posts = seen_posts[-50:]
            state[key] = {
                "seen_posts": seen_posts,
                "last_check": datetime.now().isoformat(),
            }
            save_state(state)
    except Exception as e:
        print(f"抖音作品检测异常 {room_id}: {e}")

    return notifications, new_posts_data


def check_all_posts() -> Tuple[List[str], List[Dict]]:
    """检测所有主播的新作品，返回 (通知消息列表, 新作品列表)。"""
    rooms = load_rooms()
    all_notifications = []
    all_new_posts = []

    for room in rooms:
        if room.get("platform") == "douyin":
            notifications, new_posts = check_douyin_posts(room["id"], room.get("name", room["id"]))
            all_notifications.extend(notifications)
            all_new_posts.extend(new_posts)

    # 合并到 posts.json：新作品加到列表头部，按时间倒序，去重，限制数量
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
