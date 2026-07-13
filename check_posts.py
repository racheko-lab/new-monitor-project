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

try:
    from push_utils import push_notifications
    PUSH_AVAILABLE = True
except ImportError:
    PUSH_AVAILABLE = False

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


def get_avatar_from_html(html: str) -> Optional[str]:
    """从抖音直播页 HTML 中提取头像 URL（__pace_f RSC 格式）。"""
    pace_blocks = re.findall(r'self\.__pace_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    for block in pace_blocks:
        try:
            unescaped = block.encode().decode('unicode_escape')
        except Exception:
            unescaped = block
        m = re.search(r'"avatar_thumb":\{[^}]*"url_list":\["([^"]+)"', unescaped)
        if m:
            return m.group(1)
    return None


def fetch_sec_uid_from_live(room_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """从 live.douyin.com/{room_id} 提取 sec_uid、昵称、头像（用 requests 即可）。"""
    try:
        headers = {**HEADERS, "Referer": "https://live.douyin.com/"}
        resp = requests.get(f"https://live.douyin.com/{room_id}", headers=headers, timeout=15)
        return (get_sec_uid_from_html(resp.text),
                get_nickname_from_html(resp.text),
                get_avatar_from_html(resp.text))
    except Exception:
        return None, None, None


def parse_aweme(post: Dict, room_name: str) -> Optional[Dict]:
    """将抖音 API 返回的 aweme 对象转换为前端可用的 post 结构。

    兼容 PC 端和移动端两种 API 响应：
    - PC 端（douyin.com/aweme/v1/web/aweme/post）：有 create_time、statistics.play_count
    - 移动端（m.douyin.com/web/api/v2/aweme/post）：无 create_time，statistics 只有 digg_count
      用 aweme_id 作为排序键（抖音 aweme_id 是 snowflake ID，时间递增）
    """
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
        # 作者头像（用于前端卡片展示，多字段兼容）
        author = post.get("author", {}) or {}
        avatar_obj = (author.get("avatar_thumb") or author.get("avatar_medium")
                      or author.get("avatar_larger") or author.get("avatar_168x168")
                      or author.get("avatar_300x300") or {})
        avatar_urls = avatar_obj.get("url_list") or []
        author_avatar = avatar_urls[0] if avatar_urls else None
        post_url = f"https://www.douyin.com/video/{aweme_id}"
        # 移动端 API 无 create_time，用 aweme_id 数值大小近似排序（snowflake ID 时间递增）
        sort_key = int(create_time) if create_time else int(aweme_id)
        return {
            "id": str(aweme_id),
            "platform": "douyin",
            "name": room_name,
            "title": desc[:100],
            "views": int(views),
            "likes": int(likes),
            "cover": cover,
            "avatar": author_avatar,
            "url": post_url,
            "time": time_str or datetime.now().isoformat(),
            "sort_key": sort_key,
        }
    except Exception:
        return None


def fetch_posts_with_playwright(sec_uid: str, display_name: str) -> Tuple[Optional[List[Dict]], str]:
    """使用 Playwright headless Chrome 抓取用户主页作品列表。

    策略（response 拦截 + page.evaluate fetch）：
    1. m.douyin.com/share/user/{sec_uid}（移动端分享页，拦截初始 API 响应）
    2. 在页面上下文里调用 fetch API 获取完整作品列表（包括视频）
    3. www.iesdouyin.com/share/user/{sec_uid}（旧版分享页，补充）
    严格过滤作者 sec_uid，确保不会抓取到其他用户的作品。
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None, "error"

    captured_awemes = []
    seen_raw_ids = set()
    max_posts = 50
    last_cursor = [0]  # 可变容器，保存最近一次 API 返回的 max_cursor

    def make_on_response(tag: str):
        logged_url = [False]  # 只记录第一次API URL
        def on_response(resp):
            url = resp.url
            if 'aweme/post' in url and 'iteminfo' not in url and 'publish' not in url:
                if not logged_url[0]:
                    logged_url[0] = True
                    # 只打印URL的查询参数部分
                    try:
                        from urllib.parse import urlparse, parse_qs
                        qs = parse_qs(urlparse(url).query)
                        print(f"  [{tag}] API URL params: {qs}")
                    except Exception:
                        print(f"  [{tag}] API URL: {url[:200]}")
                try:
                    data = resp.json()
                    aweme_list = data.get("aweme_list") or data.get("awemes") or []
                    has_more = data.get("has_more", False)
                    cursor = data.get("max_cursor", 0)
                    if cursor:
                        last_cursor[0] = cursor
                    if aweme_list and isinstance(aweme_list[0], dict) and "aweme_id" in aweme_list[0]:
                        new_count = 0
                        for a in aweme_list:
                            aid = str(a.get("aweme_id", ""))
                            if aid and aid not in seen_raw_ids and len(captured_awemes) < max_posts:
                                captured_awemes.append(a)
                                seen_raw_ids.add(aid)
                                new_count += 1
                        if new_count:
                            for a in aweme_list[:3]:
                                atype = a.get("aweme_type", "?")
                                aid = a.get("aweme_id", "?")
                                desc = (a.get("desc") or "")[:25]
                                print(f"    [{tag}] type={atype} id={aid} desc={desc}")
                            print(f"  [{tag}] +{new_count} (累计 {len(captured_awemes)}), has_more={has_more}, cursor={cursor}")
                except Exception:
                    pass
        return on_response

    mobile_ua = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')

    def fetch_from_share_page(browser, host: str, tag: str):
        """从移动端分享页抓取作品，通过 response 拦截 + page.evaluate fetch 获取作品。

        访问分享页后，在页面上下文里调用 fetch API 获取完整作品列表（包括视频）。
        严格 sec_uid 过滤防串号。
        """
        ctx = None
        try:
            before = len(captured_awemes)
            print(f"  [{tag}] 访问 {host}/share/user/...")
            ctx = browser.new_context(
                user_agent=mobile_ua,
                viewport={'width': 390, 'height': 844},
                locale='zh-CN', timezone_id='Asia/Shanghai',
                is_mobile=True, has_touch=True,
            )
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = ctx.new_page()
            page.on('response', make_on_response(tag))
            page.goto(f'https://{host}/share/user/{sec_uid}',
                       wait_until='domcontentloaded', timeout=45000)
            # 等待初始 API 响应
            for _ in range(15):
                if len(captured_awemes) > before:
                    break
                page.wait_for_timeout(1000)

            # 滚动加载更多
            prev = len(captured_awemes)
            for _ in range(5):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(2000)
                if len(captured_awemes) == prev:
                    break
                prev = len(captured_awemes)

            # 用 page.evaluate 在页面上下文里调用 fetch API，获取完整作品列表（包括视频）
            if host == 'm.douyin.com':
                try:
                    print(f"  [{tag}] 尝试用 page.evaluate 调用 fetch API...")
                    fetch_result = page.evaluate("""async (secUid) => {
                        try {
                            const url = `/web/api/v2/aweme/post/?sec_uid=${secUid}&count=50&max_cursor=0`;
                            const resp = await fetch(url, {credentials: 'include'});
                            const text = await resp.text();
                            let data;
                            try { data = JSON.parse(text); }
                            catch(e) {
                                return {error: 'JSON fail', status: resp.status,
                                        textLen: text.length, textStart: text.substring(0, 200)};
                            }
                            const list = data.aweme_list || [];
                            return {
                                status: resp.status,
                                count: list.length,
                                has_more: data.has_more,
                                aweme_list: list,
                            };
                        } catch(e) {
                            return {error: e.message};
                        }
                    }""", sec_uid)

                    if fetch_result and isinstance(fetch_result, dict):
                        if 'error' in fetch_result:
                            print(f"  [{tag}] fetch API 错误: {fetch_result}")
                        elif 'aweme_list' in fetch_result:
                            new_list = fetch_result['aweme_list']
                            print(f"  [{tag}] fetch API 获取 {len(new_list)} 条, has_more={fetch_result.get('has_more')}")
                            for a in new_list[:5]:
                                atype = a.get("aweme_type", "?")
                                aid = a.get("aweme_id", "?")
                                desc = (a.get("desc") or "")[:25]
                                print(f"    [{tag}-fetch] type={atype} id={aid} desc={desc}")
                            # 添加到 captured_awemes
                            added = 0
                            for a in new_list:
                                aid = str(a.get("aweme_id", ""))
                                if aid and aid not in seen_raw_ids and len(captured_awemes) < max_posts:
                                    captured_awemes.append(a)
                                    seen_raw_ids.add(aid)
                                    added += 1
                            if added:
                                print(f"  [{tag}] fetch 新增 {added} 条 (累计 {len(captured_awemes)})")
                        else:
                            print(f"  [{tag}] fetch API 结果: {fetch_result}")
                    else:
                        print(f"  [{tag}] fetch API 返回空: {fetch_result}")
                except Exception as e:
                    print(f"  [{tag}] page.evaluate 异常: {e}")

            print(f"  [{tag}] 完成，新增 {len(captured_awemes) - before} 条")
        except Exception as e:
            print(f"  [{tag}] 异常: {e}")
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )

        # 来源1: m.douyin.com 分享页（移动端，尝试点击视频标签获取视频）
        fetch_from_share_page(browser, 'm.douyin.com', 'm')

        # 来源2: iesdouyin.com 分享页（补充）
        fetch_from_share_page(browser, 'www.iesdouyin.com', 'ies')

        browser.close()

    if not captured_awemes:
        return [], "no_data"

    # 过滤：只保留作者 sec_uid 匹配的作品（防止串号/推荐内容混入）
    filtered_awemes = []
    for a in captured_awemes:
        author = a.get("author", {}) or {}
        author_sec = author.get("sec_uid") or ""
        if not author_sec or author_sec == sec_uid:
            filtered_awemes.append(a)
        else:
            print(f"  [过滤] 丢弃非目标用户作品: id={a.get('aweme_id')} author_sec={author_sec[:20]}...")

    if not filtered_awemes:
        print("  [警告] 过滤后无作品（全部为非目标用户）")
        return [], "no_data"

    # 解析作品，去重
    parsed_posts = []
    seen_ids = set()
    for a in filtered_awemes:
        parsed = parse_aweme(a, display_name)
        if parsed and parsed["id"] not in seen_ids:
            parsed_posts.append(parsed)
            seen_ids.add(parsed["id"])

    # 按 sort_key 倒序（create_time 或 aweme_id 数值）
    parsed_posts.sort(key=lambda x: x.get("sort_key", 0), reverse=True)
    return parsed_posts, "ok"


def get_status_key(platform: str, room_id: str) -> str:
    return f"{platform}_{room_id}"


def check_douyin_posts(room_id: str, name: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[Dict], List[Dict], List[str]]:
    """检测一个抖音账号，返回 (sec_uid, display_name, avatar, latest_post, new_posts, notifications)。

    流程：
    1. 用 requests 从 live.douyin.com 拿 sec_uid、昵称、头像
    2. 用 Playwright 访问 iesdouyin.com + m.douyin.com 分享页拦截作品 API
    3. 解析作品，过滤非目标用户作品，对比 state 中的 seen_posts 找出新作品
    """
    notifications = []
    new_posts_data = []
    latest_post = None
    sec_uid = None
    display_name = name
    avatar = None

    # Step 1: 获取 sec_uid、昵称、头像
    sec_uid, nickname, live_avatar = fetch_sec_uid_from_live(room_id)
    if not sec_uid:
        return None, display_name, None, None, [], []
    display_name = nickname or name
    avatar = live_avatar

    # Step 2: 用 Playwright 抓取作品
    parsed_posts, status = fetch_posts_with_playwright(sec_uid, display_name)

    if not parsed_posts:
        return sec_uid, display_name, avatar, None, [], []

    # 最新作品 = 按时间倒序第一个
    latest_post = parsed_posts[0]
    # 若作品 API 没带头像，用直播页头像兜底
    if not latest_post.get("avatar") and avatar:
        latest_post["avatar"] = avatar

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

    return sec_uid, display_name, avatar, latest_post, new_posts_data, notifications


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
        sec_uid, display_name, avatar, latest_post, new_posts, notifications = check_douyin_posts(room_id, name)

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
            "avatar": avatar,
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

    # 新作品合并到 posts.json（历史归档），按 sort_key 倒序
    if all_new_posts:
        existing = load_posts()
        existing_ids = {p.get("id") for p in existing if p.get("id")}
        for p in all_new_posts:
            if p.get("id") not in existing_ids:
                existing.append(p)
        existing.sort(key=lambda x: x.get("sort_key", 0), reverse=True)
        save_posts(existing[:POSTS_MAX])

    return all_notifications, all_new_posts


if __name__ == "__main__":
    if not PLAYWRIGHT_AVAILABLE:
        print("⚠️ playwright 未安装，作品抓取将失败")
    notifications, new_posts = check_all_posts()
    for msg in notifications:
        print(msg)
    print(f"检测完成，新作品 {len(new_posts)} 条")
    # 通过 Bark 等渠道推送新作品通知
    if notifications and PUSH_AVAILABLE:
        try:
            push_notifications(notifications, title="新作品监控")
            print(f"已推送 {len(notifications)} 条通知")
        except Exception as e:
            print(f"推送通知失败（不影响数据更新）: {e}")
