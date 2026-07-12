#!/usr/bin/env python3
"""新作品监控：使用 Playwright headless browser 抓取抖音用户作品。

绕过抖音 Web API 的 a_bogus 签名要求，直接通过 headless Chrome 访问用户主页，
拦截 aweme/v1/web/aweme/post 接口响应获取作品列表。

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

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

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


def fetch_sec_uid_from_live(room_id: str) -> Tuple[Optional[str], Optional[str]]:
    """从 live.douyin.com/{room_id} 提取 sec_uid 和昵称（用 requests 即可）。"""
    try:
        headers = {**HEADERS, "Referer": "https://live.douyin.com/"}
        resp = requests.get(f"https://live.douyin.com/{room_id}", headers=headers, timeout=15)
        return get_sec_uid_from_html(resp.text), get_nickname_from_html(resp.text)
    except Exception:
        return None, None


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


def fetch_posts_with_playwright(sec_uid: str, display_name: str) -> Tuple[Optional[List[Dict]], str]:
    """使用 Playwright headless Chrome 抓取用户主页作品列表。

    返回 (parsed_posts, status)：parsed_posts 为解析后的作品列表（可能为空），
    status 为 'ok' / 'no_data' / 'error'。
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None, "error"

    captured_awemes = []
    max_posts = 30  # 最多捕获 30 条作品

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1512, 'height': 982},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'},
        )
        # 反检测：隐藏 webdriver 标志
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
            window.chrome = {runtime: {}};
        """)
        page = context.new_page()

        def on_response(resp):
            if 'aweme/v1/web/aweme/post' in resp.url and len(captured_awemes) < max_posts:
                try:
                    data = resp.json()
                    if data.get("status_code") == 0:
                        aweme_list = data.get("aweme_list", []) or []
                        for a in aweme_list:
                            if len(captured_awemes) < max_posts:
                                captured_awemes.append(a)
                except Exception:
                    pass

        page.on('response', on_response)

        try:
            # 先访问首页拿 cookie，降低被识别为爬虫的概率
            page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(2500)

            # 访问用户主页
            page.goto(f'https://www.douyin.com/user/{sec_uid}',
                      wait_until='domcontentloaded', timeout=45000)

            # 等待作品 API 触发（最多 12 秒）
            for _ in range(12):
                if captured_awemes:
                    break
                page.wait_for_timeout(1000)

            # 稍微滚动触发更多加载
            for _ in range(2):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(1200)
        except PlaywrightTimeoutError:
            pass
        except Exception as e:
            print(f"  Playwright 抓取异常: {e}")
        finally:
            browser.close()

    if not captured_awemes:
        return [], "no_data"

    # 解析作品，去重
    parsed_posts = []
    seen_ids = set()
    for a in captured_awemes:
        parsed = parse_aweme(a, display_name)
        if parsed and parsed["id"] not in seen_ids:
            parsed_posts.append(parsed)
            seen_ids.add(parsed["id"])

    # 按时间倒序
    parsed_posts.sort(key=lambda x: x.get("time", ""), reverse=True)
    return parsed_posts, "ok"


def get_status_key(platform: str, room_id: str) -> str:
    return f"{platform}_{room_id}"


def check_douyin_posts(room_id: str, name: str) -> Tuple[Optional[str], Optional[str], Optional[Dict], List[Dict], List[str]]:
    """检测一个抖音账号，返回 (sec_uid, display_name, latest_post, new_posts, notifications)。

    流程：
    1. 用 requests 从 live.douyin.com 拿 sec_uid 和昵称
    2. 用 Playwright 访问 douyin.com/user/{sec_uid} 拦截作品 API
    3. 解析作品，对比 state 中的 seen_posts 找出新作品
    """
    notifications = []
    new_posts_data = []
    latest_post = None
    sec_uid = None
    display_name = name

    # Step 1: 获取 sec_uid
    sec_uid, nickname = fetch_sec_uid_from_live(room_id)
    if not sec_uid:
        return None, display_name, None, [], []
    display_name = nickname or name

    # Step 2: 用 Playwright 抓取作品
    parsed_posts, status = fetch_posts_with_playwright(sec_uid, display_name)

    if not parsed_posts:
        return sec_uid, display_name, None, [], []

    # 最新作品 = 按时间倒序第一个
    latest_post = parsed_posts[0]

    # Step 3: 新作品检测
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

        print(f"检测账号: {room_id} ({name})")
        sec_uid, display_name, latest_post, new_posts, notifications = check_douyin_posts(room_id, name)

        # 自动补全昵称
        if display_name and display_name != name:
            room["name"] = display_name

        # 判断状态
        if latest_post:
            status_flag = "ok"
        elif sec_uid:
            status_flag = "no_data"
        else:
            status_flag = "error"

        seen_count = len(load_state().get(f"douyin_posts_{room_id}", {}).get("seen_posts", []))
        posts_status[key] = {
            "platform": platform,
            "id": room_id,
            "name": display_name or name,
            "sec_uid": sec_uid,
            "latest_post": latest_post,
            "total_seen": seen_count,
            "new_count": len(new_posts),
            "last_check": now,
            "status": status_flag,
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
    if not PLAYWRIGHT_AVAILABLE:
        print("⚠️ playwright 未安装，作品抓取将失败")
    notifications, new_posts = check_all_posts()
    for msg in notifications:
        print(msg)
    print(f"检测完成，新作品 {len(new_posts)} 条")
