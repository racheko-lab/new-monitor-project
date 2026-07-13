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

    def add_awemes(aweme_list, tag):
        """将aweme列表添加到captured_awemes，去重，打印日志。返回新增数量。"""
        if not aweme_list or not isinstance(aweme_list, list):
            return 0
        new_count = 0
        for a in aweme_list:
            if not isinstance(a, dict) or "aweme_id" not in a:
                continue
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
            print(f"  [{tag}] +{new_count} (累计 {len(captured_awemes)})")
        return new_count

    def make_on_response(tag: str):
        logged_urls = set()
        def on_response(resp):
            url = resp.url
            if 'iteminfo' in url or 'reply' in url or 'comment' in url or 'favorite' in url or 'like' in url or 'follow' in url or 'live' in url:
                return
            is_aweme = '/aweme/' in url or 'aweme/post' in url
            if not is_aweme:
                return
            url_key = url.split('?')[0]
            if url_key not in logged_urls and len(logged_urls) < 5:
                logged_urls.add(url_key)
                try:
                    from urllib.parse import urlparse, parse_qs
                    qs = parse_qs(urlparse(url).query)
                    aweme_type_param = qs.get('aweme_type', ['?'])
                    print(f"  [{tag}] API: {url[:200]}")
                    print(f"  [{tag}] API params: aweme_type={aweme_type_param}")
                except Exception:
                    print(f"  [{tag}] API URL: {url[:200]}")
            try:
                status = resp.status
                if status != 200:
                    return
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype.lower():
                    return
                data = resp.json()
                if not isinstance(data, dict):
                    return
                aweme_list = data.get("aweme_list") or data.get("awemes") or []
                has_more = data.get("has_more", False)
                cursor = data.get("max_cursor", 0)
                if cursor:
                    last_cursor[0] = cursor
                add_awemes(aweme_list, tag + '-resp')
            except Exception:
                pass
        return on_response

    mobile_ua = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')

    dom_seen_ids = set()

    def fetch_from_share_page(browser, host: str, tag: str, path_prefix: str = '/share/user/'):
        """从移动端分享页抓取作品，通过 response 拦截 + fetch/XHR hook 捕获 API 数据。

        严格 sec_uid 过滤防串号。支持 /share/user/ 和 /user/ 两种路径。
        """
        ctx = None
        try:
            before = len(captured_awemes)
            print(f"  [{tag}] 访问 {host}{path_prefix}...")
            ctx = browser.new_context(
                user_agent=mobile_ua,
                viewport={'width': 390, 'height': 844},
                locale='zh-CN', timezone_id='Asia/Shanghai',
                is_mobile=True, has_touch=True,
            )
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.__m_captured_awemes = [];
                window.__m_api_logs = [];

                function tryAddAwemes(data, url, source) {
                    try {
                        if (!data || typeof data !== 'object') return;
                        const list = data.aweme_list || data.awemes;
                        if (Array.isArray(list)) {
                            const valid = list.filter(x => x && x.aweme_id);
                            if (valid.length) {
                                window.__m_captured_awemes.push(...valid);
                                window.__m_api_logs.push({url: url, count: valid.length, source});
                            }
                        }
                        function deepSearch(obj, depth) {
                            if (!obj || depth > 8 || typeof obj !== 'object') return;
                            if (Array.isArray(obj)) {
                                if (obj.length > 0 && obj[0] && obj[0].aweme_id) {
                                    const valid = obj.filter(x => x && x.aweme_id);
                                    if (valid.length) {
                                        window.__m_captured_awemes.push(...valid);
                                        window.__m_api_logs.push({url: url, count: valid.length, source: source+'-deep'});
                                    }
                                    return;
                                }
                                for (const item of obj) deepSearch(item, depth+1);
                            } else {
                                if (obj.aweme_id) {
                                    window.__m_captured_awemes.push(obj);
                                    window.__m_api_logs.push({url: url, count: 1, source: source+'-single'});
                                }
                                for (const key of Object.keys(obj)) deepSearch(obj[key], depth+1);
                            }
                        }
                        deepSearch(data, 0);
                    } catch(e) {}
                }

                function shouldIntercept(url) {
                    if (url.includes('iteminfo')) return false;
                    if (url.includes('reply')) return false;
                    if (url.includes('comment')) return false;
                    if (url.includes('favorite')) return false;
                    if (url.includes('like')) return false;
                    if (url.includes('follow')) return false;
                    if (url.includes('live')) return false;
                    return url.includes('/aweme/') || url.includes('aweme/post');
                }

                const _origFetch = window.fetch;
                window.fetch = function() {
                    return _origFetch.apply(this, arguments).then(resp => {
                        const url = resp.url || '';
                        if (shouldIntercept(url)) {
                            const clone = resp.clone();
                            clone.json().then(d => tryAddAwemes(d, url, 'fetch')).catch(()=>{});
                        }
                        return resp;
                    });
                };

                const _origXHROpen = XMLHttpRequest.prototype.open;
                const _origXHRSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this.__url = url;
                    return _origXHROpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    if (this.__url && shouldIntercept(this.__url)) {
                        this.addEventListener('load', function() {
                            try { tryAddAwemes(JSON.parse(this.responseText), this.__url, 'xhr'); } catch(e){}
                        });
                    }
                    return _origXHRSend.apply(this, arguments);
                };
            """)
            page = ctx.new_page()
            page.on('response', make_on_response(tag))
            page.goto(f'https://{host}{path_prefix}{sec_uid}',
                       wait_until='domcontentloaded', timeout=45000)
            for _ in range(15):
                page.wait_for_timeout(1000)
                try:
                    mdata = page.evaluate("""() => {
                        const awemes = window.__m_captured_awemes || [];
                        const logs = window.__m_api_logs || [];
                        window.__m_captured_awemes = [];
                        window.__m_api_logs = [];
                        return {awemes, logs};
                    }""")
                    if mdata.get('awemes'):
                        for log_entry in mdata.get('logs', [])[:3]:
                            print(f"  [{tag}-api] {log_entry}")
                        add_awemes(mdata['awemes'], tag + '-hook')
                        break
                except Exception:
                    pass

            for scroll_i in range(8):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1500)
                try:
                    mdata = page.evaluate("""() => {
                        const awemes = window.__m_captured_awemes || [];
                        const logs = window.__m_api_logs || [];
                        window.__m_captured_awemes = [];
                        window.__m_api_logs = [];
                        return {awemes, logs};
                    }""")
                    if mdata.get('awemes'):
                        add_awemes(mdata['awemes'], f'{tag}-s{scroll_i+1}')
                except Exception:
                    pass
                try:
                    dom_ids_m = page.evaluate("""() => {
                        const links = document.querySelectorAll('a[href*="/video/"], a[href*="/note/"]');
                        const ids = new Set();
                        links.forEach(a => {
                            try {
                                const path = new URL(a.href).pathname;
                                const parts = path.split('/');
                                for (let i = 0; i < parts.length-1; i++) {
                                    if (parts[i]==='video'||parts[i]==='note') {
                                        const id = parts[i+1].split('?')[0].split('#')[0];
                                        if (/^\\d+$/.test(id)) ids.add(id);
                                    }
                                }
                            } catch(e){}
                        });
                        return Array.from(ids);
                    }""")
                    for did in dom_ids_m:
                        dom_seen_ids.add(did)
                except Exception:
                    pass

            page.wait_for_timeout(2000)

            # 从页面内嵌JSON提取awemes（ROUTER_DATA/RENDER_DATA）
            try:
                embed_data = page.evaluate("""() => {
                    const found = [];
                    const seen = new Set();
                    function deepFind(obj, depth) {
                        if (!obj || depth > 10 || typeof obj !== 'object' || found.length >= 20) return;
                        if (Array.isArray(obj)) {
                            if (obj.length > 0 && obj[0] && obj[0].aweme_id) {
                                for (const item of obj) {
                                    if (item && item.aweme_id && !seen.has(String(item.aweme_id))) {
                                        seen.add(String(item.aweme_id));
                                        found.push(item);
                                        if (found.length >= 20) return;
                                    }
                                }
                                return;
                            }
                            for (const item of obj) { deepFind(item, depth+1); if (found.length >= 20) return; }
                        } else {
                            if (obj.aweme_id && !seen.has(String(obj.aweme_id))) {
                                seen.add(String(obj.aweme_id));
                                found.push(obj);
                                if (found.length >= 20) return;
                            }
                            for (const key of Object.keys(obj)) { deepFind(obj[key], depth+1); if (found.length >= 20) return; }
                        }
                    }
                    for (const store of [window._ROUTER_DATA, window.__INITIAL_STATE__]) {
                        try { if (store) deepFind(store, 0); } catch(e) {}
                    }
                    try {
                        const rd = document.getElementById('RENDER_DATA');
                        if (rd) { deepFind(JSON.parse(decodeURIComponent(rd.textContent)), 0); }
                    } catch(e) {}
                    return found;
                }""")
                if embed_data:
                    cnt = add_awemes(embed_data, tag + '-embed')
                    if cnt:
                        print(f"  [{tag}] 从内嵌JSON提取 {cnt} 条")
            except Exception as e:
                print(f"  [{tag}] 内嵌JSON提取异常: {e}")

            # 尝试点击"作品"标签切换到全部作品视图（如果有图文/作品分类tab）
            try:
                tabs_info = page.evaluate("""() => {
                    const tabs = [];
                    const allElements = document.querySelectorAll('div, span, p, a');
                    for (const el of allElements) {
                        const text = (el.textContent || '').trim();
                        if ((text === '作品' || text === '视频' || text === '图文' || text === '全部') && el.offsetParent !== null) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.top < window.innerHeight) {
                                tabs.push({text, tag: el.tagName, x: rect.x + rect.width/2, y: rect.y + rect.height/2});
                            }
                        }
                    }
                    return tabs.slice(0, 10);
                }""")
                if tabs_info:
                    print(f"  [{tag}] 发现标签: {[(t['text'],int(t['y'])) for t in tabs_info]}")
                    # 点击"作品"标签
                    for t in tabs_info:
                        if t['text'] in ('作品', '视频', '全部'):
                            print(f"  [{tag}] 点击 '{t['text']}' 标签...")
                            page.mouse.click(t['x'], t['y'])
                            page.wait_for_timeout(3000)
                            # 收集点击后加载的新数据
                            for _ in range(5):
                                page.wait_for_timeout(1500)
                                try:
                                    mdata2 = page.evaluate("""() => {
                                        const awemes = window.__m_captured_awemes || [];
                                        const logs = window.__m_api_logs || [];
                                        window.__m_captured_awemes = [];
                                        window.__m_api_logs = [];
                                        return {awemes, logs};
                                    }""")
                                    if mdata2.get('awemes'):
                                        add_awemes(mdata2['awemes'], tag + '-tab')
                                    else:
                                        break
                                except Exception:
                                    break
                            # 再滚动几下加载更多
                            for _ in range(4):
                                page.mouse.wheel(0, 1500)
                                page.wait_for_timeout(1500)
                                try:
                                    mdata2 = page.evaluate("""() => {
                                        const awemes = window.__m_captured_awemes || [];
                                        window.__m_captured_awemes = [];
                                        return {awemes};
                                    }""")
                                    if mdata2.get('awemes'):
                                        add_awemes(mdata2['awemes'], tag + '-tabs')
                                except Exception:
                                    pass
                            break
            except Exception as e:
                print(f"  [{tag}] 标签点击异常: {e}")

            # 最终收集hook数据
            try:
                mdata = page.evaluate("""() => {
                    const awemes = window.__m_captured_awemes || [];
                    const logs = window.__m_api_logs || [];
                    return {awemes, logs};
                }""")
                if mdata.get('awemes'):
                    add_awemes(mdata['awemes'], tag + '-final')
                if mdata.get('logs'):
                    for log_entry in mdata.get('logs', [])[:3]:
                        print(f"  [{tag}-api-final] {log_entry}")
            except Exception:
                pass

            print(f"  [{tag}] 完成，新增 {len(captured_awemes) - before} 条")
        except Exception as e:
            print(f"  [{tag}] 异常: {e}")
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    def fetch_individual_post(browser, aweme_id: str, tag: str = 'detail'):
        """快速访问单个作品分享页，提取aweme数据。优化速度：短超时、少URL。"""
        ctx = None
        urls_to_try = [
            f'https://m.douyin.com/share/video/{aweme_id}',
            f'https://www.iesdouyin.com/share/video/{aweme_id}',
            f'https://www.douyin.com/video/{aweme_id}',
        ]
        for url in urls_to_try:
            is_mobile = 'm.douyin' in url or 'iesdouyin' in url
            try:
                ctx = browser.new_context(
                    user_agent=mobile_ua if is_mobile else
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 390, 'height': 844} if is_mobile else {'width': 1920, 'height': 1080},
                    locale='zh-CN', timezone_id='Asia/Shanghai',
                    is_mobile=is_mobile, has_touch=is_mobile,
                )
                ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=8000)
                except Exception:
                    try: ctx.close()
                    except: pass
                    ctx = None
                    continue
                page.wait_for_timeout(1500)

                aweme_data = page.evaluate("""(aid) => {
                    function deepFind(obj, depth) {
                        if (!obj || depth > 8 || typeof obj !== 'object') return null;
                        if (obj.aweme_id && String(obj.aweme_id) === aid) return obj;
                        if (Array.isArray(obj)) {
                            for (const item of obj) {
                                const f = deepFind(item, depth+1);
                                if (f) return f;
                            }
                        } else {
                            for (const key of Object.keys(obj)) {
                                const f = deepFind(obj[key], depth+1);
                                if (f) return f;
                            }
                        }
                        return null;
                    }
                    for (const store of [window._ROUTER_DATA, window._SIGI_STATE, window.__INITIAL_STATE__]) {
                        try {
                            if (store) {
                                const f = deepFind(store, 0);
                                if (f) return {aweme: f, source: store === window._ROUTER_DATA ? '_ROUTER_DATA' : store === window._SIGI_STATE ? '_SIGI_STATE' : '__INITIAL_STATE__'};
                            }
                        } catch(e) {}
                    }
                    for (const elId of ['RENDER_DATA', '__NEXT_DATA__']) {
                        try {
                            const el = document.getElementById(elId);
                            if (el) {
                                let data;
                                if (elId === 'RENDER_DATA') {
                                    data = JSON.parse(decodeURIComponent(el.textContent));
                                } else {
                                    data = JSON.parse(el.textContent);
                                }
                                const f = deepFind(data, 0);
                                if (f) return {aweme: f, source: elId};
                            }
                        } catch(e) {}
                    }
                    try {
                        const scripts = document.querySelectorAll('script');
                        for (const s of scripts) {
                            const text = s.textContent || '';
                            const marker = '"aweme_id":"' + aid + '"';
                            if (!text.includes(marker)) continue;
                            const pos = text.indexOf(marker);
                            for (let back = Math.max(0, pos-2000); back < pos; back++) {
                                if (text[back] !== '{') continue;
                                let depth = 0, inStr = false, esc = false, end = -1;
                                for (let i = back; i < Math.min(text.length, back+15000); i++) {
                                    const c = text[i];
                                    if (esc) { esc = false; continue; }
                                    if (c === '\\') { esc = true; continue; }
                                    if (c === '"') { inStr = !inStr; continue; }
                                    if (inStr) continue;
                                    if (c === '{') depth++;
                                    else if (c === '}') { depth--; if (depth === 0) { end = i; break; } }
                                }
                                if (end > back) {
                                    try {
                                        const obj = JSON.parse(text.substring(back, end+1));
                                        if (obj.aweme_id && String(obj.aweme_id) === aid) {
                                            return {aweme: obj, source: 'script'};
                                        }
                                    } catch(e2) {}
                                }
                            }
                        }
                    } catch(e) {}
                    return null;
                }""", aweme_id)

                try: ctx.close()
                except: pass
                ctx = None

                if aweme_data and aweme_data.get('aweme'):
                    a = aweme_data['aweme']
                    atype = a.get('aweme_type', '?')
                    desc = (a.get('desc') or '')[:30]
                    print(f"  [{tag}] 从{aweme_data['source']}获取 id={aweme_id} type={atype} desc={desc}")
                    return a
            except Exception:
                if ctx:
                    try: ctx.close()
                    except: pass
                ctx = None
        return None

    def fetch_from_pc_page(browser):
        """从PC端douyin.com用户主页抓取作品。

        策略（按优先级）：
        1. 在init_script中hook fetch/XHR，捕获aweme/post API响应JSON
        2. 从页面内嵌JSON（SIGI_STATE/RENDER_DATA等）提取作品
        3. DOM提取ID + 视频分享页获取详情（最终备用）
        """
        ctx = None
        try:
            before = len(captured_awemes)
            print(f"  [pc] 访问 www.douyin.com/user/...")
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN', timezone_id='Asia/Shanghai',
            )
            # Hook fetch/XHR在页面内部捕获API响应（最可靠的拦截方式）
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});

                window.__captured_awemes = [];
                window.__api_logs = [];

                function tryParseAwemeList(data, url) {
                    try {
                        if (!data || typeof data !== 'object') return;
                        const list = data.aweme_list || data.awemes;
                        if (Array.isArray(list) && list.length > 0 && list[0] && list[0].aweme_id) {
                            window.__captured_awemes.push(...list);
                            window.__api_logs.push({url: url.substring(0,100), count: list.length, source: 'direct'});
                        }
                    } catch(e) {}
                }

                // Hook fetch
                const _origFetch = window.fetch;
                window.fetch = function() {
                    return _origFetch.apply(this, arguments).then(resp => {
                        const url = resp.url || '';
                        const shouldSkip = url.includes('iteminfo') || url.includes('reply') || url.includes('comment') || url.includes('favorite') || url.includes('like') || url.includes('follow') || url.includes('live') || url.includes('publish');
                        if (!shouldSkip && (url.includes('/aweme/') || url.includes('aweme/post'))) {
                            const clone = resp.clone();
                            clone.json().then(data => {
                                tryParseAwemeList(data, url);
                                function deepSearch(obj, depth) {
                                    if (!obj || depth > 8 || typeof obj !== 'object') return;
                                    if (Array.isArray(obj)) {
                                        if (obj.length > 0 && obj[0] && obj[0].aweme_id) {
                                            const valid = obj.filter(x => x && x.aweme_id);
                                            if (valid.length) {
                                                window.__captured_awemes.push(...valid);
                                                window.__api_logs.push({url: url, count: valid.length, source: 'deep'});
                                            }
                                            return;
                                        }
                                        for (const item of obj) deepSearch(item, depth+1);
                                    } else {
                                        if (obj.aweme_id) {
                                            window.__captured_awemes.push(obj);
                                            window.__api_logs.push({url: url, count: 1, source: 'single'});
                                        }
                                        for (const key of Object.keys(obj)) deepSearch(obj[key], depth+1);
                                    }
                                }
                                deepSearch(data, 0);
                            }).catch(() => {});
                        }
                        return resp;
                    });
                };

                // Hook XMLHttpRequest
                const _origXHROpen = XMLHttpRequest.prototype.open;
                const _origXHRSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this.__url = url;
                    return _origXHROpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    const u = this.__url || '';
                    const shouldSkip = u.includes('iteminfo') || u.includes('reply') || u.includes('comment') || u.includes('favorite') || u.includes('like') || u.includes('follow') || u.includes('live');
                    if (u && !shouldSkip && (u.includes('/aweme/') || u.includes('aweme/post'))) {
                        this.addEventListener('load', function() {
                            try {
                                const data = JSON.parse(this.responseText);
                                tryParseAwemeList(data, this.__url);
                                function deepSearch(obj, depth) {
                                    if (!obj || depth > 8 || typeof obj !== 'object') return;
                                    if (Array.isArray(obj)) {
                                        if (obj.length > 0 && obj[0] && obj[0].aweme_id) {
                                            const valid = obj.filter(x => x && x.aweme_id);
                                            if (valid.length) {
                                                window.__captured_awemes.push(...valid);
                                                window.__api_logs.push({url: this.__url.substring(0,100), count: valid.length, source: 'xhr-deep'});
                                            }
                                            return;
                                        }
                                        for (const item of obj) deepSearch(item, depth+1);
                                    } else {
                                        if (obj.aweme_id) {
                                            window.__captured_awemes.push(obj);
                                        }
                                        for (const key of Object.keys(obj)) deepSearch(obj[key], depth+1);
                                    }
                                }
                                deepSearch(data, 0);
                            } catch(e) {}
                        });
                    }
                    return _origXHRSend.apply(this, arguments);
                };
            """)
            page = ctx.new_page()
            page.on('response', make_on_response('pc'))
            try:
                page.goto(f'https://www.douyin.com/user/{sec_uid}',
                          wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                print(f"  [pc] goto异常(可忽略): {e}")

            print(f"  [pc] 页面URL: {page.url}")
            for _ in range(25):
                try:
                    t = page.title()
                    if t and '抖音' in t:
                        print(f"  [pc] 页面标题: {t}")
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1000)
            else:
                try:
                    print(f"  [pc] 页面标题(未达预期): {page.title()}")
                except Exception:
                    pass

            def collect_hook_awemes(tag):
                try:
                    data = page.evaluate("""() => {
                        const awemes = window.__captured_awemes || [];
                        const logs = window.__api_logs || [];
                        window.__captured_awemes = [];
                        window.__api_logs = [];
                        return {awemes: awemes, logs: logs};
                    }""")
                    hook_awemes = data.get('awemes', [])
                    hook_logs = data.get('logs', [])
                    if hook_logs:
                        for log_entry in hook_logs[:5]:
                            print(f"  [{tag}-api] {log_entry}")
                    if hook_awemes:
                        cnt = add_awemes(hook_awemes, tag)
                        print(f"  [{tag}] 从hook提取 {cnt} 条 (hook本次 {len(hook_awemes)})")
                        return cnt
                except Exception as e:
                    print(f"  [{tag}] 读取hook数据异常: {e}")
                return 0

            for _ in range(15):
                page.wait_for_timeout(1000)
                hc = collect_hook_awemes('pc-hook')
                if hc > 0:
                    break

            try:
                page_data = page.evaluate("""() => {
                    const result = {sources: {}, videoIds: [], noteIds: []};
                    // 1. 尝试从 window._SIGI_STATE_ 提取
                    try {
                        if (window._SIGI_STATE) {
                            const sigi = JSON.stringify(window._SIGI_STATE).substring(0, 200);
                            result.sources.SIGI_STATE = sigi;
                            // 查找aweme列表
                            const sigiState = window._SIGI_STATE;
                            if (sigiState && sigiState.AwemeList) {
                                const list = Object.values(sigiState.AwemeList).filter(x => x && x.aweme_id);
                                result.sigiAwemes = list.slice(0, 20);
                            }
                            // 另一种结构：sigiState.ItemModule 或 sigiState.aweme
                            if (sigiState && sigiState.ItemModule) {
                                const list = Object.values(sigiState.ItemModule);
                                result.sigiAwemes = (result.sigiAwemes || []).concat(list.filter(x => x && x.aweme_id).slice(0, 20));
                            }
                        }
                    } catch(e) { result.sources.SIGI_STATE_ERR = String(e); }

                    // 2. 尝试从 RENDER_DATA script标签提取（Douyin PC端SSR数据）
                    try {
                        const rd = document.getElementById('RENDER_DATA');
                        if (rd) {
                            result.sources.RENDER_DATA_len = rd.textContent.length;
                            result.sources.RENDER_DATA = rd.textContent.substring(0, 300);
                            try {
                                const decoded = decodeURIComponent(rd.textContent);
                                const data = JSON.parse(decoded);
                                result.renderDataKeys = Object.keys(data).slice(0, 20);
                                // 深度递归搜索所有含aweme_id的对象
                                const foundAwemes = [];
                                const seenAwemeIds = new Set();
                                function deepSearch(obj, depth, path) {
                                    if (!obj || depth > 12 || typeof obj !== 'object') return;
                                    if (foundAwemes.length >= 20) return;
                                    if (Array.isArray(obj)) {
                                        // 检查数组是否是aweme列表
                                        if (obj.length > 0 && obj[0] && typeof obj[0] === 'object' && obj[0].aweme_id) {
                                            for (const item of obj) {
                                                if (item && item.aweme_id && !seenAwemeIds.has(item.aweme_id)) {
                                                    seenAwemeIds.add(String(item.aweme_id));
                                                    foundAwemes.push(item);
                                                    if (foundAwemes.length >= 20) return;
                                                }
                                            }
                                            return;
                                        }
                                        for (let i = 0; i < obj.length; i++) {
                                            deepSearch(obj[i], depth+1, path+'['+i+']');
                                            if (foundAwemes.length >= 20) return;
                                        }
                                    } else {
                                        // 如果当前对象本身有aweme_id，它就是一个aweme
                                        if (obj.aweme_id && !seenAwemeIds.has(obj.aweme_id)) {
                                            seenAwemeIds.add(String(obj.aweme_id));
                                            foundAwemes.push(obj);
                                            if (foundAwemes.length >= 20) return;
                                        }
                                        for (const key of Object.keys(obj)) {
                                            // 优先检查可能包含作品列表的键
                                            if (key === 'aweme_list' || key === 'awemes' || key === 'post' ||
                                                key === 'data' || key === 'list' || key === 'awemeDetail' ||
                                                key === 'item_list' || key === 'items') {
                                                deepSearch(obj[key], depth+1, path+'.'+key);
                                            }
                                        }
                                        if (foundAwemes.length < 20) {
                                            for (const key of Object.keys(obj)) {
                                                if (key === 'aweme_list' || key === 'awemes' || key === 'post' ||
                                                    key === 'data' || key === 'list' || key === 'awemeDetail' ||
                                                    key === 'item_list' || key === 'items') continue;
                                                deepSearch(obj[key], depth+1, path+'.'+key);
                                                if (foundAwemes.length >= 20) return;
                                            }
                                        }
                                    }
                                }
                                deepSearch(data, 0, 'root');
                                if (foundAwemes.length) {
                                    result.renderAwemes = foundAwemes;
                                    result.renderAwemePaths = foundAwemes.map(a => ({id: a.aweme_id, type: a.aweme_type, desc: (a.desc||'').substring(0,30)}));
                                }
                            } catch(e2) { result.sources.RENDER_DATA_PARSE_ERR = String(e2).substring(0,200); }
                        } else {
                            result.sources.NO_RENDER_DATA = true;
                        }
                    } catch(e) { result.sources.RENDER_DATA_ERR = String(e); }

                    // 3. 尝试从 __NEXT_DATA__ 提取
                    try {
                        const nd = document.getElementById('__NEXT_DATA__');
                        if (nd) {
                            result.sources.NEXT_DATA = nd.textContent.substring(0, 200);
                            try {
                                const data = JSON.parse(nd.textContent);
                                function findAwemes(obj, depth) {
                                    if (!obj || depth > 5 || typeof obj !== 'object') return [];
                                    if (Array.isArray(obj)) {
                                        if (obj.length > 0 && obj[0] && obj[0].aweme_id) return obj;
                                        for (const item of obj) {
                                            const found = findAwemes(item, depth+1);
                                            if (found.length) return found;
                                        }
                                    } else {
                                        for (const key of Object.keys(obj)) {
                                            if (key === 'aweme_list' || key === 'awemes') {
                                                const val = obj[key];
                                                if (Array.isArray(val) && val.length > 0 && val[0] && val[0].aweme_id) return val;
                                            }
                                            const found = findAwemes(obj[key], depth+1);
                                            if (found.length) return found;
                                        }
                                    }
                                    return [];
                                }
                                const awemes = findAwemes(data, 0);
                                if (awemes.length) {
                                    result.nextAwemes = awemes.slice(0, 20);
                                }
                            } catch(e2) { result.sources.NEXT_DATA_PARSE_ERR = String(e2); }
                        }
                    } catch(e) { result.sources.NEXT_DATA_ERR = String(e); }

                    // 4. 从DOM提取所有视频/图文链接的aweme_id
                    try {
                        const allLinks = document.querySelectorAll('a[href*="/video/"], a[href*="/note/"]');
                        const ids = new Set();
                        allLinks.forEach(a => {
                            try {
                                const path = new URL(a.href).pathname;
                                const parts = path.split('/');
                                for (let i = 0; i < parts.length - 1; i++) {
                                    if (parts[i] === 'video' || parts[i] === 'note') {
                                        const idStr = parts[i+1].split('?')[0].split('#')[0];
                                        if (/^\\d+$/.test(idStr)) ids.add(idStr);
                                    }
                                }
                            } catch(e2) {}
                        });
                        result.videoIds = Array.from(ids).slice(0, 30);
                    } catch(e) {}

                    // 5. 扫描所有script标签查找aweme数据
                    try {
                        const scripts = document.querySelectorAll('script');
                        let foundFromScripts = [];
                        for (const s of scripts) {
                            const text = s.textContent || '';
                            if (text.length < 50) continue;
                            // 查找自渲染数据块 RENDER_DATA
                            if (text.includes('aweme_id') && (text.includes('aweme_list') || text.includes('desc'))) {
                                try {
                                    // 尝试作为JSON解析
                                    const trimmed = text.trim();
                                    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
                                        const data = JSON.parse(trimmed);
                                        function findAwemesDeep(obj, depth) {
                                            if (!obj || depth > 6 || typeof obj !== 'object') return [];
                                            if (Array.isArray(obj)) {
                                                if (obj.length > 0 && obj[0] && obj[0].aweme_id) return obj.filter(x => x && x.aweme_id);
                                                let found = [];
                                                for (const item of obj) {
                                                    const f = findAwemesDeep(item, depth+1);
                                                    if (f.length) found = found.concat(f);
                                                }
                                                return found;
                                            } else {
                                                let found = [];
                                                for (const key of Object.keys(obj)) {
                                                    if (key === 'aweme_list' || key === 'awemes') {
                                                        const val = obj[key];
                                                        if (Array.isArray(val) && val.length > 0 && val[0] && val[0].aweme_id) {
                                                            found = found.concat(val.filter(x => x && x.aweme_id));
                                                        }
                                                    }
                                                    const f = findAwemesDeep(obj[key], depth+1);
                                                    if (f.length) found = found.concat(f);
                                                }
                                                return found;
                                            }
                                        }
                                        const awemes = findAwemesDeep(data, 0);
                                        if (awemes.length > foundFromScripts.length) {
                                            foundFromScripts = awemes.slice(0, 20);
                                        }
                                    }
                                } catch(e3) {}
                            }
                        }
                        if (foundFromScripts.length) {
                            result.scriptAwemes = foundFromScripts;
                        }
                    } catch(e) {}

                    return result;
                }""")
                print(f"  [pc] 页面数据来源: {list(page_data.get('sources', {}).keys())}")
                if page_data.get('renderDataKeys'):
                    print(f"  [pc] RENDER_DATA keys: {page_data['renderDataKeys'][:15]}")
                if page_data.get('renderAwemePaths'):
                    print(f"  [pc] RENDER_DATA awemes: {page_data['renderAwemePaths']}")
                if page_data.get('sigiAwemes'):
                    cnt = add_awemes(page_data['sigiAwemes'], 'pc-sigi')
                    print(f"  [pc-sigi] 从SIGI_STATE提取 {cnt} 条")
                if page_data.get('renderAwemes'):
                    cnt = add_awemes(page_data['renderAwemes'], 'pc-render')
                    print(f"  [pc-render] 从RENDER_DATA提取 {cnt} 条")
                if page_data.get('nextAwemes'):
                    cnt = add_awemes(page_data['nextAwemes'], 'pc-next')
                    print(f"  [pc-next] 从NEXT_DATA提取 {cnt} 条")
                if page_data.get('scriptAwemes'):
                    cnt = add_awemes(page_data['scriptAwemes'], 'pc-script')
                    print(f"  [pc-script] 从script标签提取 {cnt} 条")
                dom_ids = page_data.get('videoIds', [])
                print(f"  [pc] DOM中发现 {len(dom_ids)} 个作品ID: {dom_ids[:10]}")
                for did in dom_ids:
                    dom_seen_ids.add(did)
            except Exception as e:
                print(f"  [pc] 页面数据提取异常: {e}")
                dom_ids = []

            for scroll_i in range(8):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(2000)
                collect_hook_awemes(f'pc-scroll{scroll_i+1}')

            page.wait_for_timeout(5000)
            collect_hook_awemes('pc-final')

            try:
                api_logs_final = page.evaluate("window.__api_logs || []")
                if api_logs_final:
                    print(f"  [pc] API拦截日志总数: {len(api_logs_final)}")
                    for log_entry in api_logs_final:
                        print(f"    log: {log_entry}")
            except Exception:
                pass

            try:
                post_goto_ids = page.evaluate("""() => {
                    const allLinks = document.querySelectorAll('a[href*="/video/"], a[href*="/note/"]');
                    const ids = new Set();
                    allLinks.forEach(a => {
                        try {
                            const path = new URL(a.href).pathname;
                            const parts = path.split('/');
                            for (let i = 0; i < parts.length - 1; i++) {
                                if (parts[i] === 'video' || parts[i] === 'note') {
                                    const idStr = parts[i+1].split('?')[0].split('#')[0];
                                    if (/^\\d+$/.test(idStr)) ids.add(idStr);
                                }
                            }
                        } catch(e2) {}
                    });
                    return Array.from(ids).slice(0, 50);
                }""")
                new_dom_ids = [i for i in post_goto_ids if i not in seen_raw_ids]
                for did in post_goto_ids:
                    dom_seen_ids.add(did)
                print(f"  [pc] 滚动后DOM中共 {len(post_goto_ids)} 个ID，新增 {len(new_dom_ids)} 个")
                if new_dom_ids:
                    print(f"  [pc] 新增DOM ID列表: {new_dom_ids[:20]}")
            except Exception:
                new_dom_ids = []

            print(f"  [pc] 完成，新增 {len(captured_awemes) - before} 条")
        except Exception as e:
            print(f"  [pc] 异常: {e}")
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ],
        )

        fetch_from_share_page(browser, 'm.douyin.com', 'm')
        fetch_from_share_page(browser, 'www.iesdouyin.com', 'ies')
        fetch_from_share_page(browser, 'm.douyin.com', 'm-user', path_prefix='/user/')
        fetch_from_pc_page(browser)

        # 备用：对DOM中发现但list API未返回的ID，逐个访问独立视频/图文页获取数据（限制最多5个）
        if dom_seen_ids:
            known_ids = {str(a.get('aweme_id','')) for a in captured_awemes}
            missing_ids = [did for did in dom_seen_ids if did not in known_ids]
            # 按ID数值降序排列（大ID=新作品优先）
            try:
                missing_ids.sort(key=lambda x: int(x), reverse=True)
            except Exception:
                pass
            if missing_ids:
                print(f"  [detail] DOM中有 {len(missing_ids)} 个ID需独立获取(最多5个): {missing_ids[:5]}")
                for mid in missing_ids[:5]:
                    aweme = fetch_individual_post(browser, mid, 'detail')
                    if aweme:
                        add_awemes([aweme], 'detail')

        browser.close()

    if not captured_awemes:
        return [], "no_data"

    # 先打印所有捕获到的作品信息用于诊断
    print(f"  [诊断] 捕获到 {len(captured_awemes)} 条作品，开始过滤...")
    type_counts = {}
    for a in captured_awemes:
        aid = str(a.get('aweme_id', '?'))
        atype = a.get('aweme_type', '?')
        author = a.get("author", {}) or {}
        asec = (author.get("sec_uid") or "")[:20]
        anick = (author.get("nickname") or "?")[:15]
        type_counts[str(atype)] = type_counts.get(str(atype), 0) + 1
    print(f"  [诊断] aweme_type分布: {type_counts}")

    # 过滤：只保留作者 sec_uid 严格匹配的作品（防止串号/推荐内容混入）
    # 注意：没有author.sec_uid的作品一律丢弃（通常是推荐流/广告内容）
    filtered_awemes = []
    for a in captured_awemes:
        author = a.get("author", {}) or {}
        author_sec = author.get("sec_uid") or ""
        if author_sec == sec_uid:
            filtered_awemes.append(a)
        elif not author_sec:
            print(f"  [过滤-丢弃] 无sec_uid: id={a.get('aweme_id')} type={a.get('aweme_type')} desc={(a.get('desc') or '')[:30]}")
        else:
            anick = (author.get("nickname") or "?")[:15]
            print(f"  [过滤-丢弃] 非目标用户: id={a.get('aweme_id')} type={a.get('aweme_type')} author={anick} sec={author_sec[:20]}...")

    if not filtered_awemes:
        print("  [警告] 过滤后无作品（全部为非目标用户）")
        return [], "no_data"

    # 打印过滤后作品的类型分布
    filtered_types = {}
    for a in filtered_awemes:
        t = str(a.get('aweme_type', '?'))
        filtered_types[t] = filtered_types.get(t, 0) + 1
    print(f"  [诊断] 过滤后 {len(filtered_awemes)} 条作品, 类型分布: {filtered_types}")
    for a in filtered_awemes[:5]:
        aid = a.get('aweme_id')
        atype = a.get('aweme_type')
        desc = (a.get('desc') or '')[:40]
        print(f"    id={aid} type={atype} desc={desc}")

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
