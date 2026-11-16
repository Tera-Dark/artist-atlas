# -*- coding: utf-8 -*-
"""
小红书采集引擎（重写版）
关键修正：
  1. 从 __INITIAL_STATE__.search.feeds 直接取笔记 id + xsecToken
  2. 用带 token 的 /explore/{id}?xsec_token=...&xsec_source=pc_search 打开
  3. 正文与图片从 __INITIAL_STATE__.note.noteDetailMap 读，不靠 DOM 猜
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

BASE = "https://www.xiaohongshu.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

MASK_JS = """
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome = window.chrome || {runtime:{}};
Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh']});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
"""

# 读取搜索结果（含 token）
JS_SEARCH = """
() => {
  const unwrap = v => (v && v._value !== undefined) ? v._value
                    : (v && v.value !== undefined) ? v.value : v;
  try {
    const s = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.search;
    if (!s) return [];
    const arr = unwrap(s.feeds);
    if (!Array.isArray(arr)) return [];
    const out = [];
    for (const x of arr) {
      const nc = x.noteCard || {};
      if (!x.id || !x.xsecToken) continue;
      out.push({
        id: x.id,
        token: x.xsecToken,
        title: nc.displayTitle || '',
        author: (nc.user && (nc.user.nickname || nc.user.nickName)) || '',
        likes: (nc.interactInfo && nc.interactInfo.likedCount) || ''
      });
    }
    return out;
  } catch (e) { return []; }
}
"""

# 读取笔记详情（正文 + 全部图片）
JS_NOTE = """
(noteId) => {
  const unwrap = v => (v && v._value !== undefined) ? v._value
                    : (v && v.value !== undefined) ? v.value : v;
  try {
    const nstate = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.note;
    if (!nstate) return null;
    const map = unwrap(nstate.noteDetailMap);
    if (!map) return null;
    let entry = map[noteId];
    if (!entry) {
      const ks = Object.keys(map);
      if (!ks.length) return null;
      entry = map[ks[ks.length - 1]];
    }
    const n = entry && entry.note;
    if (!n) return null;
    const imgs = [];
    for (const im of (n.imageList || [])) {
      let u = im.urlDefault || im.urlPre || im.url || '';
      if (!u && Array.isArray(im.infoList) && im.infoList.length) {
        u = im.infoList[im.infoList.length - 1].url || '';
      }
      if (u) imgs.push(u);
    }
    return {
      id: n.noteId || noteId,
      title: n.title || '',
      desc: n.desc || '',
      author: (n.user && (n.user.nickname || n.user.nickName)) || '',
      images: imgs,
      tags: (n.tagList || []).map(t => t.name).filter(Boolean),
      time: n.time || 0
    };
  } catch (e) { return null; }
}
"""

BLOCK_SIGNS = [
    "当前笔记暂时无法浏览", "笔记暂时无法浏览", "内容无法浏览",
    "该笔记已删除", "笔记不存在", "内容已删除", "页面不存在",
    "访问过于频繁", "操作过于频繁", "请稍后再试", "网络异常",
    "登录后查看", "请先登录", "扫码登录", "验证后继续", "安全验证",
]


def log_default(msg):
    print(msg, flush=True)


def open_context(p, profile: Path, headless=False, log=log_default):
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(profile), channel="chrome", headless=headless,
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(MASK_JS)
    return ctx


def is_logged_in(page):
    try:
        if page.query_selector(".login-container, .login-modal"):
            return False
        if page.query_selector("section.note-item"):
            return True
        txt = page.inner_text("body", timeout=5000)
        if any(k in txt for k in ("扫码登录", "登录后查看", "登录/注册")):
            return False
        # 已登录时右上角有「我」入口
        return bool(page.query_selector(".user, .side-bar .user, li.user"))
    except Exception:
        return False


def search_notes(page, keyword, limit, log=log_default):
    """搜索并从页面数据里取出带 token 的笔记列表。"""
    url = (f"{BASE}/search_result?keyword={quote(keyword)}"
           f"&source=web_explore_feed")
    log(f"搜索「{keyword}」…")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(4.5)

    items, seen = [], set()
    stagnant = 0
    for rnd in range(30):
        batch = page.evaluate(JS_SEARCH) or []
        new = 0
        for it in batch:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            items.append(it)
            new += 1
        log(f"  已找到 {len(items)} 篇（本轮新增 {new}）")
        if len(items) >= limit:
            break
        page.mouse.wheel(0, 2600)
        time.sleep(2.2)
        if new == 0:
            stagnant += 1
            if stagnant >= 3:
                log("  没有更多结果了")
                break
        else:
            stagnant = 0
    return items[:limit]


def fetch_note(page, item, log=log_default, retry=2):
    """带 token 打开笔记，返回详情 dict；失败返回 None。"""
    nid, token = item["id"], item["token"]
    url = f"{BASE}/explore/{nid}?xsec_token={quote(token)}&xsec_source=pc_search"
    for attempt in range(retry + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2.6)
            data = page.evaluate(JS_NOTE, nid)
            if data and (data.get("desc") or data.get("title")) and data.get("images"):
                blob = f"{data['title']} {data['desc']}"
                if any(b in blob for b in BLOCK_SIGNS):
                    log("    风控提示页，跳过")
                    return None
                data["url"] = url
                data["token"] = token
                return data
            # 数据没出来，等一下再读一次
            time.sleep(2.0)
            data = page.evaluate(JS_NOTE, nid)
            if data and data.get("images"):
                data["url"] = url
                data["token"] = token
                return data
        except Exception as e:
            if attempt < retry:
                time.sleep(2.5)
                continue
            log(f"    打开失败：{e}")
            return None
    return None


def image_key(url):
    """
    提取图片的稳定标识。
    小红书图片 URL 形如：
      http://sns-webpic-qc.xhscdn.com/202611131134/<随机签名>/spectrum/<图片ID>!xxx
    时间戳与签名段每次都变，只有末尾图片 ID 稳定，用它去重。
    """
    if not url:
        return ""
    u = url.split("?")[0]
    tail = u.rstrip("/").split("/")[-1]
    tail = tail.split("!")[0]
    # 去掉常见尺寸后缀
    tail = re.sub(r"_(\d+x\d+|\d+w|\d+h)$", "", tail)
    if tail and len(tail) >= 8:
        return tail
    return u


def https_url(u):
    """图床同时支持 http/https，统一用 https 以便在页面中直接加载。"""
    u = str(u or "").strip()
    if u.startswith("http://"):
        return "https://" + u[7:]
    if u.startswith("//"):
        return "https:" + u
    return u


# 无签名图床域名 + 浏览器可用的格式参数
PERM_HOST = "sns-img-qc.xhscdn.com"
# 不带参数时部分图片返回 HEIC（浏览器不支持），必须显式要 webp
PERM_FMT = "!nd_dft_wlteh_webp_3"
# 带时间戳与签名的临时域名
SIGNED_HOST_RE = re.compile(r"^sns-webpic[\w-]*\.xhscdn\.com$", re.IGNORECASE)


def permanent_url(u):
    """
    把带时间戳+签名的临时链接转成不含签名的长期链接。

    临时：http://sns-webpic-qc.xhscdn.com/202611131134/<签名>/spectrum/<ID>!xxx
    长期：https://sns-img-qc.xhscdn.com/spectrum/<ID>!nd_dft_wlteh_webp_3

    时间戳与签名段被去掉，只保留稳定的路径与图片 ID。
    非小红书图床或无法识别的链接原样返回（仅升级为 https）。
    """
    u = https_url(u)
    if not u:
        return ""
    try:
        body = u.split("://", 1)[1]
        seg = body.split("/")
        host, rest = seg[0], seg[1:]
    except IndexError:
        return u
    if not rest:
        return u
    tail = rest[-1]
    iid = tail.split("!")[0].split("?")[0]
    if not iid:
        return u

    if SIGNED_HOST_RE.match(host):
        # rest = [时间戳, 签名, ...路径(可能为空), 文件名]
        if len(rest) < 3:
            return u
        path_parts = rest[2:-1]
    elif host.endswith("xhscdn.com"):
        # 已经是无签名形式，只补格式参数
        path_parts = rest[:-1]
    else:
        return u

    path = "/".join(p for p in path_parts if p)
    base = f"https://{PERM_HOST}/"
    return base + (path + "/" if path else "") + iid + PERM_FMT


def is_permanent(u):
    """判断链接是否已是不含签名的长期形式。"""
    u = str(u or "")
    return PERM_HOST in u and not re.search(r"/\d{12}/", u)


def normalize_image(im):
    """
    把一条图片记录的展示链接归一为永久链接。

    入库时已经转过，但旧清单、撤销还原写回的记录可能还带着
    时间戳+签名的临时链接，过期后图就加载不出来。这里统一兜底：
    优先用 src，src 为空时退回 orig，并补齐稳定去重键。
    返回是否发生了改动，便于调用方决定要不要落盘。
    """
    if not isinstance(im, dict):
        return False
    changed = False
    src = str(im.get("src") or "").strip()
    orig = str(im.get("orig") or "").strip()
    want = permanent_url(src or orig)
    if want and want != src:
        im["src"] = want
        changed = True
    if not im.get("key"):
        k = image_key(im.get("src") or orig)
        if k:
            im["key"] = k
            changed = True
    return changed


def phash(data, size=8):
    """
    差值感知哈希（dHash）：把图缩到 (size+1)×size 灰度，
    比较左右相邻像素亮度，得到 size*size 位指纹。

    对缩放、格式转换、轻度压缩不敏感——同一张画的不同尺寸/
    格式版本会得到相同或极近的指纹，而不同画差别很大。
    这正是「同一张画被重新上传、拿到新图片ID」时 URL 去重抓不到的情况。

    返回十六进制字符串；无法解析时返回空串（调用方需退回 URL 去重）。
    """
    if not data:
        return ""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("L")
        im = im.resize((size + 1, size), Image.LANCZOS)
        px = list(im.getdata())
        bits = 0
        for row in range(size):
            base = row * (size + 1)
            for col in range(size):
                bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
        return format(bits, "0%dx" % (size * size // 4))
    except Exception:
        return ""


def phash_distance(h1, h2):
    """两个感知哈希的汉明距离；任一为空时返回一个大值（视为不同）。"""
    if not h1 or not h2 or len(h1) != len(h2):
        return 999
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except ValueError:
        return 999


# dHash 64 位：≤5 位差异视为同一张画的不同版本（缩放/压缩/格式转换），
# 阈值取保守值，宁可多搜一张也不把两张不同的画误判成同一张。
PHASH_SAME_THRESHOLD = 5


def same_picture(h1, h2):
    """两图是否实质为同一张画。"""
    return phash_distance(h1, h2) <= PHASH_SAME_THRESHOLD


def dominant_colors(data, limit=5):
    """
    从图片字节里提取主色调，返回 [[r,g,b], ...]。
    优先用 Pillow；没有则用标准库解析 JPEG/PNG 的粗略采样，
    再不行返回空列表（界面会自动隐藏配色条）。
    """
    if not data:
        return []
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((48, 48))
        px = list(im.getdata())
    except Exception:
        return []

    buckets = {}
    for r, g, b in px:
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 30 or mx > 246:
            continue          # 排除纯黑纯白
        if mx - mn < 30:
            continue          # 排除灰阶
        k = (r >> 5, g >> 5, b >> 5)
        o = buckets.setdefault(k, [0, 0, 0, 0])
        o[0] += 1
        o[1] += r
        o[2] += g
        o[3] += b

    def vivid_score(o):
        """兼顾出现频次与鲜艳度：让配色条代表画风而非背景灰。"""
        r, g, b = o[1] / o[0], o[2] / o[0], o[3] / o[0]
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / mx if mx else 0
        # 中等明度最讨喜，过暗过亮都降权
        light = mx / 255
        lum_w = 1.0 - abs(light - 0.62) * 0.8
        return (o[0] ** 0.55) * (0.35 + sat) * max(lum_w, 0.25)

    ranked = sorted(buckets.values(), key=vivid_score, reverse=True)
    picked = []
    for o in ranked:
        c = [round(o[1] / o[0]), round(o[2] / o[0]), round(o[3] / o[0])]
        # 色相相近的合并，保证 5 个色块彼此可区分
        if any(sum(abs(c[i] - p[i]) for i in range(3)) < 96 for p in picked):
            continue
        picked.append(c)
        if len(picked) >= limit:
            break
    return picked


DANBOORU = "https://danbooru.donmai.us"


def has_cjk(s):
    """是否含中日文字符。"""
    return bool(re.search(r"[\u4e00-\u9fa5\u3040-\u30ff]", str(s or "")))


def danbooru_query(name):
    """
    画师检索用的名字：保留原名（含日文/中文），只去 @ 与首尾空白。
    Danbooru 的画师条目本身就存了原名与别名，用原名检索即可命中，
    不需要、也不应该替换成罗马字。
    """
    return str(name or "").strip().lstrip("@").strip()


def danbooru_url(name, aliases=None):
    """
    画师条目检索页：artists?search[any_name_matches]=<名字>
    any_name_matches 会同时匹配本名与其它名称（别名），
    因此原名、罗马字名都能命中同一位画师。
    """
    q = danbooru_query(name)
    if not q:
        return ""
    return (f"{DANBOORU}/artists?commit=Search"
            f"&search%5Bany_name_matches%5D={quote(q, safe='')}"
            f"&search%5Border%5D=created_at")


def danbooru_alt_url(name, aliases=None):
    """备选入口：用第一个别名再检索一次（原名为空时返回空）。"""
    for al in (aliases or []):
        q = danbooru_query(al)
        if q and q != danbooru_query(name):
            return danbooru_url(q)
    return ""


def danbooru_tag(name, aliases=None):
    """
    作品标签页用的标签（罗马字形式），仅作为附加入口。
    与画师检索分开：标签页只认罗马字标签，检索页认原名。
    """
    cands = [name] + list(aliases or [])
    ascii_cands = [c for c in cands if c and not has_cjk(c)]
    pick = ascii_cands[0] if ascii_cands else (name or "")
    return str(pick).strip().lstrip("@").replace(" ", "_")


def danbooru_posts_url(name, aliases=None):
    """作品标签页（附加入口，可能查不到，故不作主按钮）。"""
    tag = danbooru_tag(name, aliases)
    if not tag:
        return ""
    return f"{DANBOORU}/posts?tags={quote(tag, safe='')}"


def download_image(ctx, url, dest: Path, log=log_default):
    if dest.exists() and dest.stat().st_size > 2048:
        return True
    try:
        r = ctx.request.get(url, headers={"Referer": BASE + "/"}, timeout=30000)
        if r.status != 200:
            return False
        body = r.body()
        if len(body) < 1024:
            return False
        dest.write_bytes(body)
        return True
    except Exception:
        return False


# ---------------- 画师名解析 ----------------
STYLE_WORDS = [
    "厚涂", "平涂", "赛璐璐", "水彩", "水墨", "国风", "古风", "美式", "日系", "韩系",
    "二次元", "写实", "半写实", "卡通", "治愈", "暗黑", "哥特", "像素", "废土",
    "科幻", "机械", "线稿", "速写", "素描", "油画", "版画", "复古", "梦幻", "极简",
    "儿童插画", "绘本", "商稿", "立绘", "同人", "原创", "角色设计", "场景", "概念设计",
    "松弛", "笔触", "氛围感", "色彩", "分镜", "插画", "漫画",
]

# 小红书官方/运营账号，帖子常艾特它们，但不是画师
OFFICIAL_ACCOUNTS = {
    "艺术薯", "薯队长", "薯管家", "薯条小助手", "小红书", "小红书创作助手",
    "创作者小助手", "创作薯", "绘画薯", "设计薯", "摄影薯", "校园薯",
    "生活薯", "时尚薯", "美妆薯", "游戏薯", "动漫薯", "二次元薯",
    "薯宝宝", "薯小妹", "知识薯", "娱乐薯", "音乐薯", "电影薯",
}

BAD_SUBSTR = [
    "推荐", "合集", "整理", "安利", "分享", "大家", "风格", "画风", "作品",
    "链接", "主页", "关注", "点赞", "收藏", "评论", "私信", "小红书", "以下",
    "本期", "今天", "下面", "这位", "那位", "老师", "图片", "更新", "画师",
    "分镜", "配色", "光影", "线条", "色彩", "氛围", "人物", "场景", "帖子",
    "美图", "插画推荐", "作品推荐", "松弛笔触",
]

# 「插画师所有作品🈲AI」「如果以上画师有争议」这类句子里，
# 身份词后面跟的是普通名词而非人名。只靠 BAD_SUBSTR 列不全，
# 这里按语法特征拦：后接量词/范围词/助词，或整体是常见抽象名词。
NOT_A_NAME_WORDS = {
    "所有", "全部", "本人", "原创", "作品", "争议", "版权", "授权", "转载",
    "禁止", "请勿", "如有", "以上", "以下", "各位", "大家", "本人所有",
    "所有权", "著作权", "商用", "二改", "投喂", "侵删", "AI", "ai",
    # 「画师介绍：xxx」里的修饰词，不是名字
    "介绍", "推荐", "安利", "分享", "合集", "整理", "名单", "列表", "盘点",
    "简介", "资料", "科普", "讲解", "分析", "点评",
}
# 身份词后紧跟这些字，说明后面是句子成分而不是名字
NOT_NAME_SUFFIX = re.compile(r"^(?:的|们|都|也|是|有|所有|本人|作品|们儿)")

# 名字里允许出现的字符：中日文、英文数字、少量连接符
NAME_CHARS = r"\u4e00-\u9fa5\u3040-\u30ffA-Za-z0-9_.\-・ー々"
NAME_SPLIT = re.compile(
    rf"[^\{NAME_CHARS}]+")
NAME_CUT = re.compile(r"(风格|画风|擅长|作品|主页|链接|太太|大大|老师)")
LIST_LINE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.、)）]|[①②③④⑤⑥⑦⑧⑨⑩]|[一二三四五六七八九十]{1,3}\s*[、.])"
    r"\s*(.{1,40})$")

# 话题标签整段剔除，避免把「话题」当名字
HASHTAG = re.compile(r"#[^#\n]{0,40}?(?:\[话题\]#|#|$)")

# 「画师」与冒号之间可能夹的词：画师推荐：/ 画师安利：/ 插画师分享：
ROLE_GAP = r"(?:推荐|安利|分享|介绍|合集|整理|名单|列表|盘点)?"

ARTIST_PATTERNS = [
    # 画师：米室 / 画师推荐：りたお / 插画师是X上的画师：あるてら
    rf"画师{ROLE_GAP}[：:]\s*[【\[]?([{NAME_CHARS}]{{1,24}})",
    rf"插画师{ROLE_GAP}[：:]\s*[【\[]?([{NAME_CHARS}]{{1,24}})",
    rf"插画家{ROLE_GAP}[：:]\s*[【\[]?([{NAME_CHARS}]{{1,24}})",
    rf"绘师{ROLE_GAP}[：:]\s*[【\[]?([{NAME_CHARS}]{{1,24}})",
    rf"画师是[^：:\n]{{0,20}}[：:]\s*([{NAME_CHARS}]{{1,24}})",
    rf"作者{ROLE_GAP}[：:]\s*@?([{NAME_CHARS}]{{1,24}})",
    # illus：BwPuppy / illust: xxx —— 插画师缩写署名，常见于稿件展示帖。
    # 漏识别会让整篇落进「待认领」。只认缩写词，不认单字「画」以免误取。
    rf"(?i:(?:illus|illust|illustrator))\s*[：:]\s*@?([{NAME_CHARS}]{{1,24}})",
    # Art by nyz / art by XXX / Illustration by XXX（大小写均可）
    rf"(?i:(?:art|artwork|illustration|drawn|illustrated)\s+by)\s+@?([{NAME_CHARS}]{{1,24}})",
    # 【Zombie_KE】画师/作品推荐  → 标题里的方括号名
    rf"@([{NAME_CHARS}]{{1,24}})",
]

# 「西班牙插画家 Alariko（Alar Iko）」：身份词后跟名字。
# 必须有空格或冒号分隔，否则「画师用松动写意的笔锋…」这类句子会被误取。
# 中日文之间常不加空格（插画师おこげゴリゴリ），故允许身份词后直接跟
# 假名/汉字；拉丁名仍要求空格，避免把「画师abc」这类连写误取。
ROLE_THEN_NAME = re.compile(
    rf"(?:插画师|插画家|画师|绘师|艺术家|漫画家|概念艺术家)"
    rf"(?:[ \t]*[：:][ \t]*|[ \t]+)@?([{NAME_CHARS}]{{2,24}})")
# 只认「身份词 + 短名」，且名字后必须是边界（括号/空白/标点/行尾）。
# 否则「画师用松动写意的笔锋勾勒眉眼发丝」整句会被当成名字。
ROLE_THEN_CJK = re.compile(
    rf"(?:插画师|插画家|画师|绘师|艺术家|漫画家)"
    rf"([\u3040-\u30ff\u4e00-\u9fa5][{NAME_CHARS}]{{1,11}})"
    rf"(?=[（(\s，,。：:｜|/、!！?？]|$)")

# 标题「头像｜织布机loom」「画师@みっか」：名字在标题里，
# 分隔符或「画师」之后。这类帖正文可能只有话题标签，漏取会整篇待认领。
TITLE_AFTER_SEP = re.compile(
    rf"[｜|丨/／]\s*([{NAME_CHARS}]{{2,24}})\s*$")
TITLE_ROLE_NAME = re.compile(
    rf"(?:画师|插画师|插画家|绘师|作者)\s*@?([{NAME_CHARS}]{{2,24}})\s*$")

# 「作者大大：」后换行才写名字：冒号收尾且下一行是名字
ROLE_COLON_EOL = re.compile(
    rf"(?:作者|画师|插画师|插画家|绘师)(?:大大|老师|太太)?\s*[：:][ \t]*\n"
    rf"\s*([{NAME_CHARS}]{{2,24}})")

# 名字后紧跟括号内的账号：露路しぐれ（@tuyuji_0724）
# 也支持带平台前缀：おこげゴリゴリ（twi：okoge_gorigori）
NAME_WITH_HANDLE = re.compile(
    rf"([{NAME_CHARS}]{{1,24}})\s*[（(]\s*"
    rf"(?:(?i:twi|twitter|x|ins|instagram|pixiv|wb|weibo|微博|推特)\s*[：:]\s*)?"
    rf"(@?[{NAME_CHARS}]{{2,24}})\s*[)）]")

# 括号里若是国籍/地区/平台说明，不是账号，不能收作别名
NOT_HANDLE = {
    "中国", "日本", "韩国", "美国", "英国", "法国", "德国", "西班牙", "意大利",
    "俄罗斯", "泰国", "越南", "印度", "巴西", "加拿大", "澳大利亚", "国内", "国外",
    "推特", "微博", "小红书", "抖音", "快手", "哔哩哔哩", "全平台", "同名",
    "侵删", "转载", "授权", "已授权", "未授权", "图源网络", "版权归原作者所有",
}


def is_handle(s):
    """判断括号内容是否像账号：带 @、含数字或下划线、或纯 ASCII 词。"""
    t = str(s or "").strip()
    if not t:
        return False
    if t.lstrip("@") in NOT_HANDLE:
        return False
    if t.startswith("@"):
        return True
    if re.search(r"[0-9_]", t):
        return True
    # 纯拉丁字母词（如 neko、pushio）视为账号；中文词一律不视为账号
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z.\-]{1,23}", t))

# 社交账号行：X（推特）：@TeraAru6262 / 推特：xxx / ins：xxx
# 这类通常是同一位画师的账号别名，不应当成新画师
SOCIAL_LINE = re.compile(
    r"(?:^|\n)\s*[📱🐦🔗]*\s*"
    r"(?:X\s*(?:[（(]\s*推特\s*[)）])?|推特|twitter|微博|ins|instagram|"
    r"lofter|pixiv|p站|B站|bilibili|抖音|小红书号|账号|ID)"
    r"\s*[：:]",
    re.IGNORECASE)

# 正文首句直接是名字的情况：りたお，日本插画师
LEAD_NAME = re.compile(rf"^\s*([{NAME_CHARS}]{{1,20}})\s*[，,]\s*"
                       r"(?:日本|韩国|中国|美国|国内|国外|自由)?(?:插画师|画师|绘师)")


# Windows 保留设备名，不能直接作为文件/文件夹名
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_name(s, maxlen=40):
    s = re.sub(r'[\\/:*?"<>|\r\n\t\x00-\x1f]', "_", str(s if s is not None else ""))
    s = re.sub(r"\s+", " ", s).strip(" ._")
    s = s[:maxlen].rstrip(" ._")
    if not s:
        return "未命名"
    # 保留名（含带扩展名的形式）加前缀规避
    stem = s.split(".")[0].upper()
    if stem in _WIN_RESERVED:
        s = "_" + s
    return s


def strip_tags(text):
    """去掉 #xxx[话题]# 这类标签，它们不是正文内容。"""
    if not text:
        return ""
    t = HASHTAG.sub(" ", text)
    t = re.sub(r"\[话题\]", " ", t)
    return t


def clean_name(raw, maxlen=20):
    if not raw:
        return None
    n = raw.strip().strip("【】[]（）()<>《》\"'“”‘’☾☽✨💕❤️")
    n = re.sub(r"^(是|叫|为|有|的|位)", "", n)
    n = n.strip(" ，,。.、:：!！?？~～-—_")
    n = NAME_CUT.split(n)[0].strip(" ，,。.、:：")
    # 只保留合法名字字符
    parts = [p for p in NAME_SPLIT.split(n) if p]
    n = parts[0] if parts else ""
    if not (1 <= len(n) <= maxlen):
        return None
    if not re.search(r"[\u4e00-\u9fa5\u3040-\u30ffA-Za-z]", n):
        return None
    # 单个 ASCII 字母/数字不足以作为画师名
    if len(n) == 1 and not re.search(r"[\u4e00-\u9fa5\u3040-\u30ff]", n):
        return None
    if re.fullmatch(r"[0-9.,，。_\-]+", n):
        return None
    if any(b in n for b in BAD_SUBSTR):
        return None
    # 「插画师所有作品」「画师有争议」：身份词后跟的是普通名词，不是人名
    if n in NOT_A_NAME_WORDS or NOT_NAME_SUFFIX.match(n):
        return None
    # 明显的句子而不是名字
    if re.search(r"[！!？?。]{1,}", raw) and len(n) > 8:
        return None
    if n in ("话题", "Enjoy", "enjoy"):
        return None
    if n in OFFICIAL_ACCOUNTS:
        return None
    return n


def line_of(text, pos):
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a:(len(text) if b == -1 else b)]


def style_hint(text):
    hits = [w for w in STYLE_WORDS if w in text]
    return "/".join(list(dict.fromkeys(hits))[:3]) if hits else ""


# 发帖博主的自我介绍/引流句，里面的 @账号 是博主本人，不是被推荐的画师。
# 例：「✨ 我是@啊呜~，这里高清发布插画分享、画师推荐…」
# 误收会导致整篇被当成多画师合集，图片对半分并标记为「归属待确认」。
SELF_INTRO = re.compile(
    r"(我是|本人是|我就是|这里是|大家好|欢迎关注|关注我|我的(?:主页|账号)"
    r"|高清发布|精心挑选|带你看不一样|一起审美|审美提升|成长记录"
    r"|求(?:关注|点赞|三连)|点赞关注|侵删|商改|版权归原作者)")


def is_self_intro(line):
    """该行是否为博主自我介绍/版权声明，而非画师推荐内容。"""
    return bool(SELF_INTRO.search(str(line or "")))


def parse_artists(text, title=""):
    text = strip_tags(text)
    title = strip_tags(title)
    if not text and not title:
        return []
    found, seen = [], set()

    def norm(n):
        return n.lstrip("@").lower()

    def push2(name, src, is_social=False):
        n = clean_name(name)
        if not n:
            return
        # 博主自我介绍/版权声明行里的账号是发帖人自己，不是被推荐画师
        if is_self_intro(src):
            return
        n = n.lstrip("@")
        k = norm(n)
        if k in seen:
            return
        # 社交账号行（推特/ins/微博等）：若已有主名，收为别名而非新画师
        if is_social and found:
            seen.add(k)
            if n not in found[0].setdefault("aliases", []):
                found[0]["aliases"].append(n)
            return
        seen.add(k)
        found.append({"name": n, "style": style_hint(src), "aliases": []})

    # 1) 结构化列表行优先：多画师合集靠它保证顺序
    listed = []
    for line in text.splitlines():
        m = LIST_LINE.match(line.strip())
        if m:
            body = m.group(1)
            parts = [p for p in NAME_SPLIT.split(body.lstrip("@")) if p]
            if parts:
                listed.append((parts[0], body))
    if len(listed) >= 2:
        for nm, src in listed:
            push2(nm, src)
        return found

    # 2) 「画师：露路しぐれ（@tuyuji_0724）」——括号内是同一人的账号。
    #    身份词紧跟中日文名（插画师おこげゴリゴリ）也算，必须在
    #    通用 @账号 规则之前处理，否则账号会被抢先当成第二位画师。
    for m in NAME_WITH_HANDLE.finditer(text):
        ln = line_of(text, m.start())
        if re.search(r"(画师|插画师|插画家|绘师|作者|art\s+by)", ln, re.IGNORECASE):
            nm = m.group(1)
            # 「插画师おこげゴリゴリ」这种连写，名字里带着身份词前缀，需剥掉
            nm = re.sub(r"^(?:插画师|插画家|画师|绘师|艺术家|漫画家|作者)", "", nm)
            if not nm:
                continue
            push2(nm, ln)
            if is_handle(m.group(2)):
                push2(m.group(2), ln, is_social=True)

    # 3) 显式「画师：xxx」；社交账号行收为别名
    for pat in ARTIST_PATTERNS:
        for m in re.finditer(pat, text):
            ln = line_of(text, m.start())
            push2(m.group(1), ln, is_social=bool(SOCIAL_LINE.search(ln)))

    # 4) 「西班牙插画家 Alariko」：身份词在名字之前
    for m in ROLE_THEN_NAME.finditer(text):
        push2(m.group(1), line_of(text, m.start()))

    # 4b) 「插画师おこげゴリゴリ（twi：okoge_gorigori）」：中日文不加空格
    for m in ROLE_THEN_CJK.finditer(text):
        ln = line_of(text, m.start())
        push2(m.group(1), ln)
        # 同行括号里的账号是同一人的别名
        h = NAME_WITH_HANDLE.search(ln)
        if h and is_handle(h.group(2)):
            push2(h.group(2), ln, is_social=True)

    # 4c) 「作者大大：\n织布机loom｜国人二次元画师…」：冒号收尾，名字在下一行
    for m in ROLE_COLON_EOL.finditer(text):
        push2(m.group(1), line_of(text, m.start(1)))

    # 5) 首句「りたお，日本插画师」
    for line in text.splitlines():
        m = LEAD_NAME.match(line.strip())
        if m:
            push2(m.group(1), line)

    # 4) 标题里的【名字】
    for m in re.finditer(rf"[【\[]([{NAME_CHARS}]{{2,24}})[】\]]", title):
        push2(m.group(1), title)

    # 6b) 标题「艺术家分享｜Blanc.ブラン」「画师推荐 - xxx」：分隔符后的名字
    if not found and title:
        m = re.search(rf"[｜|丨/／\-—:：]\s*([{NAME_CHARS}]{{2,24}})\s*$", title)
        if m and re.search(r"(画师|插画师|艺术家|绘师|分享|推荐|安利)", title):
            push2(m.group(1), title)

    # 6c) 标题「苺山 X:2833osi」：开头是名字，后面跟账号
    if title:
        m = re.match(
            rf"^\s*([{NAME_CHARS}]{{2,24}})\s+"
            rf"(?:X|推特|twitter|ins|instagram|pixiv|微博)\s*[：:]\s*@?([{NAME_CHARS}]{{2,24}})",
            title, re.IGNORECASE)
        if m:
            push2(m.group(1), title)
            push2(m.group(2), title, is_social=True)
        elif not found:
            # 「苺山 X:2833osi」之外，标题首词后接空白也可能是名字
            m2 = re.match(rf"^\s*([{NAME_CHARS}]{{2,24}})\s+\S", title)
            if m2 and not re.search(r"(每日|分享|推荐|合集|整理|插画|作品|审美)", m2.group(1)):
                push2(m2.group(1), title)

    # 7) 单条列表行兜底
    for nm, src in listed:
        push2(nm, src)

    # 8) 正文只有社交账号行、没有主名时（如「X：nyz」），该账号即主名
    if not found:
        for line in text.splitlines():
            if SOCIAL_LINE.search(line):
                m = re.search(rf"[：:]\s*@?([{NAME_CHARS}]{{2,24}})", line)
                if m:
                    push2(m.group(1), line)
                    break

    # 9) 正文全是话题标签时，名字只在标题里：
    #    「画师@みっか」「头像｜织布机loom」。放在最后兜底，
    #    避免标题里的通用词盖掉正文中更可靠的署名。
    if not found and title:
        m = TITLE_ROLE_NAME.search(title) or TITLE_AFTER_SEP.search(title)
        if m:
            push2(m.group(1), title)
    return found


def explicit_map(text, artists, n_img):
    if not text or not artists:
        return {}
    names = [a["name"] for a in artists]
    mapping = {}
    pat = re.compile(r"(?:图|p|P|第)\s*(\d{1,2})(?:\s*[-~到至]\s*(\d{1,2}))?\s*(?:张|图)?")
    for line in text.splitlines():
        hit = [n for n in names if n in line]
        if len(hit) != 1:
            continue
        for m in pat.finditer(line):
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else a
            if 1 <= a <= b <= n_img and b - a <= 12:
                for k in range(a, b + 1):
                    mapping[k - 1] = hit[0]
    return mapping


def build_plan(note, index):
    """返回每张图的归属与可信度。"""
    desc = note.get("desc") or ""
    title = note.get("title") or ""
    artists = parse_artists(desc, title)
    imgs = note.get("images") or []
    if not imgs:
        return []
    if not artists:
        return [{"artist": "待认领", "style": style_hint(desc),
                 "image_url": u, "seq": i + 1, "confidence": "unknown"}
                for i, u in enumerate(imgs)]

    na, ni = len(artists), len(imgs)
    emap = explicit_map(desc, artists, ni)
    names = [a["name"] for a in artists]
    out = []
    for i, u in enumerate(imgs):
        if i in emap:
            a, conf = artists[names.index(emap[i])], "explicit"
        elif na == 1:
            a, conf = artists[0], "single"
        elif na == ni:
            a, conf = artists[i], "order"
        else:
            a, conf = artists[min(na - 1, int(i * na / ni))], "guess"
        out.append({"artist": a["name"], "style": a["style"],
                    "aliases": a.get("aliases", []),
                    "image_url": u, "seq": i + 1, "confidence": conf})
    return out