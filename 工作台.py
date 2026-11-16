# -*- coding: utf-8 -*-
"""
小红书画师采集工作台 · 本地服务
双击 启动工作台.bat 即可，浏览器会自动打开工作台界面。
"""

import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

def _app_root():
    """
    程序根目录 = 用户数据存放处。

    打包成 exe 后 __file__ 指向临时解压目录（退出即销毁），
    绝不能把采集数据/凭证写在那里，否则关掉就全丢。
    因此冻结运行时一律用 exe 自身所在目录；源码运行时用脚本目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def _res_root():
    """
    只读资源目录（界面 HTML、语义映射等随包分发的文件）。
    PyInstaller 单文件模式会把它们解压到 sys._MEIPASS。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _app_root()


ROOT = _app_root()
RES = _res_root()
PROFILE = ROOT / "_profile"          # 兼容旧版：首个账号沿用此目录
ACCOUNTS_DIR = ROOT / "_accounts"    # 多账号登录态，各自独立目录
ACCOUNTS_FILE = ROOT / "账号.json"
DATA_DIR = ROOT / "采集结果"
IMG_DIR = DATA_DIR / "画师图片"
DATA_FILE = DATA_DIR / "data.json"
UI_FILE = RES / "工作台界面.html"   # 只读资源，随包分发
CRED_FILE = ROOT / "d站凭证.json"   # 只存本机，不打印、不交付
SAUCE_FILE = ROOT / "搜图凭证.json"  # 同上：只存本机，不打印、不交付
SAUCE_CACHE_FILE = DATA_DIR / "搜图缓存.json"  # 图→作者标签，复跑不重复搜
# 搜图额度台账：按画师 uid 记录「累计搜过哪几张画」，跨轮次生效。
# 保证每位画师最多 2 张，且这 2 张必须是内容不同的画。
SAUCE_LEDGER_FILE = DATA_DIR / "搜图台账.json"
# 语义身份映射：随包分发的纠正规则；用户目录若有同名文件则优先用它，
# 这样对方可以自己补充规则而不必改程序。
SEMANTIC_FILE = (ROOT / "语义映射.json") if (ROOT / "语义映射.json").is_file() \
    else (RES / "语义映射.json")
# 归属冲突记录：同一张图被不同笔记归给不同画师时留痕，不静默丢弃
CONFLICT_FILE = DATA_DIR / "归属冲突.json"
PORT = 8765
DEFAULT_ACCOUNT = "default"

sys.path.insert(0, str(ROOT))
import 采集引擎 as grab  # noqa: E402

BASE = grab.BASE


def now():
    return time.strftime("%H:%M:%S")


def name_norm(s):
    """
    画师名归一化：全半角统一、去 @、大小写折叠、分隔符统一、去敬称。
    只做形态归一，不做语种转换（汉字不猜罗马字）。
    """
    import re
    import unicodedata
    t = unicodedata.normalize("NFKC", str(s or "")).strip().lstrip("@").casefold()
    t = re.sub(r"[・·．.]+", "_", t)
    t = re.sub(r"[\s_\-]+", "_", t).strip("_")
    for suf in ("老师", "先生", "太太", "大大", "sensei", "です"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


def edit_distance(a, b, cap=3):
    """带早停的编辑距离；长度差过大直接返回大值，避免无谓计算。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match_names(our_names, entry):
    """
    把我们提取的名字与 D 站条目比对，返回判定与证据。

    分层：
      exact  归一后精确命中 name 或 other_names —— 强证据
      near   编辑距离 ≤2 且相似度 ≥0.85 且长度 ≥6 —— 疑似，需人工确认
      none   都没命中

    短名（<6 字符）不做近似匹配：LOOM 会误配到 L◇◆M 这类形近串。
    """
    pool = [(name_norm(entry.get("name")), "name", entry.get("name"))]
    others = entry.get("other_names") or []
    if isinstance(others, str):
        others = others.split()
    for x in others:
        pool.append((name_norm(x), "other_names", str(x)))

    hits, nears = [], []
    for nm in our_names:
        k = name_norm(nm)
        if not k:
            continue
        exact = [p for p in pool if p[0] and p[0] == k]
        if exact:
            hits.append({"ours": nm, "field": exact[0][1], "theirs": exact[0][2]})
            continue
        if len(k) < 6:
            continue
        best = None
        for p in pool:
            if not p[0] or len(p[0]) < 6:
                continue
            d = edit_distance(k, p[0])
            if best is None or d < best[0]:
                best = (d, p)
        if best and best[0] <= 2:
            ratio = 1 - best[0] / max(len(k), len(best[1][0]))
            if ratio >= 0.85:
                nears.append({"ours": nm, "theirs": best[1][2],
                              "distance": best[0], "similarity": round(ratio, 3)})

    if hits:
        verdict = "exact"
    elif nears:
        verdict = "near"
    else:
        verdict = "none"
    return {"verdict": verdict, "hits": hits, "nears": nears,
            "entry_name": entry.get("name", ""),
            "entry_id": str(entry.get("id") or ""),
            "other_count": len(others)}


class Danbooru:
    """
    Danbooru 官方接口（只读）。

    安全边界：
      - 凭证只写本机 d站凭证.json，绝不打印到日志、不回传前端明文
      - 只发 GET；不提供任何写入、投票、评论、上传能力
      - 出错信息里剔除凭证，避免异常堆栈把它带进日志
    """

    HOST = "https://danbooru.donmai.us"

    def __init__(self):
        self.lock = threading.Lock()
        self._login = ""
        self._key = ""
        self.last_error = ""
        self._load()

    def _load(self):
        if not CRED_FILE.is_file():
            return
        try:
            d = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            self._login = str(d.get("login") or "").strip()
            self._key = str(d.get("api_key") or "").strip()
        except Exception:
            self._login, self._key = "", ""

    def configured(self):
        with self.lock:
            return bool(self._login and self._key)

    def masked(self):
        """给前端看的脱敏信息：只露账号名与 key 长度。"""
        with self.lock:
            if not (self._login and self._key):
                return {"configured": False, "login": "", "key_len": 0}
            return {"configured": True, "login": self._login,
                    "key_len": len(self._key)}

    def save(self, login, key):
        login = str(login or "").strip()
        key = str(key or "").strip()
        if not login or not key:
            return False, "账号名和 API Key 都要填"
        tmp = CRED_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"login": login, "api_key": key},
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, CRED_FILE)
        except OSError as e:
            return False, f"保存失败：{e}"
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        with self.lock:
            self._login, self._key = login, key
        return True, ""

    def clear(self):
        with self.lock:
            self._login, self._key = "", ""
        if CRED_FILE.is_file():
            try:
                CRED_FILE.unlink()
            except OSError as e:
                return False, f"删除失败：{e}"
        return True, ""

    def _scrub(self, msg):
        """把凭证从错误信息里抹掉，防止随堆栈进日志。"""
        s = str(msg)
        with self.lock:
            for secret in (self._key, self._login):
                if secret:
                    s = s.replace(secret, "***")
        return s

    def get(self, path, params=None, timeout=20):
        """
        只读 GET。返回 (data, error)。
        error 为 None 表示成功；否则是脱敏后的原因说明。
        """
        import base64
        import urllib.error
        import urllib.parse
        import urllib.request

        with self.lock:
            login, key = self._login, self._key
        if not (login and key):
            return None, "尚未配置 API 凭证"

        url = self.HOST + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        token = base64.b64encode(f"{login}:{key}".encode()).decode()
        req = urllib.request.Request(url, headers={
            "Authorization": "Basic " + token,
            "User-Agent": "ArtistWorkbench/1.0 (readonly artist lookup)",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
            if "json" not in ctype.lower():
                head = raw[:120].decode("utf-8", "replace").lower()
                if "cloudflare" in head or "just a moment" in head or "<html" in head:
                    return None, "被人机验证页拦下（Cloudflare），凭证未能通过"
                return None, f"返回的不是 JSON（{ctype or '未知类型'}）"
            return json.loads(raw), None
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return None, "凭证被拒（401）：账号名或 API Key 不对"
            if e.code == 403:
                return None, "被拒绝（403）：可能被人机验证拦下，或该接口无权限"
            if e.code == 404:
                return None, "查不到该条目（404）"
            if e.code == 429:
                return None, "触发限流（429），稍后再试"
            return None, self._scrub(f"HTTP {e.code}")
        except Exception as e:
            return None, self._scrub(f"{type(e).__name__}: {e}")

    def search(self, name, limit=8, fuzzy=False):
        """
        按名字检索画师条目（any_name_matches 同时匹配本名与别名）。
        fuzzy=True 时用通配包裹，用于错拼名字的兜底候选召回。
        """
        q = str(name or "").strip().lstrip("@")
        if not q:
            return [], "名字为空"
        # 模糊召回需要更大容量：按创建时间排序时，目标可能被挤出前 20
        lim = max(1, min(int(limit), 100 if fuzzy else 20))
        if not fuzzy:
            data, err = self.get("/artists.json", {
                "search[any_name_matches]": q,
                "search[order]": "created_at", "limit": lim})
            if err:
                return [], err
            if not isinstance(data, list):
                return [], "返回结构不符合预期"
            return data, None

        # 模糊召回：错拼可能出现在词中间（zhibu-i-iloom），
        # 单一前缀通配救不了，改用多个子串片段分别召回后合并。
        import re
        core = "".join(re.findall(r"[A-Za-z0-9]+", q)).lower()
        frags = []
        if len(core) >= 4:
            # 头段、尾段、中段各取一次，覆盖不同位置的拼写错误
            frags.append(core[:4] + "*")
            frags.append("*" + core[-4:])
            if len(core) >= 8:
                mid = len(core) // 2
                frags.append("*" + core[mid - 2:mid + 2] + "*")
        else:
            frags.append("*" + core + "*")

        out, seen, errs = [], set(), []
        for f in frags:
            data, err = self.get("/artists.json", {
                "search[any_name_matches]": f,
                "search[order]": "created_at", "limit": lim})
            if err:
                # 单个片段失败不影响其余片段：瞬时波动不该让整次核验失败
                errs.append(err)
                continue
            if not isinstance(data, list):
                continue
            for r in data:
                rid = str(r.get("id") or "")
                if rid and rid not in seen:
                    seen.add(rid)
                    out.append(r)
        # 只有全部片段都失败才算失败
        if not out and errs and len(errs) == len(frags):
            return [], errs[0]
        return out, None

    def verify(self, name, aliases=None):
        """
        核验一个画师名：先按本名检索，再按别名检索，汇总判定。
        返回结论 + 候选条目，供人工确认；不自动合并任何数据。
        """
        names = [name] + [a for a in (aliases or []) if a]
        tried, entries, errors = [], [], []
        seen_ids = set()
        for nm in names:
            q = str(nm or "").strip().lstrip("@")
            if not q or q in tried:
                continue
            tried.append(q)
            rows, err = self.search(q)
            if err:
                errors.append({"query": q, "error": err})
                continue
            for r in rows:
                rid = str(r.get("id") or "")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    entries.append(r)

        # 精确检索零召回时，用通配兜底：错拼的名字（如 Zhibuiiloom）
        # 精确搜不到，但模糊召回后能靠编辑距离认出真实条目。
        used_fuzzy = False
        if not entries and not errors:
            for nm in names:
                q = str(nm or "").strip().lstrip("@")
                if not q:
                    continue
                rows, err = self.search(q, limit=100, fuzzy=True)
                if err:
                    errors.append({"query": q + "(模糊)", "error": err})
                    continue
                used_fuzzy = True
                for r in rows:
                    rid = str(r.get("id") or "")
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        entries.append(r)
                if entries:
                    break

        if not entries:
            return {"verdict": "none" if not errors else "error",
                    "queries": tried, "errors": errors, "candidates": [],
                    "fuzzy": used_fuzzy,
                    "message": ("检索无结果：可能名字提取有误，或该画师未被 D 站收录"
                                if not errors else "检索失败")}

        scored = []
        for e in entries:
            m = match_names(names, e)
            # 主名命中（条目 name 正好是我们的名字）是强证据；
            # 只在 other_names 里出现是弱证据，多个同名时不足以定案。
            primary = any(h.get("field") == "name" for h in m.get("hits", []))
            scored.append({
                "id": str(e.get("id") or ""),
                "name": e.get("name", ""),
                "other_names": e.get("other_names") or [],
                "is_deleted": bool(e.get("is_deleted")),
                "is_banned": bool(e.get("is_banned")),
                "url": f"{self.HOST}/artists/{e.get('id')}",
                "match": m, "primary": primary,
            })
        rank = {"exact": 0, "near": 1, "none": 2}
        # 同等级内：主名命中排在前，其余保持检索顺序
        scored.sort(key=lambda x: (rank.get(x["match"]["verdict"], 3),
                                   not x["primary"]))
        exact = [x for x in scored if x["match"]["verdict"] == "exact"]
        prim = [x for x in exact if x["primary"]]

        # 唯一性闸门：搜到名字不等于就是本人。
        #   恰好 1 个精确命中          → 可信
        #   多个精确命中但主名唯一      → 主名是强证据，可信
        #   多个精确命中且主名不唯一    → 待消歧，绝不随手取第一个
        if len(exact) == 1:
            best = "exact"
        elif len(exact) > 1:
            if len(prim) == 1:
                best = "exact"
                # 把唯一主名提到最前，确保 top 是它而非建档最早的
                one = prim[0]
                scored = [one] + [x for x in scored if x is not one]
            else:
                best = "ambiguous"
        else:
            best = scored[0]["match"]["verdict"] if scored else "none"

        msg = {"exact": "在 D 站找到匹配的画师条目",
               "ambiguous": (f"D 站有 {len(exact)} 个同名条目，无法确定是本人，"
                             f"需你点选；已列出全部候选，不会自动直连"),
               "near": "找到高度相似的条目，可能是拼写差异，需你确认",
               "none": "检索到条目但名字都不匹配，需你确认"}[best]
        if used_fuzzy and best not in ("none", "ambiguous"):
            msg += "（精确检索无果，经模糊召回后比对得出）"
        # 待消歧时返回全部候选，供界面逐个列出让你选
        keep = scored if best == "ambiguous" else scored[:8]
        return {"verdict": best, "queries": tried, "errors": errors,
                "fuzzy": used_fuzzy, "candidates": keep, "message": msg}

    def urls_of(self, artist_id, limit=40):
        """取某条目登记的社交账号链接（只读）。"""
        rows, err = self.get("/artist_urls.json",
                             {"search[artist_id]": str(artist_id),
                              "limit": int(limit)})
        if err or not isinstance(rows, list):
            return []
        return rows

    def who_by_handle(self, handle):
        """
        用社交账号反查画师身份 —— 这是比名字更硬的证据。

        D 站为每位画师登记了 X/pixiv/instagram 等账号链接。
        账号是唯一的：x.com/asikumin 只可能属于一个人，
        而名字会重名、会错拼。据此可自动定案，无需人工过目。

        返回 [(artist_id, url, is_active), ...]
        """
        h = str(handle or "").strip().lstrip("@").lower()
        # 只保留账号里可能出现的字符，避免通配符注入
        h = "".join(c for c in h if c.isalnum() or c in "_.-")
        if len(h) < 4:
            return []
        rows, err = self.get("/artist_urls.json",
                             {"search[url_matches]": "*" + h + "*",
                              "limit": 40})
        if err or not isinstance(rows, list):
            return []
        out = []
        for x in rows:
            u = str(x.get("url") or "")
            # 必须是账号位精确等于 handle，而不是子串蹭到
            # （asikumin 不能匹配 asikumin123 这类别人的账号）
            tail = u.rstrip("/").split("/")[-1].lower()
            if tail != h:
                continue
            aid = str(x.get("artist_id") or "")
            if aid:
                out.append((aid, u, bool(x.get("is_active"))))
        return out

    def probe(self, artist_id="149913"):
        """连通性自检：只查一个画师条目，验证凭证与通道是否可用。"""
        data, err = self.get(f"/artists/{artist_id}.json")
        if err:
            return {"ok": False, "error": err, "artist_id": artist_id}
        if not isinstance(data, dict) or not data.get("name"):
            return {"ok": False, "error": "返回结构不符合预期", "artist_id": artist_id}
        # 该接口不返回 post_count，改为如实给出条目自带的字段
        others = data.get("other_names") or []
        if isinstance(others, str):
            others = others.split()
        return {
            "ok": True,
            "artist_id": str(data.get("id") or artist_id),
            "name": data.get("name", ""),
            "other_names": [str(x) for x in others],
            "other_count": len(others),
            "group_name": data.get("group_name") or "",
            "is_deleted": bool(data.get("is_deleted")),
            "is_banned": bool(data.get("is_banned")),
            "url": f"{self.HOST}/artists/{data.get('id') or artist_id}",
        }


DANBOORU = Danbooru()


class SauceNao:
    """
    SauceNAO 搜图（只读兜底）。

    仅在 D 站搜不到、或搜到的对应不上时才启用：
    用作品图反查作者，比名字比对更硬。

    安全边界与 D 站凭证一致：
      - key 只写本机 搜图凭证.json，绝不打印日志、不回传前端明文
      - 出错信息里剔除 key
      - 默认不发起任何请求；未配置时直接拒绝
    """

    HOST = "https://saucenao.com/search.php"
    # 能定位到作者的库：9=Danbooru 5=Pixiv 41=Twitter 34=deviantArt
    # 12= MangaDex 之类无作者信息的库不参与判定
    AUTHOR_DBS = {9: "Danbooru", 5: "Pixiv", 41: "Twitter",
                  34: "deviantArt", 25: "ArtStation", 21: "AniDB"}

    def __init__(self):
        self.lock = threading.Lock()
        self._key = ""
        self.last_error = ""
        # 额度：免费账号有 30 秒与每日双重限制，这里主动节流
        self._calls = []          # 最近调用时间戳
        self._day = ""            # 当日日期
        self._day_used = 0
        self.daily_cap = 140      # 留出余量，避免撞上限
        self.short_cap = 3        # 每 30 秒最多 3 次
        self._load()

    def _load(self):
        if not SAUCE_FILE.is_file():
            return
        try:
            d = json.loads(SAUCE_FILE.read_text(encoding="utf-8"))
            self._key = str(d.get("api_key") or "").strip()
        except Exception:
            self._key = ""

    def configured(self):
        with self.lock:
            return bool(self._key)

    def masked(self):
        with self.lock:
            if not self._key:
                return {"configured": False, "key_len": 0}
            return {"configured": True, "key_len": len(self._key)}

    def save(self, key):
        key = str(key or "").strip()
        if not key:
            return False, "请填写 API Key"
        if len(key) < 20:
            return False, "API Key 看起来太短，请检查是否复制完整"
        tmp = SAUCE_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"api_key": key},
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, SAUCE_FILE)
        except OSError as e:
            return False, f"保存失败：{e}"
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        with self.lock:
            self._key = key
        return True, ""

    def clear(self):
        with self.lock:
            self._key = ""
        if SAUCE_FILE.is_file():
            try:
                SAUCE_FILE.unlink()
            except OSError as e:
                return False, f"删除失败：{e}"
        return True, ""

    def _scrub(self, msg):
        s = str(msg)
        with self.lock:
            if self._key:
                s = s.replace(self._key, "***")
        return s

    def quota(self):
        """当前额度余量（仅本机计数，供界面显示）。"""
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            if self._day != today:
                self._day, self._day_used = today, 0
            now = time.time()
            recent = len([t for t in self._calls if now - t < 30])
            return {"day_used": self._day_used, "daily_cap": self.daily_cap,
                    "short_used": recent, "short_cap": self.short_cap}

    def _throttle(self):
        """
        主动限流：超额时返回等待秒数，不硬闯。
        免费额度有限，宁可慢一点也不要被封。
        """
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            if self._day != today:
                self._day, self._day_used = today, 0
            if self._day_used >= self.daily_cap:
                return -1, "今日搜图额度已用完，明天再试"
            now = time.time()
            self._calls = [t for t in self._calls if now - t < 30]
            if len(self._calls) >= self.short_cap:
                wait = 30 - (now - self._calls[0]) + 0.5
                return max(0.5, wait), ""
            self._calls.append(now)
            self._day_used += 1
        return 0, ""

    def search(self, image_url, numres=6, minsim=80, timeout=30):
        """
        用图片链接反查来源（只读）。返回 (results, error)。

        只传公开图床链接，不上传本机文件。
        相似度低于 minsim 的结果直接丢掉——同画风也会高分，
        低分结果不足以判定身份。
        """
        import urllib.error
        import urllib.parse
        import urllib.request

        with self.lock:
            key = self._key
        if not key:
            return [], "尚未配置搜图 API Key"
        u = str(image_url or "").strip()
        if not u.startswith("http"):
            return [], "图片链接无效"

        wait, err = self._throttle()
        if err:
            return [], err
        if wait > 0:
            time.sleep(min(wait, 31))

        params = {
            "api_key": key, "output_type": 2, "numres": int(numres),
            "db": 999, "url": u, "minsim": int(minsim),
            "hide": 1,          # 过滤明确不当内容
        }
        data = urllib.parse.urlencode(params).encode()
        # 429 自动退避一次：短窗口限流等一会儿就好，不该整次核验失败
        for attempt in range(2):
            req = urllib.request.Request(self.HOST, data=data, headers={
                "User-Agent": "ArtistWorkbench/1.0 (readonly artist lookup)",
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                    ctype = r.headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    time.sleep(32)
                    continue
                if e.code == 403:
                    return [], "Key 被拒（403）：请检查是否复制完整"
                if e.code == 429:
                    return [], "触发限流（429），稍后再试"
                return [], self._scrub(f"HTTP {e.code}")
            except Exception as e:
                return [], self._scrub(f"{type(e).__name__}: {e}")
        if "json" not in ctype.lower():
            head = raw[:120].decode("utf-8", "replace").lower()
            if "cloudflare" in head or "just a moment" in head:
                return [], "被人机验证页拦下"
            return [], f"返回的不是 JSON（{ctype or '未知'}）"
        d = json.loads(raw)

        hdr = d.get("header") or {}
        if hdr.get("status") not in (None, 0):
            msg = str(hdr.get("message") or "")
            if "limit" in msg.lower() or hdr.get("status") == -2:
                return [], "搜图额度已用尽，稍后再试"
            return [], self._scrub(f"搜图失败：{msg or hdr.get('status')}")

        out = []
        for r in (d.get("results") or []):
            h = r.get("header") or {}
            dat = r.get("data") or {}
            try:
                sim = float(h.get("similarity") or 0)
            except (TypeError, ValueError):
                sim = 0.0
            if sim < minsim:
                continue
            idx = h.get("index_id")
            out.append({
                "similarity": sim,
                "index_id": idx,
                "index_name": str(h.get("index_name") or ""),
                "author": str(dat.get("member_name")
                              or dat.get("author_name")
                              or dat.get("creator") or ""),
                "author_id": str(dat.get("member_id")
                                 or dat.get("author_id") or ""),
                "title": str(dat.get("title") or ""),
                "urls": [str(x) for x in (dat.get("ext_urls") or [])],
                "source": str(dat.get("source") or ""),
                "thumbnail": str(h.get("thumbnail") or ""),
            })
        out.sort(key=lambda x: -x["similarity"])
        return out, None

    def probe(self, image_url=""):
        """
        连通性自检：拿一张图试搜，验证 key 与通道可用。
        testmode 不消耗额度，但这里要验证真实通路，故正常搜一次。
        """
        u = str(image_url or "").strip()
        if not u.startswith("http"):
            return {"ok": False, "error": "请提供一张作品图的链接用于测试"}
        rows, err = self.search(u, numres=3, minsim=60)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "results": len(rows),
                "top": rows[0] if rows else None,
                "quota": self.quota()}


SAUCENAO = SauceNao()


class Accounts:
    """
    多账号管理：每个账号一套独立的浏览器登录目录，互不干扰。
    退出登录只清空该账号的登录态目录，采集到的画师与图片一律不动。
    """

    def __init__(self):
        self.lock = threading.Lock()
        ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
        self.meta = {"current": DEFAULT_ACCOUNT, "items": {}}
        self._load()

    def _load(self):
        if ACCOUNTS_FILE.is_file():
            try:
                d = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
                if isinstance(d, dict) and d.get("items"):
                    self.meta = d
            except Exception:
                pass
        # 旧版单账号目录无缝纳入，用户不用重新登录
        if DEFAULT_ACCOUNT not in self.meta["items"]:
            self.meta["items"][DEFAULT_ACCOUNT] = {
                "label": "默认账号",
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "legacy": True,
            }
        if self.meta.get("current") not in self.meta["items"]:
            self.meta["current"] = DEFAULT_ACCOUNT
        self._save()

    def _save(self):
        tmp = ACCOUNTS_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, ACCOUNTS_FILE)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def profile_dir(self, aid=None):
        aid = aid or self.meta["current"]
        if aid == DEFAULT_ACCOUNT:
            return PROFILE
        return ACCOUNTS_DIR / aid

    def current(self):
        with self.lock:
            return self.meta["current"]

    def label(self, aid=None):
        with self.lock:
            aid = aid or self.meta["current"]
            it = self.meta["items"].get(aid) or {}
            return it.get("label") or aid

    def list(self):
        with self.lock:
            cur = self.meta["current"]
            out = []
            for aid, it in self.meta["items"].items():
                d = self.profile_dir(aid)
                out.append({
                    "id": aid,
                    "label": it.get("label") or aid,
                    "current": aid == cur,
                    "has_state": d.is_dir() and any(d.iterdir()),
                    "created": it.get("created", ""),
                })
            out.sort(key=lambda x: (not x["current"], x["created"]))
            return out

    def add(self, label=""):
        with self.lock:
            # 时间戳 + 随机后缀 + 冲突重试：同毫秒连续创建也不会撞 ID
            import secrets
            for _ in range(50):
                aid = ("acc" + str(int(time.time() * 1000))[-9:]
                       + secrets.token_hex(2))
                if aid not in self.meta["items"]:
                    break
            else:
                aid = "acc" + secrets.token_hex(8)
            label = (label or "").strip() or f"账号 {len(self.meta['items']) + 1}"
            self.meta["items"][aid] = {
                "label": label[:24],
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.meta["current"] = aid
            self._save()
            self.profile_dir(aid).mkdir(parents=True, exist_ok=True)
            return aid

    def switch(self, aid):
        with self.lock:
            if aid not in self.meta["items"]:
                return False, "找不到这个账号"
            self.meta["current"] = aid
            self._save()
            return True, ""

    def rename(self, aid, label):
        label = (label or "").strip()
        if not label:
            return False, "名称不能为空"
        with self.lock:
            if aid not in self.meta["items"]:
                return False, "找不到这个账号"
            self.meta["items"][aid]["label"] = label[:24]
            self._save()
            return True, ""

    def logout(self, aid):
        """退出登录：清掉该账号的浏览器登录目录，不碰采集数据。"""
        with self.lock:
            if aid not in self.meta["items"]:
                return False, "找不到这个账号"
            d = self.profile_dir(aid)
        if d.is_dir():
            try:
                shutil.rmtree(d)
            except OSError as e:
                return False, f"清除登录态失败：{e}"
        return True, ""

    def remove(self, aid):
        """删除账号条目（同时清登录态）。默认账号保留，避免无账号可用。"""
        with self.lock:
            if aid not in self.meta["items"]:
                return False, "找不到这个账号"
            if aid == DEFAULT_ACCOUNT:
                return False, "默认账号不能删除，可以退出它的登录"
            d = self.profile_dir(aid)
            self.meta["items"].pop(aid)
            if self.meta["current"] == aid:
                self.meta["current"] = DEFAULT_ACCOUNT
            self._save()
        if d.is_dir():
            try:
                shutil.rmtree(d)
            except OSError:
                pass
        return True, ""


ACCOUNTS = Accounts()


def now_ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()
        self.save_local = False   # 默认在线图廊：只存图床链接，不下载
        # 单画师作品上限：同一人被多篇推荐会无限累积，必须有闸
        self.max_per_artist = 30
        self._pal_cache = {}      # 图片稳定键 -> 主色调
        self.logs = []
        self.phase = "idle"          # idle / login / collecting
        self.logged_in = None
        self.progress = 0
        self.total = 0
        self.stop_flag = False
        self.artists = {}            # name -> record
        self.notes_done = 0
        self.keyword = ""
        self._sauce_cache = {}       # 图稳定键 -> {hits:[{tag,sim,post}]}
        self._sauce_ledger = {}      # 画师uid -> 累计搜过的图（含内容指纹）
        self._phash_cache = {}       # 图稳定键 -> 感知哈希，避免重复下载
        self._sem = {"generic": {}, "rename": {}, "aliases": {}}
        self._conflicts = []         # 归属冲突：同图被不同笔记归给不同画师
        self._load_conflicts()
        self._load_sauce_cache()
        self._load_sauce_ledger()
        self._load_semantic()
        self._load()

    # ---------- 归属冲突 ----------
    def _load_conflicts(self):
        if CONFLICT_FILE.is_file():
            try:
                d = json.loads(CONFLICT_FILE.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    self._conflicts = [x for x in d if isinstance(x, dict)]
            except Exception:
                self._conflicts = []

    def _save_conflicts(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFLICT_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._conflicts, ensure_ascii=False,
                                      indent=1), encoding="utf-8")
            os.replace(tmp, CONFLICT_FILE)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def record_conflict(self, src_key, image_url, want_artist, note_url,
                        note_title, held_by):
        """
        记录一次归属冲突：这张图已经归在 held_by 名下，
        但本篇笔记认为它属于 want_artist。

        不自动裁决（可能是转载/合作/其中一篇搞错，需要人判断），
        但绝不允许静默——否则后到的画师会凭空消失。
        """
        for c in self._conflicts:
            if c.get("key") == src_key and c.get("want") == want_artist:
                return False
        self._conflicts.append({
            "key": src_key, "url": image_url, "want": want_artist,
            "held_by": held_by, "note_url": note_url,
            "note_title": note_title, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if len(self._conflicts) > 500:
            self._conflicts = self._conflicts[-500:]
        self._save_conflicts()
        return True

    # ---------- 搜图缓存 ----------
    def _load_sauce_cache(self):
        if SAUCE_CACHE_FILE.is_file():
            try:
                d = json.loads(SAUCE_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self._sauce_cache = d
            except Exception:
                self._sauce_cache = {}

    def _save_sauce_cache(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SAUCE_CACHE_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._sauce_cache, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, SAUCE_CACHE_FILE)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ---------- 搜图额度台账 ----------
    # 结构：{画师uid: {"used": [{"key":..., "phash":..., "at":...}]}}
    # 按 uid 而非名字记账：改名后额度不会被重置，杜绝「改个名再搜两张」。
    def _load_sauce_ledger(self):
        if SAUCE_LEDGER_FILE.is_file():
            try:
                d = json.loads(SAUCE_LEDGER_FILE.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self._sauce_ledger = d
            except Exception:
                self._sauce_ledger = {}

    def _save_sauce_ledger(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SAUCE_LEDGER_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._sauce_ledger, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, SAUCE_LEDGER_FILE)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def sauce_used(self, uid):
        """该画师累计已搜过的图（含内容指纹），跨轮次累计。"""
        rec = self._sauce_ledger.get(uid) or {}
        return list(rec.get("used") or [])

    def sauce_left(self, uid):
        """该画师还剩几次搜图额度。"""
        return max(0, self.SAUCE_MAX_IMGS - len(self.sauce_used(uid)))

    def _sauce_charge(self, uid, key, ph):
        """记一次实际发生的搜图消耗。"""
        rec = self._sauce_ledger.setdefault(uid, {"used": []})
        rec.setdefault("used", []).append(
            {"key": key, "phash": ph, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._save_sauce_ledger()

    # ---------- 数据 ----------
    def _migrate_alias_tiers(self, a):
        """
        给存量别名定证据等级。

        全部按弱级处理会引入回归：日后笔记用别名提到该画师时，
        系统认不出是同一人，会新建一条重复记录。所以按证据分级——
        D 站核验命中过的别名是权威级，语义映射确认过的是人工级，
        其余存量别名都源自历史采集时帖子明示的账号（X：@xxx、
        推特：xxx、括号内账号），归入帖内明示级，仍可认人。
        """
        src = a.setdefault("alias_src", {})
        v = a.get("verify") or {}
        # D 站核验命中过的名字（本名或别名）→ 权威级
        for h in v.get("hits") or []:
            ours = h.get("ours")
            if ours and self.name_key(ours) != self.name_key(a["name"]):
                k = self.name_key(ours)
                if int(src.get(k, 9)) > self.ALIAS_TIER_D:
                    src[k] = self.ALIAS_TIER_D
        # 账号铁证认定的 handle → 账号登记级
        for p in v.get("proof") or []:
            h = p.get("handle")
            if h and self.name_key(h) != self.name_key(a["name"]):
                k = self.name_key(h)
                if int(src.get(k, 9)) > self.ALIAS_TIER_URL:
                    src[k] = self.ALIAS_TIER_URL
        for al in a.get("aliases", []):
            k = self.name_key(al)
            if k in src:
                continue
            if al in self.semantic_aliases(a["name"]):
                src[k] = self.ALIAS_TIER_HUMAN   # 人工通篇读帖确认过
            else:
                src[k] = self.ALIAS_TIER_POST    # 历史采集的明示账号，可认人

    def _load(self):
        if DATA_FILE.exists():
            upgraded = 0
            cleaned = 0
            filled = 0
            migrated = 0
            try:
                d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                for a in d.get("artists", []):
                    a.setdefault("aliases", [])
                    a.setdefault("styles", [])
                    a.setdefault("notes", [])
                    a.setdefault("images", [])
                    a.setdefault("alias_src", {})
                    # 迁移：老数据没有 uid，补一个不可变身份标识
                    if not a.get("uid"):
                        a["uid"] = self.new_uid()
                        migrated += 1
                    self._migrate_alias_tiers(a)
                    # 历史遗留：占位名被收作别名会让无归属图持续倒进这位画师
                    keep = [x for x in a["aliases"]
                            if not self.is_placeholder(x)
                            and not self.is_generic_word(x)]
                    if len(keep) != len(a["aliases"]):
                        cleaned += 1
                        a["aliases"] = keep
                    # 回填语义映射里的别名：正文给出过但规则层漏掉的账号/异写，
                    # 补齐后 D 站核验命中率显著提高
                    for al in self.semantic_aliases(a["name"]):
                        if (self.name_key(al) != self.name_key(a["name"])
                                and not any(self.name_key(al) == self.name_key(x)
                                            for x in a["aliases"])):
                            a["aliases"].append(al)
                            filled += 1
                    # 旧清单里的签名链接会过期，加载时就换成永久链接
                    for im in a["images"]:
                        if grab.normalize_image(im):
                            upgraded += 1
                    # 历史数据里可能已有同人多条，加载时按身份归并
                    exist = self.resolve(a["name"])
                    if exist:
                        self._merge_into(exist, a)
                    else:
                        self.artists[a["name"]] = a
                self.keyword = d.get("keyword", "")
                self.notes_done = d.get("notes_done", 0)
                # 迁移只做检测，不自动合并：同一 uid 或同一名字出现在
                # 两条记录上是数据异常，报出来由人决定，不替用户选。
                self._conflict_report = self._detect_identity_conflicts()
            except Exception:
                pass
            if upgraded or cleaned or filled or migrated:
                # 立刻落盘，避免下次启动又走一遍转换
                try:
                    self.save()
                    if migrated:
                        self.log(f"已为 {migrated} 位画师建立不可变身份标识（uid）")
                    if upgraded:
                        self.log(f"已把 {upgraded} 张图的临时链接换成永久链接")
                    if cleaned:
                        self.log(f"已清除 {cleaned} 位画师名下的占位/通用词别名，"
                                 "无归属图片不会再被误判给他们")
                    if filled:
                        self.log(f"已按语义映射回填 {filled} 条别名，"
                                 "D 站核验命中率随之提高")
                    if getattr(self, "_conflict_report", None):
                        self.log("⚠ 检测到身份冲突（未自动处理，需你确认）：")
                        for c in self._conflict_report[:6]:
                            self.log(f"   {c}")
                except Exception:
                    pass

    def _detect_identity_conflicts(self):
        """
        检测身份冲突：同一 uid 或同一强别名被两条以上记录持有。
        只报告不合并——合并需要证据，猜错会永久污染数据。
        """
        out = []
        seen_uid, seen_alias = {}, {}
        for nm, rec in self.artists.items():
            uid = rec.get("uid")
            if uid:
                if uid in seen_uid:
                    out.append(f"uid {uid} 同时属于「{seen_uid[uid]}」与「{nm}」")
                else:
                    seen_uid[uid] = nm
            for al in self.strong_aliases(rec):
                k = self.name_key(al)
                if k in seen_alias and seen_alias[k] != nm:
                    out.append(f"别名「{al}」同时属于「{seen_alias[k]}」与「{nm}」")
                else:
                    seen_alias.setdefault(k, nm)
        return out

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "keyword": self.keyword,
            "notes_done": self.notes_done,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "artists": sorted(self.artists.values(),
                              key=lambda a: -len(a.get("images", []))),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # 原子替换 + 独立写锁：并发保存不会互相抢占同一临时文件
        with self._save_lock:
            tmp = DATA_FILE.with_name(f"data.{threading.get_ident()}.tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
                for attempt in range(6):
                    try:
                        os.replace(tmp, DATA_FILE)
                        break
                    except PermissionError:
                        if attempt == 5:
                            raise
                        time.sleep(0.08 * (attempt + 1))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    def log(self, msg):
        msg = str(msg).rstrip()
        if not msg:
            return
        with self.lock:
            self.logs.append(f"[{now()}] {msg}")
            if len(self.logs) > 400:
                self.logs = self.logs[-400:]
        print(msg, flush=True)

    def state(self):
        with self.lock:
            return {
                "phase": self.phase,
                "logged_in": self.logged_in,
                "progress": self.progress,
                "total": self.total,
                "logs": self.logs[-120:],
                "notes_done": self.notes_done,
                "keyword": self.keyword,
                "artist_count": len(self.artists),
                "image_count": sum(len(a.get("images", [])) for a in self.artists.values()),
                "account": ACCOUNTS.current(),
                "account_label": ACCOUNTS.label(),
                "accounts": ACCOUNTS.list(),
                "d_configured": DANBOORU.configured(),
                "v_progress": getattr(self, "v_progress", 0),
                "v_total": getattr(self, "v_total", 0),
                "verify_stat": self._verify_stat(),
                "same_id": self._same_id_groups(),
                # 归属冲突：同一张图被不同笔记归给不同画师（风险A 可见化）
                "conflicts": list(self._conflicts),
                # 身份冲突：迁移检测出的 uid/别名重复（只报告，不自动处理）
                "identity_conflicts": list(getattr(self, "_conflict_report", [])),
            }

    def _same_id_groups(self):
        """核验到同一 D 站条目的画师 = 同一人被拆成多条，供一键合并。"""
        groups = {}
        for nm, rec in self.artists.items():
            vid = str((rec.get("verify") or {}).get("id") or "")
            if vid:
                groups.setdefault(vid, []).append(nm)
        return [{"id": vid, "names": sorted(nms)}
                for vid, nms in groups.items() if len(nms) >= 2]

    def _verify_stat(self):
        """各核验状态的画师数量（调用方需持锁）。"""
        st = {"matched": 0, "confirmed": 0, "suspect": 0,
              "missing": 0, "absent": 0, "error": 0, "none": 0}
        for rec in self.artists.values():
            s = (rec.get("verify") or {}).get("state") or "none"
            st[s] = st.get(s, 0) + 1
        return st

    def palette(self, name):
        """
        取该画师代表作的主色调。浏览器受跨域限制读不到像素，
        故在服务端取色：优先用本地备份，否则临时拉一张小图。
        """
        key = self.name_key(name)
        with self.lock:
            canonical = self.resolve(name)
            rec = self.artists.get(canonical) if canonical else None
            if not rec or not rec.get("images"):
                return {"colors": []}
            im = rec["images"][0]
            ck = im.get("key") or grab.image_key(im.get("src", ""))
            if ck in self._pal_cache:
                return {"colors": self._pal_cache[ck]}
            local = im.get("file") or ""
            src = im.get("src") or ""

        data = None
        if local:
            f = (ROOT / local).resolve()
            if f.is_relative_to(ROOT.resolve()) and f.is_file():
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
        if data is None and src:
            try:
                import urllib.request
                req = urllib.request.Request(
                    src, headers={"User-Agent": grab.UA})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
            except Exception:
                data = None
        if not data:
            return {"colors": []}

        cols = grab.dominant_colors(data)
        with self.lock:
            self._pal_cache[ck] = cols
        return {"colors": cols}

    def data(self):
        with self.lock:
            out = []
            for a in sorted(self.artists.values(),
                            key=lambda x: -len(x.get("images", []))):
                rec = dict(a)
                v = a.get("verify") or {}
                # 只有拿到可信条目才直连：confirmed 是你确认过的，
                # matched 是本名/别名精确命中且带证据的。
                # id 为空（疑似/未找到/模糊召回）一律退回检索页，不指向任何人。
                if v.get("id") and v.get("state") in ("confirmed", "matched"):
                    rec["d_url"] = f"{DANBOORU.HOST}/artists/{v['id']}"
                    rec["d_direct"] = True
                else:
                    rec["d_url"] = grab.danbooru_url(a["name"], a.get("aliases"))
                    rec["d_direct"] = False
                rec["d_query"] = grab.danbooru_query(a["name"])
                rec["d_alt_url"] = grab.danbooru_alt_url(a["name"], a.get("aliases"))
                rec["d_tag"] = grab.danbooru_tag(a["name"], a.get("aliases"))
                rec["d_posts_url"] = grab.danbooru_posts_url(a["name"], a.get("aliases"))
                out.append(rec)
            return out

    # ---------- D 站核验 ----------
    def _prove_by_handle(self, name, aliases, cands):
        """
        用社交账号铁证自动定案，免人工过目。

        两条路径：
          A 名字本身就是账号 —— 拿它反查账号库，命中唯一条目即定案。
            asikumin 就是这样找到真身 dayama(162830)，而非形近的 asikusa。
          B 候选条目登记的账号里，有与我们的名字/别名同名的 ——
            Zhibuiiloom 拼错了，但 x.com/Zhibujiloom 登记在 149913，
            且该账号在多个平台重复出现，可判定同一人。

        只有证据唯一且一致才返回结论；有歧义一律不定案。
        """
        ours = [name] + [a for a in (aliases or []) if a]
        keys = {}
        for o in ours:
            k = "".join(c for c in str(o).strip().lstrip("@").lower()
                        if c.isalnum() or c in "_.-")
            if len(k) >= 4:
                keys[k] = o

        # A：名字当账号直接反查
        votes = {}
        for k, orig in keys.items():
            for aid, url, active in DANBOORU.who_by_handle(k):
                votes.setdefault(aid, []).append(
                    {"handle": orig, "url": url, "active": active})
        if len(votes) == 1:
            aid = next(iter(votes))
            entry, err = DANBOORU.get(f"/artists/{aid}.json")
            if not err and isinstance(entry, dict) and entry.get("name"):
                ev = votes[aid]
                return {"entry": {
                    "id": aid, "name": entry.get("name", ""),
                    "other_names": entry.get("other_names") or [],
                    "url": f"{DANBOORU.HOST}/artists/{aid}",
                    "match": {"verdict": "exact", "hits": [], "nears": []}},
                    "proof": ev,
                    "evidence": "账号铁证：" + "、".join(
                        f"{x['handle']} → {x['url']}" for x in ev[:3])}

        # B：候选条目的登记账号中出现我们的名字（容忍错拼：比对账号主干）
        for c in (cands or [])[:5]:
            cid = str(c.get("id") or "")
            if not cid:
                continue
            rows = DANBOORU.urls_of(cid)
            hit = []
            for x in rows:
                u = str(x.get("url") or "")
                tail = u.rstrip("/").split("/")[-1].lower()
                tail = "".join(ch for ch in tail if ch.isalnum())
                if len(tail) < 5:
                    continue
                for k, orig in keys.items():
                    kk = "".join(ch for ch in k if ch.isalnum())
                    if len(kk) < 5:
                        continue
                    # 账号主干与我们的名字高度一致（错拼只差 1-2 字符）
                    if tail == kk or (abs(len(tail) - len(kk)) <= 2
                                      and edit_distance(tail, kk) <= 2):
                        hit.append({"handle": orig, "url": u,
                                    "active": bool(x.get("is_active"))})
            # 同一账号在多平台登记 → 证据更强，可定案
            if len(hit) >= 2:
                entry, err = DANBOORU.get(f"/artists/{cid}.json")
                if err or not isinstance(entry, dict) or not entry.get("name"):
                    continue
                return {"entry": {
                    "id": cid, "name": entry.get("name", ""),
                    "other_names": entry.get("other_names") or [],
                    "url": f"{DANBOORU.HOST}/artists/{cid}",
                    "match": {"verdict": "exact", "hits": [], "nears": []}},
                    "proof": hit,
                    "evidence": f"账号铁证：{len(hit)} 个平台登记同一账号 "
                                + "、".join(x["url"] for x in hit[:3])}
        return None

    def _sauce_hits_for(self, u, minsim):
        """单张图反查 D 站作者标签，返回 [{tag,sim,post}]。"""
        rows, err = SAUCENAO.search(u, numres=6, minsim=minsim)
        if err:
            return None, err
        hits = []
        for r in rows:
            pid = ""
            for x in r.get("urls") or []:
                mm = re.search(
                    r"danbooru\.donmai\.us/(?:posts|post/show)/(\d+)", x)
                if mm:
                    pid = mm.group(1)
                    break
            if not pid:
                continue
            post, e2 = DANBOORU.get(f"/posts/{pid}.json")
            if e2 or not isinstance(post, dict):
                continue
            tag = str(post.get("tag_string_artist") or "").strip()
            if not tag or " " in tag:
                continue   # 多作者合作帖不能用来定身份
            hits.append({"tag": tag, "sim": r["similarity"], "post": pid})
        return hits, None

    # 单位画师最多搜 2 张：搜图只在 D 站定不了案时兜底，不是常规手段。
    SAUCE_MAX_IMGS = 2

    def _image_phash(self, im):
        """
        取一张图的内容指纹（感知哈希）。优先本地备份，否则临时下载。
        结果按图稳定键缓存，同一张图只算一次。
        取不到时返回空串——调用方退回 URL 级去重，不阻断搜图。
        """
        u = str(im.get("src") or "")
        key = im.get("key") or grab.image_key(u)
        if key in self._phash_cache:
            return self._phash_cache[key]
        data = None
        local = im.get("file") or ""
        if local:
            f = (ROOT / local).resolve()
            try:
                if f.is_relative_to(ROOT.resolve()) and f.is_file():
                    data = f.read_bytes()
            except OSError:
                data = None
        if data is None and u.startswith("http"):
            try:
                import urllib.request
                req = urllib.request.Request(
                    u, headers={"User-Agent": grab.UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
            except Exception:
                data = None
        ph = grab.phash(data) if data else ""
        self._phash_cache[key] = ph
        return ph

    def _sauce_votes(self, images, uid=None, minsim=85):
        """
        拿作品图反查 D 站作者标签，返回 {作者标签: [证据...]}。

        额度硬规则（用户明确要求）：
          1 只在 D 站完全搜不到时调用，已命中/待消歧一律不搜；
          2 每位画师**累计**最多 SAUCE_MAX_IMGS 张，跨轮次记账，
            按 uid 记，改名也不会重置额度；
          3 这几张必须是**内容不同的画**：先按图稳定键去重，
            再按感知哈希去重——同一张画被裁切/加水印/重新上传后
            会拿到新图片ID，URL 去重抓不到，只能靠画面指纹；
          4 结果（含「无命中」）永久缓存，搜过的图绝不重试。
        出错时返回 ({}, 错误)。
        """
        if not SAUCENAO.configured():
            return {}, None
        votes = {}
        dirty = False
        used = self.sauce_used(uid) if uid else []
        used_keys = {x.get("key") for x in used}
        used_phs = [x.get("phash") for x in used if x.get("phash")]
        left = max(0, self.SAUCE_MAX_IMGS - len(used)) if uid else self.SAUCE_MAX_IMGS

        # 本轮已搜过的内容指纹，防止同一轮内两张同画各扣一次
        seen_keys = set()
        seen_phs = list(used_phs)
        for im in (images or []):
            u = str(im.get("src") or "")
            if not u.startswith("http"):
                continue
            key = im.get("key") or grab.image_key(u)
            if key in seen_keys or key in used_keys:
                # 同一张图（签名/尺寸变化也算同一张）绝不重复搜
                ent = self._sauce_cache.get(key)
                if ent:
                    for h in ent.get("hits", []):
                        votes.setdefault(h["tag"], []).append(
                            {"sim": h["sim"], "post": h["post"]})
                continue
            ent = self._sauce_cache.get(key)
            if ent is not None:
                # 缓存命中：不消耗额度，但仍要看内容是否与已搜的重复
                seen_keys.add(key)
                for h in ent.get("hits", []):
                    votes.setdefault(h["tag"], []).append(
                        {"sim": h["sim"], "post": h["post"]})
                if ent.get("hits"):
                    break
                continue
            if left <= 0:
                break      # 累计额度用完，绝不再发请求
            # 内容级去重：画面与已搜过的任一张实质相同 → 跳过，不扣额度
            ph = self._image_phash(im)
            if ph and any(grab.same_picture(ph, p) for p in seen_phs):
                seen_keys.add(key)
                continue
            hits, err = self._sauce_hits_for(u, minsim)
            if err:
                return {}, err
            self._sauce_cache[key] = {"hits": hits}
            dirty = True
            seen_keys.add(key)
            if ph:
                seen_phs.append(ph)
            if uid:
                self._sauce_charge(uid, key, ph)
                left -= 1
            for h in hits:
                votes.setdefault(h["tag"], []).append(
                    {"sim": h["sim"], "post": h["post"]})
            if hits:
                break
        if dirty:
            self._save_sauce_cache()
        return votes, None

    def _entry_by_tag(self, tag):
        """按作者标签取唯一同名条目。"""
        rows, err = DANBOORU.get("/artists.json",
                                 {"search[any_name_matches]": tag, "limit": 5})
        if err or not isinstance(rows, list):
            return None
        return next((x for x in rows if x.get("name") == tag), None)

    def _prove_by_sauce(self, name, images, uid=None):
        """
        搜图兜底：名字与账号都定不了案时，用作品图反查作者。
        多张图指向不同作者时视为冲突，不定案。
        uid 用于按画师累计记账——同一人改名也不会重置额度。
        """
        if uid and self.sauce_left(uid) <= 0:
            self.log(f"  搜图兜底（{name}）：累计额度已用完"
                     f"（{self.SAUCE_MAX_IMGS} 张），不再搜索")
            return None
        votes, err = self._sauce_votes(images, uid=uid, minsim=85)
        if err:
            self.log(f"  搜图兜底（{name}）：{err}")
            return None
        if len(votes) != 1:
            return None
        tag = next(iter(votes))
        entry = self._entry_by_tag(tag)
        if not entry:
            return None
        ev = votes[tag]
        aid = str(entry.get("id"))
        return {"entry": {
            "id": aid, "name": entry.get("name", ""),
            "other_names": entry.get("other_names") or [],
            "url": f"{DANBOORU.HOST}/artists/{aid}",
            "match": {"verdict": "exact", "hits": [], "nears": []}},
            "proof": [{"handle": name, "url": f"post/{x['post']}",
                       "active": True, "sim": x["sim"]} for x in ev],
            "evidence": "搜图铁证：" + "、".join(
                f"作品{x['post']} 相似度{x['sim']:.0f}% 作者标签 {tag}"
                for x in ev[:3])}

    def verify_one(self, name, force=False):
        """
        核验单个画师并把结果写进记录。
        只记录判定与候选，绝不自动合并或改名——合并须人工确认。
        """
        if not DANBOORU.configured():
            return False, "尚未配置 D 站 API 凭证"
        with self.lock:
            canonical = self.resolve(name)
            rec = self.artists.get(canonical) if canonical else None
            if not rec:
                return False, "找不到这位画师"
            old = rec.get("verify") or {}
            if old.get("state") == "confirmed" and not force:
                return True, "已确认过，跳过"
            aliases = list(rec.get("aliases") or [])
            nm = rec["name"]
            imgs = list(rec.get("images") or [])
            uid = self.ensure_uid(rec)   # 搜图额度按 uid 累计，改名不重置

        r = DANBOORU.verify(nm, aliases)
        verdict = r.get("verdict")
        fuzzy = bool(r.get("fuzzy"))
        cands = r.get("candidates") or []
        top = cands[0] if cands else {}

        # 模糊召回（通配捞回来的形近条目）只能当参考，不能当结论。
        # Blanc.ブラン 曾被模糊匹配蹭到 Blanched_Z，asikumin 蹭到 asikusa，
        # 都是完全不同的画师，绝不能据此直连。
        if fuzzy and verdict == "exact":
            verdict = "near"
        # 多个同名精确命中：名字证据不足以定本人，转人工消歧。
        # 账号铁证（_prove_by_handle）仍可救回其中确定的那个。
        ambiguous = (verdict == "ambiguous")
        trusted = (verdict == "exact") and not fuzzy

        # 名字靠不住时，改用社交账号定案：账号唯一，不会重名也不会错拼。
        # 这一步免费（只查 D 站），能救回大部分「疑似/未找到/同名」。
        proof = None
        if not trusted:
            proof = self._prove_by_handle(nm, aliases, cands)
        # 搜图只在「D 站完全搜不到」时兜底：这是用户的明确授权边界。
        # 同名待消歧、近似疑似都「搜到了只是定不了哪个」，用账号铁证或
        # 人工点选解决，绝不烧搜图额度。
        if not trusted and proof is None and verdict == "none":
            proof = self._prove_by_sauce(nm, imgs, uid=uid)
        if proof:
            trusted = True
            verdict = "exact"
            top = proof["entry"]
            cands = [top] + [c for c in cands
                             if c.get("id") != top.get("id")]

        # 搜图只用于「D 站找不到 / 对应不上」的兜底，已在上面走完。
        # 已命中的画师不再搜图：那属于超出授权的额外调用，会白烧额度。
        cross = ""

        # 账号/搜图铁证若能定案，待消歧也随之解除
        if proof and ambiguous:
            ambiguous = False
        state = {"exact": "matched", "near": "suspect",
                 "none": "missing", "error": "error"}.get(verdict, "error")
        if ambiguous:
            state = "ambiguous"
        hits = (top.get("match") or {}).get("hits", [])
        # 待消歧时保留全部同名候选（含 url/主名标记），供界面逐个点选；
        # 其余情形最多留 5 个。
        cand_out = [{"id": c.get("id"), "name": c.get("name"),
                     "url": c.get("url", ""),
                     "primary": bool(c.get("primary")),
                     "verdict": (c.get("match") or {}).get("verdict")}
                    for c in (cands if ambiguous else cands[:5])]
        info = {
            "state": state,
            # id 是直连的唯一依据：只有可信命中才填，待消歧一律留空
            "id": top.get("id", "") if trusted else "",
            "name": top.get("name", "") if trusted else "",
            "url": top.get("url", "") if trusted else "",
            # 候选另存，只供你人工挑选，不参与跳转
            "suggest_id": top.get("id", "") if not ambiguous else "",
            "suggest_name": top.get("name", "") if not ambiguous else "",
            "suggest_url": top.get("url", "") if not ambiguous else "",
            "message": r.get("message", ""),
            "fuzzy": fuzzy,
            "ambiguous": ambiguous,
            "hits": hits,
            "nears": (top.get("match") or {}).get("nears", []),
            "evidence": (proof["evidence"] if proof else (
                "；".join(
                    f"{h.get('ours')} = 条目{h.get('field')}「{h.get('theirs')}」"
                    for h in hits) if trusted else "")),
            "proof": (proof or {}).get("proof", []),
            "auto": bool(proof),
            "cross": cross,
            "candidates": cand_out,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if not trusted and top.get("id"):
            info["message"] = (
                f"未确认同一人，不会直连。仅供你核对的近似候选："
                f"{top.get('name')}（ID {top.get('id')}）")
        with self.lock:
            cur = self.artists.get(self.resolve(nm, allow_weak=True) or nm)
            if cur is not None:
                cur["verify"] = info
                # 证据闭环：D 站证实过的别名从「弱/明示」升为权威级，
                # 此后它才真正有资格参与认人。账号铁证认定的 handle 同理。
                if trusted:
                    for h in hits:
                        ours = h.get("ours")
                        if ours:
                            self.set_alias(cur, ours, self.ALIAS_TIER_D)
                    for p in (proof or {}).get("proof", []):
                        hh = p.get("handle")
                        if hh:
                            self.set_alias(cur, hh, self.ALIAS_TIER_URL)
        self.save()
        return True, info

    def verify_all(self, force=False, only_pending=False):
        """
        批量核验。默认跳过已确认的；only_pending 时只处理未命中的。
        由采集收尾自动调用，也可由按钮手动触发。
        """
        if not DANBOORU.configured():
            return {"ok": False, "error": "尚未配置 D 站 API 凭证"}
        with self.lock:
            targets = []
            for nm, rec in self.artists.items():
                st = (rec.get("verify") or {}).get("state")
                if st == "confirmed" and not force:
                    continue
                if only_pending and st in ("matched", "confirmed"):
                    continue
                targets.append(nm)
        stat = {"matched": 0, "suspect": 0, "missing": 0,
                "ambiguous": 0, "error": 0, "skipped": 0}
        self.log(f"开始核验 {len(targets)} 位画师（D 站官方接口）…")
        for i, nm in enumerate(targets, 1):
            if self.stop_flag:
                self.log("核验已停止。")
                break
            self.v_progress = i
            self.v_total = len(targets)
            ok, info = self.verify_one(nm, force=force)
            if not ok:
                stat["error"] += 1
                self.log(f"  [{i}/{len(targets)}] {nm} 核验失败：{info}")
                continue
            if isinstance(info, str):
                stat["skipped"] += 1
                continue
            st = info.get("state", "error")
            stat[st] = stat.get(st, 0) + 1
            if st == "matched":
                self.log(f"  [{i}/{len(targets)}] ✓ {nm} → {info['name']}（ID {info['id']}）")
            elif st == "suspect":
                nr = (info.get("nears") or [{}])[0]
                self.log(f"  [{i}/{len(targets)}] ? {nm} ≈ {info['name']}"
                         f"（差 {nr.get('distance','?')} 个字符，待你确认）")
            elif st == "ambiguous":
                self.log(f"  [{i}/{len(targets)}] ⚠ {nm} 有 "
                         f"{len(info.get('candidates') or [])} 个同名条目，待你点选")
            elif st == "missing":
                self.log(f"  [{i}/{len(targets)}] ✗ {nm} 未找到")
            time.sleep(0.5)
        self.v_progress = 0
        self.v_total = 0
        self.log(f"核验完成：命中 {stat['matched']}，同名待消歧 {stat['ambiguous']}，"
                 f"疑似 {stat['suspect']}，未找到 {stat['missing']}，失败 {stat['error']}")
        # 风险B 治本：核验到同一 D 站 ID（T1 权威证据）的画师自动合并，
        # 不再需要你逐个点「合并」按钮。只在强证据下自动做，弱证据仍靠你确认。
        merged = self._auto_merge_same_id()
        if merged:
            self.log(f"已按 D 站权威证据自动合并 {merged} 组同一人")
        return {"ok": True, "stat": stat, "total": len(targets),
                "auto_merged": merged}

    def _auto_merge_same_id(self):
        """
        把核验到同一 D 站 ID 的画师合并为一条（风险B 治本）。

        依据是 T1 权威证据（D 站条目唯一），不是名字猜测，所以可自动执行。
        保留图片最多的一条为主，其余并入；别名、uid 谱系都留存。
        返回合并的组数。不删任何图片。
        """
        groups = {}
        for nm, rec in list(self.artists.items()):
            v = rec.get("verify") or {}
            # 只认已确证命中（matched/confirmed）且有 id 的
            if v.get("state") in ("matched", "confirmed") and v.get("id"):
                groups.setdefault(str(v["id"]), []).append(nm)
        merged = 0
        for did, names in groups.items():
            if len(names) < 2:
                continue
            # 主记录取图片最多的，其余并入；并列时按名字排序保证确定性
            names.sort(key=lambda n: (-len(self.artists[n].get("images", [])), n))
            keep = names[0]
            for other in names[1:]:
                if other not in self.artists:
                    continue
                src = self.artists.pop(other)
                # 合并后把被并的主名留作权威别名，日后再遇到能认出
                self.set_alias(self.artists[keep], other, self.ALIAS_TIER_D)
                self._merge_into(keep, src)   # 不套用上限：合并不得丢图
                merged += 1
        if merged:
            self.save()
        return merged

    def confirm_verify(self, name, artist_id=None, reject=False):
        """
        人工确认：认定同一人（可指定候选 ID），或标记为确实不在 D 站。
        注意：save() 内部会取锁，必须在释放 self.lock 之后调用，否则死锁。
        """
        with self.lock:
            canonical = self.resolve(name)
            rec = self.artists.get(canonical) if canonical else None
            if not rec:
                return False, "找不到这位画师"
            v = dict(rec.get("verify") or {})
            if reject:
                v["state"] = "absent"
                v["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                rec["verify"] = v
            else:
                # 未确认时 id 是空的，候选编号存在 suggest_id 里
                aid = str(artist_id or v.get("id")
                          or v.get("suggest_id") or "").strip()
                if not aid.isdigit():
                    return False, "请给出有效的 D 站画师 ID"
                aname = v.get("name") or v.get("suggest_name") or ""
                for c in v.get("candidates") or []:
                    if str(c.get("id")) == aid:
                        aname = c.get("name") or aname
                v.update({"state": "confirmed", "id": aid, "name": aname,
                          "url": f"{DANBOORU.HOST}/artists/{aid}",
                          "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                rec["verify"] = v
        # 锁已释放，此处落盘与日志才安全
        self.save()
        if reject:
            self.log(f"已标记「{canonical}」为 D 站未收录。")
        else:
            self.log(f"已确认「{canonical}」= D 站 {v.get('name') or v.get('id')}（ID {v.get('id')}）。")
        return True, ""

    # ---------- 登录 ----------
    def start_login(self):
        if self.phase != "idle":
            return False, "已有任务在运行"
        self.phase = "login"
        self.stop_flag = False
        threading.Thread(target=self._login_worker, daemon=True).start()
        return True, ""

    def _login_worker(self):
        try:
            from playwright.sync_api import sync_playwright
            self.log(f"正在为「{ACCOUNTS.label()}」打开浏览器，请扫码登录小红书……")
            with sync_playwright() as p:
                ctx = grab.open_context(p, ACCOUNTS.profile_dir(), headless=False, log=self.log)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(BASE + "/explore", wait_until="domcontentloaded", timeout=60000)
                ok = False
                t0 = time.time()
                while time.time() - t0 < 600 and not self.stop_flag:
                    time.sleep(3)
                    try:
                        if grab.is_logged_in(page):
                            ok = True
                            break
                    except Exception:
                        pass
                try:
                    ctx.close()
                except Exception:
                    pass
            self.logged_in = ok
            self.log(f"「{ACCOUNTS.label()}」登录成功，状态已保存，可以开始采集了。" if ok
                     else "未检测到登录成功，请再试一次。")
        except Exception as e:
            self.log(f"登录出错：{e}")
            self.logged_in = False
        finally:
            self.phase = "idle"

    # ---------- 采集 ----------
    def start_collect(self, keyword, limit, headless=True, auto_verify=True):
        if self.phase != "idle":
            return False, "已有任务在运行"
        self.phase = "collecting"
        self.stop_flag = False
        self.progress = 0
        self.total = limit
        self.keyword = keyword
        threading.Thread(target=self._collect_worker,
                         args=(keyword, limit, headless, auto_verify),
                         daemon=True).start()
        return True, ""

    def stop(self):
        self.stop_flag = True
        self.log("已请求停止，将在当前这篇结束后停下。")

    def _collect_worker(self, keyword, limit, headless, auto_verify=True):
        grab.log = self.log  # 让引擎内部日志流到工作台
        try:
            from playwright.sync_api import sync_playwright
            IMG_DIR.mkdir(parents=True, exist_ok=True)
            self.log(f"开始采集：「{keyword}」，目标 {limit} 篇"
                     + ("（后台静默模式）" if headless else "（显示浏览器）"))
            with sync_playwright() as p:
                ctx = grab.open_context(p, ACCOUNTS.profile_dir(), headless=headless, log=self.log)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(BASE + "/explore", wait_until="domcontentloaded", timeout=60000)
                    time.sleep(3)
                    if not grab.is_logged_in(page):
                        self.logged_in = False
                        self.log("还没登录，请先点「登录小红书」完成扫码。")
                        return
                    self.logged_in = True

                    items = grab.search_notes(page, keyword, limit, log=self.log)
                    self.total = len(items)
                    if not items:
                        self.log("没拿到笔记。若反复为空，请关掉静默模式再试一次。")
                        return
                    self.log(f"共 {len(items)} 篇，开始逐篇提取画师")
                    blocked = 0

                    for i, it in enumerate(items, 1):
                        if self.stop_flag:
                            self.log("已停止。")
                            break
                        self.progress = i
                        title_hint = (it.get("title") or "")[:24]
                        self.log(f"[{i}/{len(items)}] {title_hint}")
                        note = grab.fetch_note(page, it, log=self.log)
                        if not note:
                            blocked += 1
                            self.log("  ✗ 打不开，已跳过")
                            if blocked >= 5 and self.notes_done == 0:
                                self.log("连续多篇被拦截，可能被平台风控了。")
                                self.log("建议：关掉「后台静默」重跑，或等一会儿再试。")
                                break
                            time.sleep(2.0)
                            continue
                        blocked = 0
                        plan = grab.build_plan(note, i)
                        if not plan:
                            self.log("  这篇没有可用图片，跳过")
                            continue
                        self.notes_done += 1
                        got = self._ingest(ctx, note, plan, note["url"])
                        names = sorted({x["artist"] for x in plan})
                        self.log(f"  ✓ {len(note['images'])} 张图 / 画师：{'、'.join(names[:4])}"
                                 f" → 新增 {got} 张")
                        self.save()
                        time.sleep(1.2)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
            self.save()
            self.log(f"采集完成：{len(self.artists)} 位画师，"
                     f"{sum(len(a['images']) for a in self.artists.values())} 张作品图")
            # 整轮采完再核验：此时同一画师的别名已从各篇笔记累积完整，
            # 逐篇核验会因别名还没到齐而误判「搜不到」。
            if auto_verify and DANBOORU.configured() and not self.stop_flag:
                try:
                    self.verify_all()
                except Exception as e:
                    self.log(f"自动核验出错（不影响已采集数据）：{e}")
            elif auto_verify and not DANBOORU.configured():
                self.log("未配置 D 站 API，跳过自动核验。可在「D站接口」里配置后手动核验。")
        except Exception as e:
            self.log(f"采集出错：{e}")
            self.log(traceback.format_exc().splitlines()[-1])
        finally:
            self.phase = "idle"

    @staticmethod
    def name_key(n):
        """画师身份键：忽略大小写、首尾空格、@前缀与全角空格。"""
        s = str(n or "").strip().strip("\u3000").lstrip("@").strip()
        return s.casefold()

    # 「待认领」是无归属图片的占位筐，不是真实画师身份。
    # 它一旦成为某人的别名，resolve() 就会把后续所有无归属图片
    # 都判给那位画师（曾让 BwPuppy 吞下 49 张别人的图）。
    PLACEHOLDER_NAMES = {"待认领"}

    @classmethod
    def is_placeholder(cls, name):
        return cls.name_key(name) in {cls.name_key(x)
                                      for x in cls.PLACEHOLDER_NAMES}

    # ---------- 身份模型 ----------
    # 名字是不可靠的标签：会重名、会错拼、会被栏目名污染。
    # 所以身份用不可变 uid 表示，名字只是指向 uid 的显示标签。
    # 别名按「证据来源」分级，只有能证明同一人的证据才参与认人。
    # 数字越小证据越硬；set_alias 只升不降。
    ALIAS_TIER_D = 1       # D 站条目别名表里确有此名 —— 权威
    ALIAS_TIER_URL = 2     # D 站登记的社交账号 —— 权威
    ALIAS_TIER_HUMAN = 3   # 人工通篇读帖确认 / 界面点选 —— 强
    ALIAS_TIER_POST = 4    # 帖内明示账号（「X：@xxx」「推特：xxx」）—— 强
                           # 博主亲口声明的身份，可认人
    ALIAS_TIER_WEAK = 5    # 无来源记录、仅写法差异 —— 弱，不认人
    TIER_LABEL = {1: "D站核验", 2: "账号登记", 3: "人工确认",
                  4: "帖内明示账号", 5: "仅写法差异"}
    STRONG_TIERS = (1, 2, 3, 4)

    @staticmethod
    def new_uid():
        import secrets
        return "a" + format(int(time.time() * 1000), "x") + secrets.token_hex(4)

    def alias_tier(self, rec, alias):
        """取别名的证据等级；没记录过的一律按最弱处理。"""
        src = rec.get("alias_src") or {}
        return int(src.get(self.name_key(alias), self.ALIAS_TIER_WEAK))

    def set_alias(self, rec, alias, tier):
        """
        写入别名及其证据等级。等级只升不降：
        强证据一旦被记录，不能被后来的弱证据覆盖掉。
        占位名与通用词永远不收作别名（它们是污染源）。
        """
        if not alias:
            return False
        if self.is_placeholder(alias) or self.is_generic_word(alias):
            return False
        k = self.name_key(alias)
        if not k or k == self.name_key(rec.get("name")):
            return False
        rec.setdefault("aliases", [])
        src = rec.setdefault("alias_src", {})
        changed = False
        cur = src.get(k)
        if cur is None or int(tier) < int(cur):
            src[k] = int(tier)
            changed = True
        if not any(self.name_key(x) == k for x in rec["aliases"]):
            rec["aliases"].append(alias)
            changed = True
        return changed

    def strong_aliases(self, rec):
        """只返回有强证据的别名（T1-T3），弱别名不参与认人。"""
        src = rec.get("alias_src") or {}
        return [a for a in (rec.get("aliases") or [])
                if int(src.get(self.name_key(a), self.ALIAS_TIER_WEAK))
                in self.STRONG_TIERS]

    # ---------- 语义映射 ----------
    # 规则层只能按字符形态匹配，永远追不上博主的写法（栏目名会被当画师、
    # 账号会被当主名）。人工通篇阅读得出的判定沉淀在 语义映射.json 里，
    # 入库时套用，让同类错误不再复发。文件缺失时静默跳过，不影响采集。
    def _load_semantic(self):
        self._sem = {"generic": {}, "rename": {}, "aliases": {}}
        if not SEMANTIC_FILE.is_file():
            return
        try:
            d = json.loads(SEMANTIC_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        g = d.get("通用词") or {}
        self._sem["generic"] = {self.name_key(k): k
                                for k in g if not k.startswith("_")}
        r = d.get("改名") or {}
        self._sem["rename"] = {self.name_key(k): v
                               for k, v in r.items() if not k.startswith("_")}
        a = d.get("补别名") or {}
        for k, v in a.items():
            if k.startswith("_") or not isinstance(v, list):
                continue
            self._sem["aliases"][self.name_key(k)] = list(v)

    def semantic_canonical(self, name):
        """规则层抽出的名字 → 语义确认的正确身份（无映射则原样返回）。"""
        return self._sem["rename"].get(self.name_key(name), name)

    def is_generic_word(self, name):
        """是否是栏目名/博主自称/版权用语等通用词，绝不能当画师身份。"""
        return self.name_key(name) in self._sem["generic"]

    def semantic_aliases(self, name):
        """该画师语义确认过的别名（正文里明确给出但规则层漏掉的）。"""
        return self._sem["aliases"].get(self.name_key(name), [])

    def resolve(self, name, allow_weak=False):
        """
        按本名或别名找到已存在的画师记录名；找不到返回 None。

        两遍匹配，顺序就是优先级：
          第一遍 只比主名 —— 主名永远胜过任何人的别名。
            否则「米室」被登记为甲的别名时，米室自己的图会被甲吞走。
          第二遍 才比别名。

        allow_weak=False（默认）：只认强证据别名（D站核验/账号登记/人工确认）。
        帖内共现提取的弱别名不参与认人——它只说明「同一篇里出现过」，
        不能证明是同一人。曾有人因此把「米室」的图吞进别人名下。

        allow_weak=True：仅用于用户主动操作（改名/移图/核验/删除），
        此时是人在指认对象，按名字找得到更符合直觉。
        """
        k = self.name_key(name)
        if not k:
            return None
        # 第一遍：主名优先
        for canonical, rec in self.artists.items():
            if self.name_key(canonical) == k:
                return canonical
        # 第二遍：别名（顺手清掉占位/通用词这类污染别名）
        for canonical, rec in self.artists.items():
            al = rec.get("aliases")
            if al and any(self.is_placeholder(x) or self.is_generic_word(x)
                          for x in al):
                rec["aliases"] = [x for x in al
                                  if not self.is_placeholder(x)
                                  and not self.is_generic_word(x)]
            pool = rec.get("aliases", []) if allow_weak else self.strong_aliases(rec)
            for a in pool:
                if self.name_key(a) == k:
                    return canonical
        return None

    def resolve_by_uid(self, uid):
        """按不可变 uid 找画师名，改名后身份依然可追溯。"""
        if not uid:
            return None
        for canonical, rec in self.artists.items():
            if rec.get("uid") == uid:
                return canonical
        return None

    def ensure_uid(self, rec):
        """给记录补上不可变 uid（迁移期老数据没有）。"""
        if not rec.get("uid"):
            rec["uid"] = self.new_uid()
        return rec["uid"]

    def _merge_into(self, dst_name, src_rec, apply_cap=False):
        """
        把 src_rec 的内容并入 dst_name（调用方需持锁）。
        返回因收图上限而**未并入**的图片记录列表（不是数量）。

        apply_cap 默认 False：加载历史数据、撤销还原都必须全量并入，
        否则超限的图片会被静默丢弃，落盘后永久找不回来。
        只有用户主动改名合并时才套用上限，且调用方必须把返回的
        图片另行保全——源记录在调用处已被 pop，不保全就等于删图。
        """
        dst = self.artists[dst_name]
        have = {grab.image_key(im.get("src", "")) for im in dst["images"]}
        cap = int(self.max_per_artist or 0) if apply_cap else 0
        skipped = []
        for im in src_rec.get("images", []):
            k = grab.image_key(im.get("src", ""))
            if k in have:
                continue
            if cap > 0 and len(dst["images"]) >= cap:
                skipped.append(im)
                continue
            dst["images"].append(im)
            have.add(k)
        for st in src_rec.get("styles", []):
            if st not in dst["styles"]:
                dst["styles"].append(st)
        for al in src_rec.get("aliases", []):
            # 占位名不是身份，收作别名会让无归属图持续倒进这位画师
            if self.is_placeholder(al):
                continue
            if (self.name_key(al) != self.name_key(dst_name)
                    and al not in dst.setdefault("aliases", [])):
                dst["aliases"].append(al)
        for nt in src_rec.get("notes", []):
            if not any(x["url"] == nt["url"] for x in dst["notes"]):
                dst["notes"].append(nt)
        # 返回未并入的图片记录本身（非数量），调用方需据此保全，避免丢图
        return skipped

    @staticmethod
    def _find_image(rec, ident):
        """按本地路径或在线稳定标识定位一张图（在线模式下 file 为空）。"""
        if not ident:
            return None
        for im in rec.get("images", []):
            if im.get("file") and im["file"] == ident:
                return im
        for im in rec.get("images", []):
            if ident in (im.get("key"), im.get("src")):
                return im
        return None

    def _folder_for(self, canonical, style=""):
        """
        决定画师用哪个文件夹。
        若净化后的目录名已被另一位画师占用，则加序号区分，避免两人混图。
        调用方需持锁。
        """
        base = grab.safe_name(f"{canonical}_{style}" if style else canonical)
        # 该画师已有的目录优先沿用
        rec = self.artists.get(canonical)
        if rec and rec.get("images"):
            old = (ROOT / rec["images"][0]["file"]).parent.name
            if old:
                return old
        used = {}
        for nm, r in self.artists.items():
            if nm == canonical or not r.get("images"):
                continue
            used[(ROOT / r["images"][0]["file"]).parent.name] = nm
        if base not in used:
            return base
        i = 2
        while f"{base}_{i}" in used:
            i += 1
        return f"{base}_{i}"

    def _known_srcs(self):
        """已收过图片的稳定标识，用于跨帖子/跨轮次去重。"""
        s = set()
        for a in self.artists.values():
            for im in a.get("images", []):
                k = im.get("key") or grab.image_key(im.get("src", ""))
                if k:
                    s.add(k)
        return s

    def _owner_map(self):
        """图片稳定键 -> 当前持有它的画师名，用于发现归属冲突。"""
        m = {}
        for nm, a in self.artists.items():
            for im in a.get("images", []):
                k = im.get("key") or grab.image_key(im.get("src", ""))
                if k:
                    m[k] = nm
        return m

    def _semantic_fix(self, item):
        """
        语义纠正：字符匹配分不清栏目名/账号/真名，按人工通篇读帖
        得出的映射修正。返回 (名字, 风格, 归属可信度, 别名, 强别名集)。
        去重分支和入库分支都要用，故提取为独立方法避免两处逻辑漂移。
        """
        raw_name = item.get("artist") or ""
        style = item.get("style", "")
        conf = item.get("confidence", "guess")
        aliases = item.get("aliases", []) or []
        if self.is_generic_word(raw_name):
            # 「审美积累」这类栏目名不是身份，图片退回待认领由人判断
            return "待认领", style, "unknown", [], set()
        fixed = self.semantic_canonical(raw_name)
        if fixed != raw_name:
            aliases = [a for a in aliases
                       if self.name_key(a) != self.name_key(fixed)]
            if raw_name not in aliases:
                aliases.append(raw_name)   # 原写法留作溯源别名
            raw_name = fixed
        extra = [a for a in self.semantic_aliases(raw_name) if a not in aliases]
        aliases += extra
        sem_set = set(self.semantic_aliases(raw_name))
        return raw_name, style, conf, aliases, sem_set

    def _ingest(self, ctx, note, plan, link):
        added = dup = capped = 0
        known = self._known_srcs()
        owner = self._owner_map()
        conflicts = 0
        # 先把正文补进已存在的笔记记录：重复采集时图片会全部判重跳过，
        # 若放到图片循环里就永远存不上正文，语义证据随之丢失。
        desc = note.get("desc") or ""
        if desc:
            with self.lock:
                for rec in self.artists.values():
                    for nt in rec.get("notes", []):
                        if nt.get("url") == link and not nt.get("desc"):
                            nt["desc"] = desc
                            nt.setdefault("img_count",
                                          len(note.get("images") or []))
        for item in plan:
            src_key = grab.image_key(item["image_url"])
            raw_name, style, conf, aliases, sem_set = self._semantic_fix(item)
            if src_key in known:
                dup += 1
                # 这张图已经归在别人名下，本篇却认为属于另一个人。
                # 不自动裁决（可能是转载/合作/某篇搞错），但必须留痕，
                # 否则后到的画师会凭空消失而无人察觉。
                held = owner.get(src_key)
                if held and raw_name != "待认领" \
                        and self.name_key(held) != self.name_key(raw_name):
                    if self.record_conflict(src_key, item["image_url"],
                                            raw_name, link,
                                            note.get("title") or "", held):
                        conflicts += 1
                continue
            with self.lock:
                canonical = self.resolve(raw_name) or raw_name.strip().lstrip("@")
                # 单画师上限：同一人被多篇推荐时不再无限累积
                cur = self.artists.get(canonical)
                cap = int(self.max_per_artist or 0)
                if cap > 0 and cur and len(cur.get("images", [])) >= cap:
                    capped += 1
                    continue

            rel = ""
            if self.save_local:
                # 可选：同时把原图存到本地做离线备份
                with self.lock:
                    folder = self._folder_for(canonical, style)
                d = IMG_DIR / folder
                d.mkdir(parents=True, exist_ok=True)
                low = item["image_url"].lower()
                ext = ".png" if ".png" in low else (".webp" if ".webp" in low else ".jpg")
                n = len([x for x in d.iterdir() if x.is_file()]) + 1
                dest = d / f"{grab.safe_name(canonical)}_{n:02d}{ext}"
                while dest.exists():
                    n += 1
                    dest = d / f"{grab.safe_name(canonical)}_{n:02d}{ext}"
                if not grab.download_image(ctx, item["image_url"], dest):
                    continue
                rel = dest.relative_to(ROOT).as_posix()
            with self.lock:
                canonical = self.resolve(raw_name) or canonical
                rec = self.artists.setdefault(canonical, {
                    "name": canonical, "styles": [], "images": [],
                    "notes": [], "aliases": [], "alias_src": {}})
                self.ensure_uid(rec)
                if style and style not in rec["styles"]:
                    rec["styles"].append(style)
                # 别名按「证据来源」分级写入：
                #   语义映射里人工通篇读帖确认过的 → 人工级
                #   plan 带来的别名（帖子明示「X：@xxx」「推特：xxx」或
                #     括号内账号）→ 帖内明示级，博主亲口声明，可认人
                #   仅本次写法与主名不同（大小写/@等）→ 弱级，只溯源不认人
                # 弱别名不参与认人，否则「米室」出现在别人帖子里就会把
                # 米室的图全吸过去——风险C 的根因。
                for al in aliases:
                    tier = (self.ALIAS_TIER_HUMAN if al in sem_set
                            else self.ALIAS_TIER_POST)
                    self.set_alias(rec, al, tier)
                self.set_alias(rec, raw_name, self.ALIAS_TIER_WEAK)
                # 历史遗留的占位/通用词别名顺手清掉
                if any(self.is_placeholder(x) or self.is_generic_word(x)
                       for x in rec.get("aliases", [])):
                    rec["aliases"] = [x for x in rec["aliases"]
                                      if not self.is_placeholder(x)
                                      and not self.is_generic_word(x)]
                    src = rec.get("alias_src") or {}
                    for k in list(src):
                        if not any(self.name_key(a) == k
                                   for a in rec["aliases"]):
                            src.pop(k, None)
                rec["images"].append({"file": rel,
                                      "src": grab.permanent_url(item["image_url"]),
                                      "orig": item["image_url"],
                                      "conf": conf, "seq": item.get("seq", 0),
                                      "key": src_key})
                added += 1
                known.add(src_key)
                owner[src_key] = canonical   # 同轮内的后续重复图也能查到归属
                if not any(nt["url"] == link for nt in rec["notes"]):
                    rec["notes"].append({
                        "title": note["title"] or "无标题",
                        "url": link, "author": note["author"],
                        # 正文必须存盘：小红书 token 会失效，失效后这篇笔记
                        # 再也打不开。语义判定（画师名/博主自称/栏目名）全靠
                        # 正文证据，不留存就等于证据永久丢失、结论无法复核。
                        "desc": note.get("desc", "") or "",
                        "img_count": len(note.get("images") or []),
                    })
                else:
                    # 已存在但缺正文（旧数据）：趁 token 还有效补上
                    nt = next(x for x in rec["notes"] if x["url"] == link)
                    if not nt.get("desc") and note.get("desc"):
                        nt["desc"] = note["desc"]
                        nt.setdefault("img_count", len(note.get("images") or []))
        if dup:
            self.log(f"  （跳过 {dup} 张已收过的重复图）")
        if conflicts:
            self.log(f"  ⚠ {conflicts} 张图归属有分歧（已归他人名下），"
                     f"已记入「归属冲突」清单待你核对，未自动改动")
        if capped:
            self.log(f"  （{capped} 张因画师已达 {self.max_per_artist} 张上限未收）")
        return added

    # ---------- 人工修正 ----------
    def rename_artist(self, old, new):
        new = (new or "").strip()
        if not new:
            return False, "新名字不能为空"
        with self.lock:
            # 用户主动改名：允许按任意写法（含弱别名）找到对象
            src_name = self.resolve(old, allow_weak=True)
            if not src_name:
                return False, "找不到这位画师"
            # 「待认领」里混着多位画师的无归属图，整筐改名会把别人的图
            # 全判给一个人。必须逐张移图，不能整筐改名。
            if self.is_placeholder(src_name):
                return False, ("「待认领」是无归属图片的暂存筐，可能混着多位画师，"
                               "不能整筐改名。请展开图片，逐张移到对应画师名下。")
            target = self.resolve(new, allow_weak=True)
            skipped = []
            if target and target != src_name:
                # 目标是已存在的另一位（含大小写/别名变体）→ 合并
                src_rec = self.artists.pop(src_name)
                # 旧主名保留为别名，便于日后同写法再次归并
                if (not self.is_placeholder(src_name)
                        and self.name_key(src_name) != self.name_key(target)):
                    src_rec.setdefault("aliases", []).append(src_name)
                # 用户主动合并才套用收图上限
                skipped = self._merge_into(target, src_rec, apply_cap=True)
                self.artists[target]["aliases"] = [
                    a for a in self.artists[target].get("aliases", [])
                    if self.name_key(a) != self.name_key(target)]
                if skipped:
                    # 源记录已被 pop，装不下的图必须放回去，否则永久丢失。
                    # 只保留未并入的那些，避免同一张图同时挂在两人名下。
                    src_rec["images"] = skipped
                    self.artists[src_name] = src_rec
            else:
                rec = self.artists.pop(src_name)
                # 若只是大小写/空格差异，视为同一人，沿用原主名
                if target == src_name and self.name_key(new) == self.name_key(src_name):
                    self.artists[src_name] = rec
                else:
                    if (not self.is_placeholder(src_name)
                            and self.name_key(src_name) != self.name_key(new)):
                        al = rec.setdefault("aliases", [])
                        if src_name not in al:
                            al.append(src_name)
                    rec["name"] = new
                    rec["aliases"] = [a for a in rec.get("aliases", [])
                                      if self.name_key(a) != self.name_key(new)
                                      and not self.is_placeholder(a)]
                    self.artists[new] = rec
        self.save()
        self.log(f"已把「{old}」改名为「{new}」")
        # 锁已释放后才能 log：log() 内部会取锁，持锁调用会死锁
        if skipped:
            self.log(f"  注意：有 {len(skipped)} 张图因「{new}」已达收图上限"
                     f"（{self.max_per_artist} 张）未能并入，已原样留在"
                     f"「{old}」名下，一张都没删。"
                     f"如需全部合并，请把上限调高后重新操作。")
        return True, ""

    def restore_artist(self, rec):
        """撤销移除：把画师记录写回，按身份归并避免产生重复条目。"""
        if not isinstance(rec, dict) or not rec.get("name"):
            return False, "还原数据不完整"
        name = str(rec["name"]).strip()
        if not name:
            return False, "画师名为空"
        clean = {
            "name": name,
            "styles": list(rec.get("styles") or []),
            "images": [im for im in (rec.get("images") or []) if isinstance(im, dict)],
            "notes": list(rec.get("notes") or []),
            "aliases": list(rec.get("aliases") or []),
        }
        # 还原的旧记录可能还带签名链接，先换成永久链接
        for im in clean["images"]:
            grab.normalize_image(im)
        with self.lock:
            exist = self.resolve(name)
            if exist:
                self._merge_into(exist, clean)
            else:
                self.artists[name] = clean
        self.save()
        self.log(f"已还原「{name}」（{len(clean['images'])} 张）")
        return True, ""

    def restore_image(self, name, im):
        """撤销移除单张图：写回该画师名下，找不到画师则重建。"""
        if not isinstance(im, dict):
            return False, "还原数据不完整"
        name = str(name or "").strip()
        if not name:
            return False, "画师名为空"
        with self.lock:
            canonical = self.resolve(name) or name
            rec = self.artists.setdefault(canonical, {
                "name": canonical, "styles": [], "images": [],
                "notes": [], "aliases": []})
            # 撤销写回的可能是旧记录，链接先归一再入库
            grab.normalize_image(im)
            k = im.get("key") or grab.image_key(im.get("src", ""))
            dup = any((x.get("key") or grab.image_key(x.get("src", ""))) == k
                      for x in rec["images"])
            if not dup:
                rec["images"].append(im)
        self.save()
        self.log(f"已还原「{canonical}」的 1 张图")
        return True, ""

    def delete_artist(self, name):
        with self.lock:
            if name not in self.artists:
                return False, "找不到这位画师"
            self.artists.pop(name)
        self.save()
        self.log(f"已移除「{name}」（图片文件仍保留在硬盘上）")
        return True, ""

    def move_image(self, src_name, file_rel, dst_name):
        dst_name = (dst_name or "").strip()
        if not dst_name:
            return False, "请填写要移动到的画师名"
        with self.lock:
            src_key_name = self.resolve(src_name)
            src = self.artists.get(src_key_name) if src_key_name else None
            if not src:
                return False, "找不到来源画师"
            hit = self._find_image(src, file_rel)
            if not hit:
                return False, "找不到这张图"

            # 目标按本名/别名解析，避免同一人被新建成两条
            canonical_dst = self.resolve(dst_name) or dst_name.lstrip("@").strip()
            if canonical_dst == src_key_name:
                return False, "这张图已经在该画师名下了"

            # 在线模式下图片没有本地文件，只改归属记录即可
            if file_rel:
                old_path = (ROOT / file_rel).resolve()
                if not old_path.is_relative_to(ROOT.resolve()):
                    return False, "图片路径不合法"
                if old_path.is_file():
                    styles = self.artists.get(canonical_dst, {}).get("styles") or []
                    style = styles[0] if styles else ""
                    folder = self._folder_for(canonical_dst, style)
                    new_dir = IMG_DIR / folder
                    try:
                        new_dir.mkdir(parents=True, exist_ok=True)
                        n = len([p for p in new_dir.iterdir() if p.is_file()]) + 1
                        ext = old_path.suffix or ".jpg"
                        new_path = new_dir / f"{grab.safe_name(canonical_dst)}_{n:02d}{ext}"
                        while new_path.exists():
                            n += 1
                            new_path = new_dir / f"{grab.safe_name(canonical_dst)}_{n:02d}{ext}"
                        shutil.move(str(old_path), str(new_path))
                        hit["file"] = new_path.relative_to(ROOT).as_posix()
                    except OSError as e:
                        return False, f"移动文件失败：{e}"
                else:
                    # 备份文件已被清理，退化为纯在线记录
                    hit["file"] = ""

            src["images"].remove(hit)
            hit["conf"] = "manual"
            dst = self.artists.setdefault(canonical_dst, {
                "name": canonical_dst, "styles": [], "images": [],
                "notes": [], "aliases": []})
            if (self.name_key(dst_name) != self.name_key(canonical_dst)
                    and dst_name not in dst.setdefault("aliases", [])):
                dst["aliases"].append(dst_name)
            dst["images"].append(hit)
            if not src["images"]:
                self.artists.pop(src_key_name, None)
        self.save()
        self.log(f"已把一张图从「{src_name}」移到「{dst_name}」")
        return True, ""

    def delete_image(self, name, file_rel):
        with self.lock:
            rec = self.artists.get(self.resolve(name) or name)
            if not rec:
                return False, "找不到这位画师"
            hit = self._find_image(rec, file_rel)
            if not hit:
                return False, "找不到这张图"
            rec["images"].remove(hit)
            if not rec["images"]:
                self.artists.pop(rec["name"], None)
        self.save()
        self.log("已从清单移除一张图（文件仍在硬盘上）")
        return True, ""


ENGINE = Engine()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urlparse(self.path)
        # 路径需解码：中文资源名（如应用图标.png）在 URL 里是百分号编码
        p, q = unquote(u.path), parse_qs(u.query)
        if p in ("/", "/index.html"):
            if not UI_FILE.exists():
                return self._send(500, "界面文件缺失", "text/plain; charset=utf-8")
            return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
        if p in ("/favicon.ico", "/应用图标.ico"):
            f = ROOT / "应用图标.ico"
            if f.is_file():
                return self._send(200, f.read_bytes(), "image/x-icon")
            return self._send(404, "not found", "text/plain")
        if p == "/应用图标.png":
            f = ROOT / "应用图标.png"
            if f.is_file():
                return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, "not found", "text/plain")
        if p == "/api/state":
            return self._json(ENGINE.state())
        if p == "/api/accounts":
            return self._json({"ok": True, "accounts": ACCOUNTS.list(),
                               "current": ACCOUNTS.current()})
        if p == "/api/d_cred":
            # 只回脱敏信息，绝不回传 API Key 明文
            return self._json({"ok": True, **DANBOORU.masked()})
        if p == "/api/s_cred":
            return self._json({"ok": True, **SAUCENAO.masked(),
                               "quota": SAUCENAO.quota()})
        if p == "/api/palette":
            name = q.get("n", [""])[0]
            return self._json(ENGINE.palette(name))
        if p == "/api/data":
            return self._json({"artists": ENGINE.data()})
        if p == "/img":
            rel = unquote(q.get("p", [""])[0])
            if not rel or "\x00" in rel:
                return self._send(404, "not found", "text/plain")
            try:
                f = (ROOT / rel).resolve()
                # 用 is_relative_to 严格判定，避免同前缀兄弟目录被误放行
                if not f.is_relative_to(ROOT.resolve()):
                    return self._send(404, "not found", "text/plain")
            except (ValueError, OSError):
                return self._send(404, "not found", "text/plain")
            if not f.is_file():
                return self._send(404, "not found", "text/plain")
            ctype = mimetypes.guess_type(str(f))[0] or "image/jpeg"
            try:
                return self._send(200, f.read_bytes(), ctype)
            except OSError:
                return self._send(404, "not found", "text/plain")
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        n = max(0, min(n, 1_000_000))
        try:
            raw = self.rfile.read(n) if n else b"{}"
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        # 只接受 JSON 对象，数组/字符串/null 一律按空处理，避免 .get 崩溃
        if not isinstance(body, dict):
            body = {}
        if p == "/api/d_cred_save":
            ok, err = DANBOORU.save(body.get("login", ""), body.get("api_key", ""))
            if ok:
                # 只记事件，绝不记凭证内容
                ENGINE.log("已保存 D 站 API 凭证（仅存本机）。")
            return self._json({"ok": ok, "error": err, **DANBOORU.masked()})
        if p == "/api/d_cred_clear":
            ok, err = DANBOORU.clear()
            if ok:
                ENGINE.log("已清除本机保存的 D 站 API 凭证。")
            return self._json({"ok": ok, "error": err, **DANBOORU.masked()})
        if p == "/api/s_cred_save":
            ok, err = SAUCENAO.save(body.get("api_key", ""))
            if ok:
                ENGINE.log("已保存搜图 API 凭证（仅存本机）。")
            return self._json({"ok": ok, "error": err, **SAUCENAO.masked()})
        if p == "/api/s_cred_clear":
            ok, err = SAUCENAO.clear()
            if ok:
                ENGINE.log("已清除本机保存的搜图 API 凭证。")
            return self._json({"ok": ok, "error": err, **SAUCENAO.masked()})
        if p == "/api/s_probe":
            if not SAUCENAO.configured():
                return self._json({"ok": False, "error": "尚未配置搜图 API Key"})
            u = str(body.get("url") or "").strip()
            if not u:
                # 未指定时取库里第一张作品图，省得你手动找链接
                for rec in ENGINE.data():
                    for im in rec.get("images") or []:
                        if str(im.get("src") or "").startswith("http"):
                            u = im["src"]
                            break
                    if u:
                        break
            r = SAUCENAO.probe(u)
            r["tested_url"] = u
            if r.get("ok"):
                ENGINE.log(f"搜图接口连通，返回 {r.get('results', 0)} 条候选。")
            else:
                ENGINE.log(f"搜图接口测试未通过：{r.get('error')}")
            return self._json(r)
        if p == "/api/d_verify_all":
            if ENGINE.phase != "idle":
                return self._json({"ok": False, "error": "请先等当前任务结束"})
            if not DANBOORU.configured():
                return self._json({"ok": False, "error": "尚未配置 D 站 API 凭证"})
            force = bool(body.get("force"))
            only_pending = bool(body.get("only_pending"))

            def _run():
                ENGINE.phase = "verifying"
                ENGINE.stop_flag = False
                try:
                    ENGINE.verify_all(force=force, only_pending=only_pending)
                except Exception as e:
                    ENGINE.log(f"核验出错：{e}")
                finally:
                    ENGINE.phase = "idle"

            threading.Thread(target=_run, daemon=True).start()
            return self._json({"ok": True})
        if p == "/api/d_verify_one":
            nm = str(body.get("name") or "").strip()
            if not nm:
                return self._json({"ok": False, "error": "请给出画师名"})
            ok, info = ENGINE.verify_one(nm, force=bool(body.get("force")))
            if ok and isinstance(info, dict):
                st = info.get("state")
                if st == "matched":
                    ENGINE.log(f"核验通过：{nm} → {info['name']}（ID {info['id']}）")
                elif st == "suspect":
                    ENGINE.log(f"疑似同人：{nm} ≈ {info['name']}，待确认")
                else:
                    ENGINE.log(f"未命中：{nm}")
            return self._json({"ok": ok,
                               "error": info if isinstance(info, str) and not ok else "",
                               "verify": info if isinstance(info, dict) else None})
        if p == "/api/d_confirm":
            ok, err = ENGINE.confirm_verify(
                body.get("name", ""), body.get("artist_id"),
                reject=bool(body.get("reject")))
            return self._json({"ok": ok, "error": err})
        if p == "/api/d_verify":
            nm = str(body.get("name") or "").strip()
            if not nm:
                return self._json({"ok": False, "error": "请给出要核验的画师名"})
            if not DANBOORU.configured():
                return self._json({"ok": False, "error": "尚未配置 API 凭证"})
            aliases = body.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            ENGINE.log(f"正在核验画师「{nm}」…")
            r = DANBOORU.verify(nm, aliases)
            v = r.get("verdict")
            if v == "exact":
                c = r["candidates"][0]
                ENGINE.log(f"核验通过：{nm} → D 站 {c['name']}（ID {c['id']}）")
            elif v == "near":
                c = r["candidates"][0]
                ENGINE.log(f"疑似同人：{nm} ≈ {c['name']}，需人工确认")
            else:
                ENGINE.log(f"未命中：{nm}（{r.get('message')}）")
            return self._json({"ok": True, **r})
        if p == "/api/d_probe":
            aid = str(body.get("artist_id") or "149913").strip()
            if not aid.isdigit():
                return self._json({"ok": False, "error": "画师 ID 只能是数字"})
            ENGINE.log(f"正在测试 D 站接口连通性（画师 {aid}）…")
            r = DANBOORU.probe(aid)
            if r.get("ok"):
                ENGINE.log(f"接口可用：{r['name']}（作品 {r.get('post_count')}）")
            else:
                ENGINE.log(f"接口不可用：{r.get('error')}")
            return self._json(r)
        if p == "/api/login":
            ok, err = ENGINE.start_login()
            return self._json({"ok": ok, "error": err})
        if p == "/api/accounts":
            return self._json({"ok": True, "accounts": ACCOUNTS.list(),
                               "current": ACCOUNTS.current()})
        if p == "/api/account_add":
            if ENGINE.phase != "idle":
                return self._json({"ok": False, "error": "请先等当前任务结束"})
            aid = ACCOUNTS.add(body.get("label", ""))
            ENGINE.logged_in = None
            ENGINE.log(f"已新建并切换到「{ACCOUNTS.label(aid)}」，请点登录扫码。")
            return self._json({"ok": True, "id": aid})
        if p == "/api/account_switch":
            if ENGINE.phase != "idle":
                return self._json({"ok": False, "error": "请先等当前任务结束"})
            ok, err = ACCOUNTS.switch(body.get("id", ""))
            if ok:
                ENGINE.logged_in = None
                ENGINE.log(f"已切换到「{ACCOUNTS.label()}」。")
            return self._json({"ok": ok, "error": err})
        if p == "/api/account_rename":
            ok, err = ACCOUNTS.rename(body.get("id", ""), body.get("label", ""))
            return self._json({"ok": ok, "error": err})
        if p == "/api/account_logout":
            if ENGINE.phase != "idle":
                return self._json({"ok": False, "error": "请先等当前任务结束"})
            aid = body.get("id") or ACCOUNTS.current()
            ok, err = ACCOUNTS.logout(aid)
            if ok:
                if aid == ACCOUNTS.current():
                    ENGINE.logged_in = False
                ENGINE.log(f"已退出「{ACCOUNTS.label(aid)}」的登录，采集数据未受影响。")
            return self._json({"ok": ok, "error": err})
        if p == "/api/account_remove":
            if ENGINE.phase != "idle":
                return self._json({"ok": False, "error": "请先等当前任务结束"})
            ok, err = ACCOUNTS.remove(body.get("id", ""))
            if ok:
                ENGINE.logged_in = None
                ENGINE.log("已删除该账号及其登录态，采集数据未受影响。")
            return self._json({"ok": ok, "error": err})
        if p == "/api/collect":
            kw = (body.get("keyword") or "").strip()
            if not kw:
                return self._json({"ok": False, "error": "请填写关键词"})
            try:
                limit = max(1, min(200, int(body.get("limit", 20))))
            except Exception:
                limit = 20
            ENGINE.save_local = bool(body.get("save_local", False))
            # 单画师作品上限：0 表示不限制，其余钳制在 1..500
            try:
                mpa = int(body.get("max_per_artist", ENGINE.max_per_artist))
            except Exception:
                mpa = ENGINE.max_per_artist
            ENGINE.max_per_artist = max(0, min(500, mpa))
            ok, err = ENGINE.start_collect(
                kw, limit, bool(body.get("headless", True)),
                auto_verify=bool(body.get("auto_verify", True)))
            return self._json({"ok": ok, "error": err})
        if p == "/api/stop":
            ENGINE.stop()
            return self._json({"ok": True})
        if p == "/api/rename":
            ok, err = ENGINE.rename_artist(body.get("old", ""), body.get("new", ""))
            return self._json({"ok": ok, "error": err})
        if p == "/api/delete_artist":
            ok, err = ENGINE.delete_artist(body.get("name", ""))
            return self._json({"ok": ok, "error": err})
        if p == "/api/restore_artist":
            ok, err = ENGINE.restore_artist(body.get("artist"))
            return self._json({"ok": ok, "error": err})
        if p == "/api/restore_image":
            ok, err = ENGINE.restore_image(body.get("name", ""), body.get("image"))
            return self._json({"ok": ok, "error": err})
        if p == "/api/move_image":
            ok, err = ENGINE.move_image(body.get("from", ""), body.get("file", ""),
                                        body.get("to", ""))
            return self._json({"ok": ok, "error": err})
        if p == "/api/delete_image":
            ok, err = ENGINE.delete_image(body.get("name", ""), body.get("file", ""))
            return self._json({"ok": ok, "error": err})
        if p == "/api/open":
            target = DATA_DIR if body.get("what") == "root" else IMG_DIR
            target.mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(str(target))
            except Exception:
                pass
            return self._json({"ok": True})
        return self._send(404, "not found", "text/plain")


def listening_ports():
    """
    读本机监听端口表，返回正在监听的端口集合。
    比逐个 TCP 试连快得多；拿不到时返回 None，由调用方回退。
    """
    import subprocess
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        r = subprocess.run(["netstat.exe", "-ano", "-p", "TCP"],
                           capture_output=True, timeout=8,
                           creationflags=flags)
        text = (r.stdout or b"").decode("utf-8", "replace")
        ports = set()
        for line in text.splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            local = parts[1]
            if ":" not in local:
                continue
            tail = local.rsplit(":", 1)[1]
            if tail.isdigit():
                ports.add(int(tail))
        return ports or None
    except Exception:
        return None


def port_open(port, timeout=0.2):
    """
    先用 TCP 连接判断端口是否有人监听。
    空端口会立刻被拒绝，不必等 HTTP 超时——这是启动慢的关键。
    """
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_existing(port):
    """探测该端口上是否已有本工作台在运行（先探端口，再发 HTTP）。"""
    import urllib.request
    if not port_open(port):
        return False
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
        return "artist_count" in data and "phase" in data
    except Exception:
        return False


class ExclusiveServer(ThreadingHTTPServer):
    # Windows 默认允许端口重复绑定，会导致多个实例抢同一端口；
    # 关掉 SO_REUSEADDR 让重复绑定真正报错，从而触发换端口逻辑。
    allow_reuse_address = False


def set_console_icon():
    """给控制台窗口挂上应用图标，任务栏与 Alt-Tab 不再是默认黑框。"""
    if sys.platform != "win32":
        return
    ico = ROOT / "应用图标.ico"
    if not ico.is_file():
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
        for size, kind in ((16, ICON_SMALL), (32, ICON_BIG)):
            h = user32.LoadImageW(None, str(ico), IMAGE_ICON, size, size,
                                  LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(hwnd, WM_SETICON, kind, h)
        # 让任务栏按独立应用归组，而不是归到 python.exe
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Qianwen.ArtistWorkbench")
        except Exception:
            pass
    except Exception:
        pass


def wait_exit(code=0):
    """
    退出前留一句可见提示。
    双击运行时窗口会随进程关闭，不留提示用户只会看到「闪一下就没了」。
    """
    try:
        print()
        input("按回车键关闭本窗口…")
    except (EOFError, KeyboardInterrupt):
        pass
    return code


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    set_console_icon()

    # 已有实例在跑：打开它，并明确告知，而不是静默退出
    # 只探测真正在监听的端口，避免对空端口逐个等超时
    known = listening_ports()
    candidates = [p for p in range(PORT, PORT + 20)
                  if known is None or p in known]
    for port in candidates:
        if probe_existing(port):
            url = f"http://127.0.0.1:{port}/"
            print("=" * 52)
            print("工作台已经在运行了，本次没有重复启动。")
            print(f"访问地址：{url}")
            print("=" * 52)
            print("已为你打开浏览器。如果没弹出，把上面地址复制到浏览器即可。")
            print()
            print("想彻底重启：先关掉之前那个正在运行工作台的黑色窗口，")
            print("再双击本启动器。")
            try:
                webbrowser.open(url)
            except Exception:
                pass
            return wait_exit(0)

    srv = None
    used = PORT
    for port in range(PORT, PORT + 20):
        try:
            srv = ExclusiveServer(("127.0.0.1", port), Handler)
            used = port
            break
        except OSError:
            continue
    if srv is None:
        print(f"启动失败：{PORT}~{PORT + 19} 端口都被占用了。")
        print("请关闭占用这些端口的程序后重试。")
        return wait_exit(1)
    url = f"http://127.0.0.1:{used}/"
    if used != PORT:
        print(f"提示：{PORT} 已被占用，改用 {used}")
    print("=" * 52)
    print(f"工作台已启动：{url}")
    print("=" * 52)
    print("浏览器会自动打开。没弹出的话，把上面地址复制到浏览器即可。")
    print("用完直接关闭本窗口就退出。")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止工作台。")
    finally:
        try:
            srv.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    # 任何未预料到的异常都要显示出来，不能双击后一闪而过
    try:
        sys.exit(main() or 0)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        import traceback
        print("=" * 52)
        print("启动时出错了，详细信息如下：")
        print("=" * 52)
        traceback.print_exc()
        print()
        print("常见原因：缺少依赖库。可在本文件夹打开命令行执行：")
        print("  python -m pip install playwright pillow")
        try:
            input("按回车键关闭本窗口…")
        except (EOFError, KeyboardInterrupt):
            pass
        sys.exit(1)