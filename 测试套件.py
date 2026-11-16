# -*- coding: utf-8 -*-
"""
画师采集工作台 · 验收测试套件
覆盖：单元 / 边界 / 数据一致性 / 并发 / 安全 / 故障恢复 / 接口契约
所有测试在隔离临时目录进行，不触碰真实采集数据。
"""
import importlib.util
import json
import re
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.resolve()

RESULTS = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


E = load("engine_t", ROOT / "采集引擎.py")

CASES = []


def case(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ============ A. 文件名安全 ============
@case("A文件名", "Windows非法字符")
def a1():
    for ch in '\\/:*?"<>|':
        r = E.safe_name(f"画师{ch}名")
        check(ch not in r, f"非法字符 {ch} 未过滤: {r}")


@case("A文件名", "Windows保留设备名")
def a2():
    # CON/PRN/AUX/NUL/COM1..9/LPT1..9 在 Windows 上不能作为文件名
    bad = []
    for n in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con", "nul"]:
        r = E.safe_name(n)
        if r.upper() == n.upper():
            bad.append(n)
    check(not bad, f"保留设备名未处理: {bad}")


@case("A文件名", "结尾点与空格")
def a3():
    for n in ["画师.", "画师 ", "画师...", "画师 . "]:
        r = E.safe_name(n)
        check(not r.endswith((".", " ")), f"结尾非法: {n!r} -> {r!r}")


@case("A文件名", "空与纯符号")
def a4():
    for n in ["", "   ", "...", "///", None]:
        r = E.safe_name(n)
        check(r and r.strip(" ._"), f"空输入未兜底: {n!r} -> {r!r}")


@case("A文件名", "超长名截断")
def a5():
    r = E.safe_name("画" * 300)
    check(len(r) <= 40, f"未截断: {len(r)}")
    # 截断后不能以点/空格结尾
    check(not r.endswith((".", " ")), "截断后结尾非法")


@case("A文件名", "路径穿越字符")
def a6():
    r = E.safe_name("../../evil")
    check(".." not in r.replace(".", ""), f"穿越残留: {r}")
    check("/" not in r and "\\" not in r, f"分隔符残留: {r}")


@case("A文件名", "真实可创建")
def a7():
    with tempfile.TemporaryDirectory() as td:
        for n in ["CON", "画师?", "a" * 300, "..", "  ", "米室", "りたお"]:
            d = Path(td) / E.safe_name(n)
            d.mkdir(exist_ok=True)
            f = d / (E.safe_name(n) + "_01.jpg")
            f.write_bytes(b"x" * 10)
            check(f.exists(), f"无法创建: {n!r}")


# ============ B. 画师名解析 ============
@case("B解析", "空输入")
def b1():
    for t in ["", None, "   ", "\n\n"]:
        check(E.parse_artists(t or "", "") == [], f"空输入应返回空: {t!r}")


@case("B解析", "纯话题标签")
def b2():
    r = E.parse_artists("#画师推荐[话题]##插画[话题]##二次元[话题]#", "美图分享")
    check(r == [], f"纯标签不应产出画师: {r}")


@case("B解析", "真实样本回归")
def b3():
    samples = [
        ("美图分享 | 画师推荐", "画师：米室 #插画师推荐[话题]#", ["米室"]),
        ("【Zombie_KE】画师/作品推荐", "松弛的笔触 #光影[话题]#", ["Zombie_KE"]),
        ("插画推荐77", "りたお，日本插画师，PHASE STUDIO。", ["りたお"]),
        ("Vol.268", "今天推荐的插画师是X上的画师：あるてら ☾ 老师", ["あるてら"]),
        ("x", "画师：りすの #壁纸[话题]#", ["りすの"]),
    ]
    for title, desc, want in samples:
        got = [a["name"] for a in E.parse_artists(desc, title)]
        check(got == want, f"{title}: 期望{want} 实得{got}")


@case("B解析", "多画师顺序")
def b4():
    d = "1. 阿七 厚涂\n2. 小满 水彩\n3. 鹿野 日系"
    got = [a["name"] for a in E.parse_artists(d, "合集")]
    check(got == ["阿七", "小满", "鹿野"], f"顺序错: {got}")


@case("B解析", "同名去重")
def b5():
    d = "1. 阿七\n2. @阿七\n3. 阿七"
    got = [a["name"] for a in E.parse_artists(d, "")]
    check(len(got) == 1, f"未去重: {got}")


@case("B解析", "感叹句不误判")
def b6():
    d = "希望你也喜欢！！！Enjoy\n太牛了吧！！！"
    got = [a["name"] for a in E.parse_artists(d, "")]
    check(not any("喜欢" in x or "Enjoy" in x for x in got), f"误判: {got}")


@case("B解析", "画师推荐冒号写法")
def b9():
    """正文写「画师推荐：りたお」不能漏识别。"""
    d = "画师推荐：りたお\n看画有时候像开盲盒。\n#宝藏插画师[话题]#"
    got = [a["name"] for a in E.parse_artists(d, "破防了，每一张都想直接拿来做头像。")]
    check(got == ["りたお"], f"漏识别: {got}")
    for gap in ["推荐", "安利", "分享", "介绍", ""]:
        d2 = f"画师{gap}：测试名\n正文"
        r = [a["name"] for a in E.parse_artists(d2, "")]
        check(r == ["测试名"], f"「画师{gap}：」未识别: {r}")


@case("B解析", "同人社交账号归为别名")
def b10():
    """あるてら 与 @TeraAru6262 是同一人，不能拆成两位画师。"""
    d = ("今天推荐的插画师是X上的画师：あるてら ☾ 老师\n"
         "希望你也喜欢！！！Enjoy～～\n"
         "X （推特）：@TeraAru6262\n#分享[话题]#")
    r = E.parse_artists(d, "Vol.268｜画师推荐")
    check(len(r) == 1, f"被拆成多人: {[a['name'] for a in r]}")
    check(r[0]["name"] == "あるてら", f"主名错: {r[0]['name']}")
    check("TeraAru6262" in r[0].get("aliases", []), f"别名丢失: {r[0]}")
    plan = E.build_plan({"title": "Vol.268", "desc": d, "images": ["x"] * 17}, 1)
    check(all(x["confidence"] == "single" for x in plan), "同人应判为全篇一人")
    check(len({x["artist"] for x in plan}) == 1, "配对出现多个画师")


@case("B解析", "官方账号不算画师")
def b14():
    for nm in ["艺术薯", "薯队长", "薯条小助手", "小红书", "创作薯"]:
        check(E.clean_name(nm) is None, f"官方账号未过滤: {nm}")
    d = "作品很好看。\n@艺术薯 #画师推荐[话题]#"
    r = E.parse_artists(d, "美图分享")
    check(not any(a["name"] == "艺术薯" for a in r), f"官方号被当画师: {r}")


@case("B解析", "博主自我介绍不算画师")
def b16():
    """
    「我是@啊呜~，这里高清发布插画分享…」是发帖博主自我介绍。
    误收会让整篇被当成多画师合集，18 张图对半分并标记归属待确认。
    """
    d = ("画师：あるみっく\n"
         "✨ 我是@啊呜~，这里高清发布插画分享、画师推荐、绘画素材、成长记录。\n"
         "✨精心挑选国内外高质量插画，带你看不一样的好作品。\n"
         "✨版权归原作者所有\n🚫商改投喂侵删")
    r = E.parse_artists(d, "画师推荐No.350｜あるみっく｜审美积累")
    check([a["name"] for a in r] == ["あるみっく"], f"博主账号被当画师: {r}")
    check(not r[0].get("aliases"), f"博主账号被收为别名: {r[0]}")
    plan = E.build_plan({"title": "t", "desc": d, "images": ["x"] * 18}, 0)
    check(all(x["artist"] == "あるみっく" for x in plan), "归属被拆分")
    check(all(x["confidence"] == "single" for x in plan),
          f"单人帖不应判为推测: {set(x['confidence'] for x in plan)}")
    # 不能误伤真实多画师合集与正常推荐
    got = [a["name"] for a in E.parse_artists(
        "1. 阿七 厚涂\n2. 小满 水彩\n3. 鹿野 日系", "合集")]
    check(got == ["阿七", "小满", "鹿野"], f"真多画师被误过滤: {got}")
    for d2, want in [("画师：米室\n我是@薯队长，欢迎关注", ["米室"]),
                     ("画师：りすの\n版权归原作者所有\n侵删", ["りすの"])]:
        got2 = [a["name"] for a in E.parse_artists(d2, "x")]
        check(got2 == want, f"{d2!r} 解析错: {got2}")


@case("B解析", "缩写署名illus可识别")
def b17():
    """「illus：BwPuppy」是稿件展示帖常见署名，漏识别会整篇落进待认领。"""
    d = "illus：BwPuppy\n#画师推荐[话题]# #稿件展示[话题]#"
    r = E.parse_artists(d, "银十字常驻画师推荐")
    check([a["name"] for a in r] == ["BwPuppy"], f"缩写署名未识别: {r}")
    plan = E.build_plan({"title": "t", "desc": d, "images": ["x"] * 3}, 0)
    check(all(x["artist"] == "BwPuppy" for x in plan), "未归到正确画师")
    check(all(x["confidence"] == "single" for x in plan), "单人帖应判为确定")
    for t, want in [("illust: abc", ["abc"]), ("ILLUSTRATOR：xyz", ["xyz"])]:
        got = [a["name"] for a in E.parse_artists(t, "")]
        check(got == want, f"{t!r} 解析错: {got}")


@case("B解析", "标题分隔符后取画师名")
def b15():
    d = ("◽️Blanc.ブラン是一位活跃于网络平台的女性概念艺术家与插画师。\n"
         "@艺术薯 #艺术热夏[话题]#")
    r = E.parse_artists(d, "🫧艺术家分享｜Blanc.ブラン")
    check([a["name"] for a in r] == ["Blanc.ブラン"], f"标题取名失败: {r}")


@case("B解析", "账号行多种写法均归别名")
def b12():
    """X 后带空格、带emoji、小写x 等写法都要识别为账号行。"""
    for line in ["X ：@abc", "X：@abc", "X（推特）：@abc", "x：@abc",
                 "📱 x：@abc", "推特：@abc", "ins：@abc", "pixiv：@abc",
                 "微博：@abc", "lofter：@abc"]:
        d = "画师：测试名\n" + line
        r = E.parse_artists(d, "")
        check(len(r) == 1, f"{line!r} 被拆成多人: {[a['name'] for a in r]}")
        check("abc" in r[0].get("aliases", []),
              f"{line!r} 未收为别名: {r[0]}")


@case("B解析", "真实案例猫屋敷同人")
def b13():
    d = ("今天推荐的插画师是X上的画师：猫屋敷ぷしお 老师\n好看！！\n"
         "X ：@neko_pushio\n#二次元[话题]#")
    r = E.parse_artists(d, "Vol.241｜画师推荐")
    check(len(r) == 1, f"同人被拆: {[a['name'] for a in r]}")
    check(r[0]["name"] == "猫屋敷ぷしお", f"主名错: {r[0]['name']}")
    check("neko_pushio" in r[0]["aliases"], "别名丢失")


@case("B解析", "多画师时账号不误并")
def b11():
    """真正的多画师合集里，不能把第二个人误当别名吞掉。"""
    d = "1. 阿七 厚涂\n2. 小满 水彩\n3. 鹿野 日系"
    r = E.parse_artists(d, "合集")
    check(len(r) == 3, f"多画师被误并: {[a['name'] for a in r]}")


@case("B解析", "超长正文性能")
def b7():
    d = ("画师：测试\n#标签[话题]#\n" * 2000)
    t0 = time.time()
    E.parse_artists(d, "标题")
    el = time.time() - t0
    check(el < 3.0, f"解析过慢: {el:.2f}s")


@case("B解析", "畸形标签不崩溃")
def b8():
    for d in ["#" * 500, "#未闭合[话题]", "#a[话题]#" * 200, "画师：\n\n"]:
        E.parse_artists(d, "#" * 100)


# ============ C. 配对逻辑 ============
@case("C配对", "零图片")
def c1():
    check(E.build_plan({"desc": "画师：甲", "images": []}, 1) == [], "零图应返回空")


@case("C配对", "画师多于图片")
def c2():
    n = {"title": "", "desc": "1. 甲\n2. 乙\n3. 丙\n4. 丁", "images": ["a", "b"]}
    p = E.build_plan(n, 1)
    check(len(p) == 2, f"图片数不符: {len(p)}")
    check(all(x["confidence"] in ("guess", "explicit") for x in p), "应标记为推测")


@case("C配对", "单画师多图")
def c3():
    n = {"title": "", "desc": "画师：米室", "images": ["a"] * 12}
    p = E.build_plan(n, 1)
    check(len(p) == 12 and all(x["artist"] == "米室" for x in p), "单画师分配错")
    check(all(x["confidence"] == "single" for x in p), "可信度应为single")


@case("C配对", "显式图序优先")
def c4():
    n = {"title": "", "desc": "1. 甲\n2. 乙\n图1-2 乙\n图3 甲",
         "images": ["a", "b", "c"]}
    p = E.build_plan(n, 1)
    got = [(x["artist"], x["confidence"]) for x in p]
    check(got == [("乙", "explicit"), ("乙", "explicit"), ("甲", "explicit")],
          f"显式图序未生效: {got}")


@case("C配对", "图序越界不崩溃")
def c5():
    n = {"title": "", "desc": "1. 甲\n2. 乙\n图99 甲\n图0 乙\n图2-999 甲",
         "images": ["a", "b"]}
    p = E.build_plan(n, 1)
    check(len(p) == 2, "越界图序导致数量错")


@case("C配对", "无画师进待认领")
def c6():
    n = {"title": "日常", "desc": "随便画画", "images": ["a"]}
    p = E.build_plan(n, 1)
    check(p[0]["artist"] == "待认领" and p[0]["confidence"] == "unknown", "兜底错")


@case("C配对", "序号连续")
def c7():
    n = {"title": "", "desc": "画师：甲", "images": list("abcdef")}
    p = E.build_plan(n, 1)
    check([x["seq"] for x in p] == [1, 2, 3, 4, 5, 6], "seq不连续")


# ============ D. 工作台数据层 ============
def make_wb(td):
    """
    在隔离目录构造一个工作台实例。
    凭证与账号配置也必须隔离：否则模块加载时会读到真实凭证，
    导致测试真的去联网请求 D 站。
    """
    base = Path(td)
    wb = load("wb_t_" + str(int(time.time() * 1000))[-6:], ROOT / "工作台.py")
    wb.ROOT = base
    wb.DATA_DIR = base / "采集结果"
    wb.IMG_DIR = wb.DATA_DIR / "画师图片"
    wb.DATA_FILE = wb.DATA_DIR / "data.json"
    wb.PROFILE = base / "_profile"
    wb.ACCOUNTS_DIR = base / "_accounts"
    wb.ACCOUNTS_FILE = base / "账号.json"
    wb.CRED_FILE = base / "d站凭证.json"
    wb.SAUCE_FILE = base / "搜图凭证.json"
    wb.SAUCE_CACHE_FILE = base / "搜图缓存.json"
    # 搜图额度台账也要隔离，否则测试会消耗真实画师的额度记录
    wb.SAUCE_LEDGER_FILE = base / "搜图台账.json"
    # 归属冲突记录也要隔离，否则测试会读写真实冲突清单
    wb.CONFLICT_FILE = base / "归属冲突.json"
    # 语义映射同样要隔离：否则测试会读到真实映射表，结果不可控。
    # Engine() 在 make_wb 之后才创建，此时设路径即可生效。
    wb.SEMANTIC_FILE = base / "语义映射.json"
    # 模块级单例在加载时已读过真实凭证，这里强制清空
    wb.DANBOORU._login = ""
    wb.DANBOORU._key = ""
    wb.DANBOORU.CRED_FILE = wb.CRED_FILE
    wb.SAUCENAO._key = ""
    wb.SAUCENAO._calls = []
    wb.SAUCENAO._day_used = 0
    wb.IMG_DIR.mkdir(parents=True, exist_ok=True)
    return wb


class FakeResp:
    def __init__(self, body, status=200):
        self._b, self.status = body, status

    def body(self):
        return self._b


class FakeCtx:
    """模拟浏览器下载：每张图给出可区分的内容。"""
    def __init__(self):
        self.calls = []
        outer = self

        class R:
            def get(self, url, **kw):
                outer.calls.append(url)
                return FakeResp(b"\xff\xd8\xff" + url.encode() + b"x" * 3000)
        self.request = R()


def seed(wb, eng, name, n, style="", conf="single"):
    """涉及本地文件的用例：显式开启备份模式。"""
    eng.save_local = True
    note = {"title": f"{name}的帖子", "author": "作者", "desc": "", "url": f"http://n/{name}"}
    plan = [{"artist": name, "style": style, "image_url": f"http://img/{name}/{i}",
             "seq": i + 1, "confidence": conf} for i in range(n)]
    return eng._ingest(FakeCtx(), note, plan, note["url"])


@case("D数据", "入库与落盘一致")
def d1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        got = seed(wb, eng, "米室", 3)
        check(got == 3, f"入库数错: {got}")
        rec = eng.artists["米室"]
        for im in rec["images"]:
            f = wb.ROOT / im["file"]
            check(f.is_file(), f"记录指向不存在的文件: {im['file']}")


@case("D数据", "跨帖去重")
def d2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ctx = FakeCtx()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        plan = [{"artist": "甲", "style": "", "image_url": "http://img/same?x=1",
                 "seq": 1, "confidence": "single"}]
        n1 = eng._ingest(ctx, note, plan, "http://n/1")
        plan2 = [{"artist": "甲", "style": "", "image_url": "http://img/same?x=2",
                  "seq": 1, "confidence": "single"}]
        n2 = eng._ingest(ctx, note, plan2, "http://n/2")
        check(n1 == 1 and n2 == 0, f"去重失效: {n1},{n2}")


@case("D数据", "签名变化仍判为同图")
def d2b():
    """小红书图片URL带时间戳+随机签名，同一张图不能重复入库。"""
    base = "http://sns-webpic-qc.xhscdn.com"
    u1 = f"{base}/202611131134/aaa111/spectrum/1040g0k03221a18sb704g5o!nd_dft_wlteh_webp_3"
    u2 = f"{base}/202611131156/bbb222/spectrum/1040g0k03221a18sb704g5o!nd_dft_wlteh_webp_3"
    check(E.image_key(u1) == E.image_key(u2), "同图不同签名未识别为同一张")
    u3 = f"{base}/202611131156/ccc333/spectrum/DIFFERENT_IMAGE_ID!nd_dft"
    check(E.image_key(u1) != E.image_key(u3), "不同图被误判为同一张")
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        p1 = [{"artist": "甲", "style": "", "image_url": u1, "seq": 1,
               "confidence": "single"}]
        p2 = [{"artist": "甲", "style": "", "image_url": u2, "seq": 1,
               "confidence": "single"}]
        n1 = eng._ingest(FakeCtx(), note, p1, "http://n/1")
        n2 = eng._ingest(FakeCtx(), note, p2, "http://n/2")
        check(n1 == 1 and n2 == 0, f"跨轮次去重失效: {n1},{n2}")


@case("D数据", "删图后编号不撞车")
def d3():
    """删掉中间一张后再入库，新文件不能覆盖已有图。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 3)
        files_before = {im["file"]: (wb.ROOT / im["file"]).read_bytes()
                        for im in eng.artists["甲"]["images"]}
        # 物理删除第2张，模拟用户手动清理
        victim = list(files_before)[1]
        (wb.ROOT / victim).unlink()
        eng.artists["甲"]["images"] = [
            im for im in eng.artists["甲"]["images"] if im["file"] != victim]
        # 再入库2张新图
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/9"}
        plan = [{"artist": "甲", "style": "", "image_url": f"http://img/new/{i}",
                 "seq": i, "confidence": "single"} for i in range(2)]
        eng._ingest(FakeCtx(), note, plan, "http://n/9")
        for f, content in files_before.items():
            p = wb.ROOT / f
            if p.exists() and f != victim:
                check(p.read_bytes() == content, f"已有图片被覆盖: {f}")
        for im in eng.artists["甲"]["images"]:
            check((wb.ROOT / im["file"]).is_file(), f"记录悬空: {im['file']}")


@case("D数据", "改名保留图片")
def d4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "旧名", 2)
        ok, err = eng.rename_artist("旧名", "新名")
        check(ok, err)
        check("旧名" not in eng.artists and "新名" in eng.artists, "改名未生效")
        for im in eng.artists["新名"]["images"]:
            check((wb.ROOT / im["file"]).is_file(), "改名后图片丢失")


@case("D数据", "改名合并两人")
def d5():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "あるてら", 3)
        seed(wb, eng, "TeraAru", 2)
        ok, err = eng.rename_artist("TeraAru", "あるてら")
        check(ok, err)
        check(len(eng.artists) == 1, f"未合并: {list(eng.artists)}")
        check(len(eng.artists["あるてら"]["images"]) == 5, "合并后图片数错")


@case("D数据", "移图后目录与归属一致")
def d6():
    """把图移给别的画师后，文件应真的在新画师目录下。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 2)
        f = eng.artists["甲"]["images"][0]["file"]
        ok, err = eng.move_image("甲", f, "乙")
        check(ok, err)
        rec = eng.artists["乙"]["images"][0]
        p = wb.ROOT / rec["file"]
        check(p.is_file(), f"移动后文件不存在: {rec['file']}")
        check("乙" in str(p.parent), f"文件仍在旧画师目录: {p.parent.name}")


@case("D数据", "移空后不留空壳")
def d7():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 1)
        f = eng.artists["甲"]["images"][0]["file"]
        eng.move_image("甲", f, "乙")
        check("甲" not in eng.artists, "空画师未清理")


@case("D数据", "非法操作返回错误")
def d8():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        for ok, err in [eng.rename_artist("无", "x"), eng.rename_artist("无", ""),
                        eng.delete_artist("无"), eng.move_image("无", "f", "y"),
                        eng.move_image("无", "f", ""), eng.delete_image("无", "f")]:
            check(ok is False and err, "非法操作应返回错误")


@case("D数据", "持久化往返")
def d9():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "米室", 2, style="厚涂")
        eng.save()
        eng2 = wb.Engine()
        check("米室" in eng2.artists, "重启后数据丢失")
        check(len(eng2.artists["米室"]["images"]) == 2, "重启后图片数错")


@case("D数据", "损坏清单不崩溃")
def d10():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DATA_FILE.write_text("{坏掉的JSON", encoding="utf-8")
        eng = wb.Engine()
        check(eng.artists == {}, "损坏数据应安全降级")


@case("D数据", "写盘原子性")
def d11():
    """save 过程中断不应留下半截文件。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 2)
        eng.save()
        good = wb.DATA_FILE.read_text(encoding="utf-8")
        tmps = list(wb.DATA_DIR.glob("*.tmp")) + list(wb.DATA_DIR.glob("*.part"))
        check(not tmps, f"残留临时文件: {[t.name for t in tmps]}")
        check(json.loads(good)["artists"], "内容不完整")


@case("D数据", "并发入库不丢数据")
def d12():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        errs = []

        def work(k):
            try:
                for j in range(6):
                    note = {"title": "t", "author": "a", "desc": "", "url": f"u{k}{j}"}
                    plan = [{"artist": f"画师{k}", "style": "",
                             "image_url": f"http://i/{k}/{j}", "seq": j,
                             "confidence": "single"}]
                    eng._ingest(FakeCtx(), note, plan, note["url"])
                    eng.save()
            except Exception as ex:
                errs.append(repr(ex))

        ts = [threading.Thread(target=work, args=(k,)) for k in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check(not errs, f"并发异常: {errs[:2]}")
        total = sum(len(a["images"]) for a in eng.artists.values())
        check(total == 30, f"并发丢数据: {total}/30")
        json.loads(wb.DATA_FILE.read_text(encoding="utf-8"))


# ============ I. 重名与同人合并 ============
def ingest_one(eng, name, url, style="", aliases=None, conf="single"):
    eng.save_local = True   # 重名用例需覆盖文件夹归属，故启用本地备份
    note = {"title": f"{name}帖", "author": "a", "desc": "", "url": "http://n/" + url}
    plan = [{"artist": name, "style": style, "image_url": "http://img/" + url,
             "seq": 1, "confidence": conf, "aliases": aliases or []}]
    return eng._ingest(FakeCtx(), note, plan, note["url"])


@case("I重名", "同名跨帖合并为一人")
def i1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "米室", "a1")
        ingest_one(eng, "米室", "a2")
        check(len(eng.artists) == 1, f"同名被拆开: {list(eng.artists)}")
        check(len(eng.artists["米室"]["images"]) == 2, "同名图片未累积")


@case("I重名", "大小写不同视为同人")
def i2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "kieed", "b1")
        ingest_one(eng, "Kieed", "b2")
        check(len(eng.artists) == 1, f"大小写变体被拆成两人: {list(eng.artists)}")


@case("I重名", "首尾空格与@前缀视为同人")
def i3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "阿七", "c1")
        ingest_one(eng, " 阿七 ", "c2")
        ingest_one(eng, "@阿七", "c3")
        check(len(eng.artists) == 1, f"空格/@变体被拆开: {list(eng.artists)}")


@case("I重名", "别名跨帖反向出现应合并")
def i4():
    """A帖主名あるてら+别名TeraAru；B帖直接写TeraAru，应并入同一人。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "あるてら", "d1", aliases=["TeraAru6262"])
        ingest_one(eng, "TeraAru6262", "d2")
        check(len(eng.artists) == 1,
              f"别名反向出现被拆成两人: {list(eng.artists)}")


@case("I重名", "不同画师不得误并")
def i5():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "米室", "e1")
        ingest_one(eng, "りすの", "e2")
        ingest_one(eng, "kieed", "e3")
        check(len(eng.artists) == 3, f"不同画师被误并: {list(eng.artists)}")


@case("I重名", "改名大小写变体应合并")
def i6():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "kieed", "f1")
        ingest_one(eng, "其他", "f2")
        ok, err = eng.rename_artist("其他", "KIEED")
        check(ok, err)
        check(len(eng.artists) == 1, f"改名未识别同人: {list(eng.artists)}")


@case("I重名", "移图到别名应并入本人")
def i7():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "あるてら", "g1", aliases=["TeraAru6262"])
        ingest_one(eng, "散图", "g2")
        f = eng.artists["散图"]["images"][0]["file"]
        ok, err = eng.move_image("散图", f, "TeraAru6262")
        check(ok, err)
        check(len(eng.artists) == 1, f"移到别名却新建了人: {list(eng.artists)}")


@case("I重名", "文件夹名撞车不混图")
def i8():
    """两位不同画师的名字净化后可能同名，图片不能混进同一目录。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "A/B", "h1")
        ingest_one(eng, "A?B", "h2")
        dirs = set()
        for a in eng.artists.values():
            for im in a["images"]:
                dirs.add(str((wb.ROOT / im["file"]).parent))
                check((wb.ROOT / im["file"]).is_file(), "文件丢失")
        check(len(eng.artists) == 2, f"画师被误并: {list(eng.artists)}")
        check(len(dirs) == 2, f"两位画师共用同一目录: {dirs}")


@case("I重名", "同目录文件名不覆盖")
def i9():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        for k in range(6):
            ingest_one(eng, "米室", f"i{k}")
        files = [im["file"] for im in eng.artists["米室"]["images"]]
        check(len(set(files)) == 6, f"文件名重复导致覆盖: {files}")
        for f in files:
            check((wb.ROOT / f).is_file(), f"文件缺失: {f}")


@case("I重名", "重启后不产生重复条目")
def i10():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "米室", "j1")
        eng.save()
        eng2 = wb.Engine()
        ingest_one(eng2, "米室", "j2")
        check(len(eng2.artists) == 1, f"重启后同名分裂: {list(eng2.artists)}")


@case("I重名", "真实数据无近似重名")
def i11():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    seen = {}
    clash = []
    for a in d["artists"]:
        k = a["name"].strip().lstrip("@").lower()
        if k in seen:
            clash.append((seen[k], a["name"]))
        seen[k] = a["name"]
        for al in a.get("aliases", []):
            ak = al.strip().lstrip("@").lower()
            if ak in seen and seen[ak] != a["name"]:
                clash.append((seen[ak], a["name"] + "(别名" + al + ")"))
            seen[ak] = a["name"]
    check(not clash, f"存在近似重名: {clash}")


# ============ K. 在线图廊 ============
@case("K在线", "链接统一为https")
def k1():
    check(E.https_url("http://a.com/x.jpg") == "https://a.com/x.jpg", "http未升级")
    check(E.https_url("//a.com/x.jpg") == "https://a.com/x.jpg", "协议相对未处理")
    check(E.https_url("https://a.com/x") == "https://a.com/x", "https被改写")
    check(E.https_url("") == "" and E.https_url(None) == "", "空值未兜底")


@case("K在线", "签名链接转永久链接")
def k10():
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
              "abc123def456/spectrum/IMAGE_ID_0001!nd_dft_wlteh_webp_3")
    p = E.permanent_url(signed)
    check("sns-img-qc.xhscdn.com" in p, f"域名未替换: {p}")
    check("202611131134" not in p, f"时间戳未去掉: {p}")
    check("abc123def456" not in p, f"签名未去掉: {p}")
    check("/spectrum/IMAGE_ID_0001" in p, f"路径或ID丢失: {p}")
    check(p.endswith(E.PERM_FMT), f"缺格式参数（会返回HEIC）: {p}")
    check(p.startswith("https://"), "未用https")


@case("K在线", "无中间路径段也能转")
def k11():
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131156/"
              "24290f3bf69c/IMAGE_ID_0002!nd_dft_wlteh_webp_3")
    p = E.permanent_url(signed)
    check(E.is_permanent(p), f"无路径段未转换: {p}")
    check(p.endswith("IMAGE_ID_0002" + E.PERM_FMT), f"ID或参数错: {p}")


@case("K在线", "转换幂等")
def k12():
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
              "sig/spectrum/IDEMPOTENT_ID!x")
    p1 = E.permanent_url(signed)
    p2 = E.permanent_url(p1)
    check(p1 == p2, f"重复转换结果不一致:\n{p1}\n{p2}")


@case("K在线", "非图床链接不动")
def k13():
    for u in ["https://example.com/a.jpg", "http://other.cdn/x/y.png"]:
        p = E.permanent_url(u)
        check("sns-img-qc" not in p, f"外部链接被误改: {u} -> {p}")
    check(E.permanent_url("") == "" and E.permanent_url(None) == "", "空值未兜底")


@case("K在线", "永久判定准确")
def k14():
    check(E.is_permanent("https://sns-img-qc.xhscdn.com/spectrum/ID123!x"), "永久链接误判")
    check(not E.is_permanent(
        "https://sns-webpic-qc.xhscdn.com/202611131134/sig/spectrum/ID123!x"),
        "签名链接被误判为永久")


@case("K在线", "入库即存永久链接")
def k15():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
                  "sigx/spectrum/INGEST_ID_01!x")
        plan = [{"artist": "甲", "style": "", "image_url": signed, "seq": 1,
                 "confidence": "single"}]
        eng._ingest(FakeCtx(), note, plan, "http://n/1")
        im = eng.artists["甲"]["images"][0]
        check(E.is_permanent(im["src"]), f"入库未存永久链接: {im['src']}")
        check(im.get("orig") == signed, "原始链接未保留")


@case("K在线", "真实数据全为永久链接")
def k16():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    bad = [im["src"] for a in d["artists"] for im in a["images"]
           if not E.is_permanent(im.get("src", ""))]
    check(not bad, f"{len(bad)} 条仍是签名链接")


@case("K在线", "旧清单加载即升级为永久链接")
def k17():
    """历史 data.json 里的签名链接会过期，加载时必须换掉并落盘。"""
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
              "oldsig/spectrum/LEGACY_ID_01!x")
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DATA_DIR.mkdir(parents=True, exist_ok=True)
        wb.DATA_FILE.write_text(json.dumps({"artists": [{
            "name": "旧画师", "images": [{"src": signed, "file": "", "conf": "single"}],
        }]}, ensure_ascii=False), encoding="utf-8")
        eng = wb.Engine()
        im = eng.artists["旧画师"]["images"][0]
        check(E.is_permanent(im["src"]), f"加载未升级链接: {im['src']}")
        check(im.get("key"), "未补齐去重键")
        # 必须落盘，否则下次启动又要重转
        saved = json.loads(wb.DATA_FILE.read_text(encoding="utf-8"))
        check(E.is_permanent(saved["artists"][0]["images"][0]["src"]),
              "升级后未写回清单")


@case("K在线", "src为空时用orig兜底")
def k18():
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
              "sig/spectrum/FALLBACK_ID!x")
    im = {"src": "", "orig": signed}
    check(E.normalize_image(im), "应报告发生改动")
    check(E.is_permanent(im["src"]), f"未用orig兜底: {im['src']}")
    # 已是永久链接时不应重复报改动
    check(not E.normalize_image(im), "幂等性失败：无改动却报改动")
    check(not E.normalize_image(None) and not E.normalize_image("x"),
          "非法输入未兜底")


@case("K在线", "撤销还原也走永久链接")
def k19():
    signed = ("http://sns-webpic-qc.xhscdn.com/202611131134/"
              "sig/spectrum/UNDO_ID_01!x")
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ok, err = eng.restore_image("甲", {"src": signed, "file": ""})
        check(ok, err)
        check(E.is_permanent(eng.artists["甲"]["images"][0]["src"]),
              "撤销单图未升级链接")
        ok, err = eng.restore_artist({
            "name": "乙",
            "images": [{"src": signed.replace("UNDO_ID_01", "UNDO_ID_02"),
                        "file": ""}]})
        check(ok, err)
        rec = eng.artists["乙"]
        check(rec["name"] == "乙" and len(rec["images"]) == 1,
              f"还原记录字段丢失: {rec}")
        check(E.is_permanent(rec["images"][0]["src"]), "撤销画师未升级链接")


@case("K在线", "默认不下载图片")
def k2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        check(eng.save_local is False, "默认应为在线模式")
        ctx = FakeCtx()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        plan = [{"artist": "甲", "style": "", "image_url": "http://img/x/1",
                 "seq": 1, "confidence": "single"}]
        n = eng._ingest(ctx, note, plan, "http://n/1")
        check(n == 1, f"在线模式入库失败: {n}")
        check(not ctx.calls, f"在线模式仍发起了下载: {ctx.calls}")
        im = eng.artists["甲"]["images"][0]
        check(im["src"].startswith("https://"), f"链接未升级: {im['src']}")
        check(im["file"] == "", "在线模式不应写本地路径")
        files = list(wb.IMG_DIR.rglob("*.*"))
        check(not files, f"在线模式仍落盘: {files}")


@case("K在线", "勾选备份时才下载")
def k3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.save_local = True
        ctx = FakeCtx()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        plan = [{"artist": "甲", "style": "", "image_url": "http://img/y/1",
                 "seq": 1, "confidence": "single"}]
        eng._ingest(ctx, note, plan, "http://n/1")
        check(len(ctx.calls) == 1, "备份模式未下载")
        im = eng.artists["甲"]["images"][0]
        check(im["file"] and (wb.ROOT / im["file"]).is_file(), "备份文件缺失")


@case("K在线", "在线模式去重仍生效")
def k4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        base = "http://sns-webpic-qc.xhscdn.com"
        u1 = f"{base}/202611131134/aaa/spectrum/STABLE_ID_001!x"
        u2 = f"{base}/202611131999/bbb/spectrum/STABLE_ID_001!x"
        for u, url in [(u1, "http://n/1"), (u2, "http://n/2")]:
            plan = [{"artist": "甲", "style": "", "image_url": u, "seq": 1,
                     "confidence": "single"}]
            eng._ingest(FakeCtx(), note, plan, url)
        check(len(eng.artists["甲"]["images"]) == 1, "在线模式去重失效")


@case("K在线", "在线模式可移图")
def k8():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        for nm, u in [("甲", "http://img/online/1"), ("乙", "http://img/online/2")]:
            plan = [{"artist": nm, "style": "", "image_url": u, "seq": 1,
                     "confidence": "single"}]
            eng._ingest(FakeCtx(), note, plan, "http://n/" + nm)
        im = eng.artists["甲"]["images"][0]
        check(im["file"] == "", "在线模式不应有本地路径")
        ok, err = eng.move_image("甲", im["key"], "丙")
        check(ok, f"在线模式移图失败: {err}")
        check("丙" in eng.artists and "甲" not in eng.artists, "归属未更新")


@case("K在线", "在线模式可删图")
def k9():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        plan = [{"artist": "甲", "style": "", "image_url": "http://img/online/9",
                 "seq": 1, "confidence": "single"}]
        eng._ingest(FakeCtx(), note, plan, "http://n/1")
        im = eng.artists["甲"]["images"][0]
        ok, err = eng.delete_image("甲", im["key"])
        check(ok, f"在线模式删图失败: {err}")
        check("甲" not in eng.artists, "空画师未清理")


@case("K在线", "前端带no-referrer")
def k5():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("no-referrer" in html, "缺少 no-referrer，图床会拒绝本机Referer")
    check("imgSrc" in html, "缺少在线链接优先逻辑")
    check("imgFail" in html, "缺少加载失败兜底")
    check("data-local" in html, "缺少本地备份兜底路径")


@case("K在线", "例图上限默认10且可调")
def k17():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check('id="perArtist"' in html, "缺少例图数量输入框")
    check('value="10"' in html, "默认值应为10")
    check("function perCap" in html and "function capImgs" in html,
          "缺少上限读取/裁剪函数")
    # 卡片与图廊都必须走上限
    check("capImgs(imgs)" in html, "卡片未应用上限")
    check("capImgs(a.images || [])" in html, "图廊未应用上限")


@case("K在线", "上限只影响显示不删数据")
def k18():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    # 裁剪只能出现在渲染层，不得调用删除接口
    seg = html[html.find("function capImgs"):html.find("function capImgs") + 260]
    check("slice" in seg, "裁剪实现异常")
    for danger in ["delete_image", "delete_artist", "splice", "pop("]:
        check(danger not in seg, f"显示裁剪里混入了删除操作: {danger}")
    # 灯箱仍展示全部
    lb = html[html.find("function openLB"):html.find("function reopenLB")]
    check("(a.images||[]).map" in lb or "(a.images || []).map" in lb,
          "灯箱应展示全部图片而非裁剪后的")
    check("capImgs" not in lb, "灯箱不应受显示上限限制")


@case("K在线", "上限为0表示全部")
def k19():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("n === 0 ? arr" in html, "0 应表示展示全部")
    check("min=\"0\"" in html, "输入框应允许填0")


@case("K在线", "卡片标明展示数与总数")
def k20():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("${show.length}/${imgs.length}" in html, "未区分展示数与总数")


@case("K在线", "图廊视图存在")
def k6():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ["renderGallery", "viewGal", "gallery", "applyView", "saveLocal"]:
        check(k in html, f"图廊缺少要素: {k}")


@case("K在线", "真实数据链接可在线用")
def k7():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    bad = [im["src"] for a in d["artists"] for im in a["images"]
           if not str(im.get("src", "")).startswith("https://")]
    check(not bad, f"{len(bad)} 条链接不是https，无法在线加载")


# ============ M. 撤销与取色 ============
@case("M撤销", "移除后可完整还原")
def m1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 3, style="厚涂")
        snap = json.loads(json.dumps(eng.artists["甲"]))
        ok, _ = eng.delete_artist("甲")
        check(ok and "甲" not in eng.artists, "移除失败")
        ok, err = eng.restore_artist(snap)
        check(ok, f"还原失败: {err}")
        check(len(eng.artists["甲"]["images"]) == 3, "还原后图片数不符")
        check(eng.artists["甲"]["styles"] == ["厚涂"], "风格未还原")


@case("M撤销", "重复还原不产生重复")
def m2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 2)
        snap = json.loads(json.dumps(eng.artists["甲"]))
        eng.delete_artist("甲")
        eng.restore_artist(snap)
        eng.restore_artist(snap)
        check(len(eng.artists) == 1, f"重复还原产生多条: {list(eng.artists)}")
        check(len(eng.artists["甲"]["images"]) == 2, "重复还原导致图片翻倍")


@case("M撤销", "还原走身份归并")
def m3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "kieed", 2)
        snap = json.loads(json.dumps(eng.artists["kieed"]))
        eng.delete_artist("kieed")
        seed(wb, eng, "KIEED", 1)      # 大小写变体先占了位
        snap["name"] = "kieed"
        ok, err = eng.restore_artist(snap)
        check(ok, err)
        check(len(eng.artists) == 1, f"还原未归并: {list(eng.artists)}")


@case("M撤销", "单图还原")
def m4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 3)
        im = json.loads(json.dumps(eng.artists["甲"]["images"][1]))
        ok, _ = eng.delete_image("甲", im["file"])
        check(ok and len(eng.artists["甲"]["images"]) == 2, "删图失败")
        ok, err = eng.restore_image("甲", im)
        check(ok, f"还原图失败: {err}")
        check(len(eng.artists["甲"]["images"]) == 3, "还原后数量不符")


@case("M撤销", "非法还原数据被拒")
def m5():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        for bad in [None, {}, {"name": ""}, {"name": "  "}, []]:
            ok, err = eng.restore_artist(bad)
            check(ok is False and err, f"非法数据未被拒: {bad}")
        ok, err = eng.restore_image("甲", None)
        check(ok is False and err, "非法图片数据未被拒")


@case("M撤销", "前端撤销要素齐备")
def m6():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ["offerUndo", "toastUndo", "restore_artist", "restore_image", "hideToast"]:
        check(k in html, f"缺少撤销要素: {k}")
    # 移除画师不应再用阻塞式 confirm
    seg = html[html.find("data-act === 'rename'"):html.find("// 在线图廊")]
    check("confirm(" not in seg, "移除画师仍用阻塞确认，未改为可撤销")


@case("M取色", "取色返回合法RGB")
def m7():
    from PIL import Image
    import io
    buf = io.BytesIO()
    im = Image.new("RGB", (40, 40))
    for x in range(40):
        for y in range(40):
            im.putpixel((x, y), (200, 60, 90) if x < 20 else (40, 120, 210))
    im.save(buf, format="PNG")
    cols = E.dominant_colors(buf.getvalue())
    check(cols, "未取到颜色")
    for c in cols:
        check(len(c) == 3 and all(0 <= v <= 255 for v in c), f"非法RGB: {c}")


@case("M取色", "坏数据不崩溃")
def m8():
    for bad in [b"", b"not an image", None, b"\x00" * 100]:
        check(E.dominant_colors(bad) == [], f"坏数据应返回空: {bad!r}")


@case("M取色", "纯灰图返回空")
def m9():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), (128, 128, 128)).save(buf, format="PNG")
    check(E.dominant_colors(buf.getvalue()) == [], "纯灰应被过滤")


# ============ L. 启动与端口 ============
@case("L启动", "bat必须CRLF换行")
def l1():
    p = ROOT / "启动工作台.bat"
    check(p.is_file(), "启动脚本缺失")
    b = p.read_bytes()
    lf_only = b.count(b"\n") - b.count(b"\r\n")
    check(lf_only == 0, f"存在 {lf_only} 处纯LF换行，Windows批处理会解析错乱")
    check(b.count(b"\r\n") > 0, "未使用CRLF换行")


@case("L启动", "bat内容纯ASCII")
def l2():
    b = (ROOT / "启动工作台.bat").read_bytes()
    non_ascii = [i for i, x in enumerate(b) if x >= 128]
    check(not non_ascii,
          f"含 {len(non_ascii)} 个非ASCII字节，GBK控制台下中文会被截断")


@case("L启动", "bat调用的入口存在")
def l3():
    txt = (ROOT / "启动工作台.bat").read_bytes().decode("ascii")
    import re as _re
    m = _re.search(r'"%~dp0([\w.]+\.py)"', txt)
    check(m, "未找到脚本调用语句")
    entry = ROOT / m.group(1)
    check(entry.is_file(), f"入口文件不存在: {m.group(1)}")
    check((ROOT / "工作台.py").is_file(), "主程序缺失")


@case("L启动", "端口禁止重复绑定")
def l4():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("allow_reuse_address = False" in src,
          "未关闭端口复用，Windows下多实例会抢同一端口")
    check("ExclusiveServer((" in src, "启动未使用独占端口的服务类")


@case("L启动", "已有实例则复用")
def l5():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("def probe_existing" in src, "缺少已有实例探测")
    check("工作台已经在运行了" in src, "缺少复用提示")
    # 探测必须在尝试绑定之前
    check(src.find("probe_existing(port)") < src.find("ExclusiveServer(("),
          "应先探测复用再绑定新端口")


@case("L启动", "独占绑定确实生效")
def l6():
    import http.server
    wb = load("wb_port", ROOT / "工作台.py")
    s1 = wb.ExclusiveServer(("127.0.0.1", 8841), wb.Handler)
    try:
        raised = False
        try:
            s2 = wb.ExclusiveServer(("127.0.0.1", 8841), wb.Handler)
            s2.server_close()
        except OSError:
            raised = True
        check(raised, "同端口二次绑定未报错，独占设置无效")
    finally:
        s1.server_close()


@case("L启动", "不得静默退出")
def l7():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("def wait_exit" in src, "缺少退出前提示函数")
    # 已有实例分支必须走 wait_exit，而不是裸 return
    i = src.find("工作台已经在运行了")
    check(i > 0, "缺少已有实例提示文案")
    seg = src[i:i+900]
    check("wait_exit" in seg, "已有实例时仍会静默退出")
    check("input(" in src[src.find("def wait_exit"):src.find("def wait_exit")+400],
          "退出提示未等待用户确认")


@case("L启动", "顶层异常必须可见")
def l8():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    tail = src[src.find('if __name__ == "__main__":'):]
    check("traceback.print_exc()" in tail, "未打印异常堆栈")
    check("except Exception" in tail, "缺少顶层异常兜底")
    check("input(" in tail, "异常后窗口会一闪而过")


@case("L启动", "端口探测不得逐个等超时")
def l9():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("def listening_ports" in src, "缺少监听端口表读取")
    check("def port_open" in src, "缺少快速端口探测")
    i = src.find("def probe_existing")
    seg = src[i:i+500]
    check("port_open(port)" in seg, "HTTP 探测前未先做端口预检")
    j = src.find("known = listening_ports()")
    check(j > 0, "启动未使用端口表筛选候选")


@case("L启动", "探测耗时可接受")
def l10():
    wb = load("wb_speed", ROOT / "工作台.py")
    t0 = time.time()
    known = wb.listening_ports()
    cands = [p for p in range(wb.PORT, wb.PORT + 20)
             if known is None or p in known]
    for p in cands:
        wb.probe_existing(p)
    el = time.time() - t0
    check(el < 5.0, f"端口探测耗时 {el:.1f}s，启动会明显卡顿")


@case("L启动", "bat始终保留窗口")
def l11():
    b = (ROOT / "启动工作台.bat").read_bytes().decode("ascii")
    lines = [l.strip() for l in b.splitlines()]
    check("pause" in lines, "缺少无条件 pause，静默退出时窗口会消失")
    check("2>&1" not in b, "含 2>&1 重定向，在本机会产生路径报错")
    check("if not defined PY" in b, "缺少解释器缺失兜底")
    check("gongzuotai.py" in b, "未检查入口文件存在")


# ============ P. 账号管理 ============
def make_accounts(td):
    """在隔离目录构造账号管理器，不碰真实登录态。"""
    wb = load("wb_acc_" + str(int(time.time() * 1000))[-6:], ROOT / "工作台.py")
    base = Path(td)
    wb.ROOT = base
    wb.PROFILE = base / "_profile"
    wb.ACCOUNTS_DIR = base / "_accounts"
    wb.ACCOUNTS_FILE = base / "账号.json"
    return wb, wb.Accounts()


@case("P账号", "旧登录态无缝纳入")
def p1():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        wb.PROFILE.mkdir(parents=True, exist_ok=True)
        (wb.PROFILE / "Cookies").write_text("x", encoding="utf-8")
        lst = acc.list()
        check(len(lst) == 1 and lst[0]["id"] == "default", f"默认账号缺失: {lst}")
        check(lst[0]["has_state"], "旧登录态未被识别")
        check(acc.profile_dir() == wb.PROFILE, "默认账号应沿用旧目录")


@case("P账号", "新增账号目录隔离")
def p2():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        a1 = acc.add("大号")
        a2 = acc.add("小号")
        check(a1 != a2, "账号 ID 重复")
        d1, d2 = acc.profile_dir(a1), acc.profile_dir(a2)
        check(d1 != d2 and d1.is_dir() and d2.is_dir(), "登录目录未隔离")
        check(acc.current() == a2, "新增后应自动切到新账号")


@case("P账号", "切换账号生效并持久")
def p3():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        a1 = acc.add("甲")
        acc.add("乙")
        ok, err = acc.switch(a1)
        check(ok, err)
        check(acc.current() == a1, "切换未生效")
        acc2 = wb.Accounts()
        check(acc2.current() == a1, "切换未持久化")


@case("P账号", "退出只清登录态")
def p4():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        aid = acc.add("测试号")
        d = acc.profile_dir(aid)
        (d / "Cookies").write_text("x", encoding="utf-8")
        # 采集数据放在别处，退出不应触碰
        data = Path(td) / "采集结果"
        data.mkdir(parents=True, exist_ok=True)
        (data / "data.json").write_text('{"artists":[1]}', encoding="utf-8")
        ok, err = acc.logout(aid)
        check(ok, err)
        check(not d.exists(), "登录态目录未清除")
        check((data / "data.json").is_file(), "退出登录误删了采集数据")
        check(aid in [x["id"] for x in acc.list()], "退出不应删除账号条目")


@case("P账号", "退出后可重新登录")
def p5():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        aid = acc.add("号")
        acc.logout(aid)
        st = [x for x in acc.list() if x["id"] == aid][0]
        check(not st["has_state"], "退出后仍显示已登录")
        acc.profile_dir(aid).mkdir(parents=True, exist_ok=True)
        (acc.profile_dir(aid) / "Cookies").write_text("x", encoding="utf-8")
        st = [x for x in acc.list() if x["id"] == aid][0]
        check(st["has_state"], "重新登录后状态未更新")


@case("P账号", "删除账号回落默认")
def p6():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        aid = acc.add("临时号")
        ok, err = acc.remove(aid)
        check(ok, err)
        check(acc.current() == "default", "删除当前账号后未回落默认")
        check(aid not in [x["id"] for x in acc.list()], "账号未删除")


@case("P账号", "默认账号不可删")
def p7():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        ok, err = acc.remove("default")
        check(ok is False and err, "默认账号应禁止删除")
        ok, err = acc.logout("default")
        check(ok, f"默认账号应允许退出登录: {err}")


@case("P账号", "非法操作被拒")
def p8():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        for ok, err in [acc.switch("不存在"), acc.rename("不存在", "x"),
                        acc.rename("default", "  "), acc.logout("不存在"),
                        acc.remove("不存在")]:
            check(ok is False and err, "非法操作应返回错误")


@case("P账号", "重命名生效且有长度上限")
def p9():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        ok, err = acc.rename("default", "我的主号")
        check(ok, err)
        check(acc.label() == "我的主号", "重命名未生效")
        acc.rename("default", "超" * 60)
        check(len(acc.label()) <= 24, "名称未限长")


@case("P账号", "损坏配置可自愈")
def p10():
    with tempfile.TemporaryDirectory() as td:
        wb, acc = make_accounts(td)
        wb.ACCOUNTS_FILE.write_text("{坏掉的JSON", encoding="utf-8")
        acc2 = wb.Accounts()
        check(acc2.current() == "default", "损坏配置未回落默认")
        check(len(acc2.list()) >= 1, "损坏配置后无可用账号")


@case("P账号", "接口齐备且忙时拒绝")
def p11():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    for k in ["/api/accounts", "/api/account_add", "/api/account_switch",
              "/api/account_rename", "/api/account_logout", "/api/account_remove"]:
        check(k in src, f"缺少接口 {k}")
    # 切换/退出/删除在任务运行时必须拒绝，避免登录目录被占用
    for name in ["account_switch", "account_logout", "account_remove", "account_add"]:
        i = src.find('if p == "/api/' + name + '"')
        seg = src[i:i + 260]
        check("ENGINE.phase" in seg, f"{name} 未做运行中保护")


@case("P账号", "前端账号控件齐备")
def p12():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ["accMenu", "accList", "accAdd", "accLogout", "renderAccounts",
              "toggleAcc", "account_switch", "account_logout"]:
        check(k in html, f"界面缺少账号要素 {k}")
    check("已采集的画师和图片不会丢失" in html, "缺少数据安全提示")
    check('role="menu"' in html, "账号菜单缺少语义角色")


# ============ Q. 待认领成因回归 ============
@case("Q待认领", "标题名加账号")
def q1():
    """「苺山 X:2833osi」正文纯标签，名字只在标题。"""
    d = "#画师推荐[话题]# #作品欣赏[话题]# #插画师[话题]#"
    r = E.parse_artists(d, "苺山 X:2833osi")
    check(len(r) == 1, f"应识别 1 人: {[a['name'] for a in r]}")
    check(r[0]["name"] == "苺山", f"主名错: {r[0]['name']}")
    check("2833osi" in r[0]["aliases"], f"账号未收为别名: {r[0]}")
    plan = E.build_plan({"title": "苺山 X:2833osi", "desc": d,
                         "images": ["x"] * 5}, 0)
    check(all(x["confidence"] == "single" for x in plan), "不应落入待认领")


@case("Q待认领", "ArtBy与孤立账号行")
def q2():
    """「X：nyz / Art by nyz」——没有主名时账号即主名。"""
    d = "X：nyz\nArt by nyz\n图源外网 | 版权归原作者所有\n#插画[话题]#"
    r = E.parse_artists(d, "每日插画分享#571")
    names = [a["name"] for a in r]
    check(names == ["nyz"], f"应识别 nyz: {names}")
    for variant in ["Art by abc", "art by abc", "Illustration by abc",
                    "Artwork by @abc"]:
        rr = E.parse_artists(variant, "")
        check([a["name"] for a in rr] == ["abc"], f"{variant} 未识别: {rr}")


@case("Q待认领", "身份词在名字之前")
def q3():
    """「西班牙插画家 Alariko（Alar Iko）」——名字在身份词后面。"""
    d = "西班牙插画家 Alariko（Alar Iko） 很擅长画“没有什么发生”的瞬间。\n#插画[话题]#"
    r = E.parse_artists(d, "他的画里，连发呆都有了故事")
    check([a["name"] for a in r] == ["Alariko"], f"识别错: {r}")


@case("Q待认领", "身份词后接句子不误判")
def q4():
    """「画师用松动写意的笔锋勾勒眉眼发丝」不能被当成名字。"""
    d = ("🎨画师：露路しぐれ（@tuyuji_0724）\n"
         "⭐该画师擅长以奔放洒脱的厚涂笔触为骨。画师用松动写意的笔锋勾勒眉眼发丝，"
         "不刻意雕琢圆滑轮廓。\n#插画[话题]#")
    r = E.parse_artists(d, "宝藏画师作品No.22｜审美积累")
    names = [a["name"] for a in r]
    check(names == ["露路しぐれ"], f"出现误判: {names}")
    check("tuyuji_0724" in r[0]["aliases"], f"括号账号未收别名: {r[0]}")
    plan = E.build_plan({"title": "宝藏画师作品No.22", "desc": d,
                         "images": ["x"] * 6}, 0)
    check(all(x["confidence"] == "single" for x in plan),
          "同人应判为全篇一人，不该 guess")


@case("Q待认领", "括号账号不拆成两人")
def q5():
    for d in ["画师：甲名（@handle_a）", "插画师:乙名(@handle_b)",
              "作者：丙名（handle_c）"]:
        r = E.parse_artists(d, "")
        check(len(r) == 1, f"{d} 被拆成多人: {[a['name'] for a in r]}")
        check(len(r[0]["aliases"]) == 1, f"{d} 别名缺失: {r[0]}")


@case("Q待认领", "标题首词不误取通用词")
def q6():
    """「每日插画分享#571」这类标题不能把「每日插画分享」当名字。"""
    for t in ["每日插画分享#571", "插画推荐 77", "作品欣赏 合集",
              "审美积累 艺术分享"]:
        r = E.parse_artists("", t)
        check(not r, f"标题 {t} 误产出画师: {r}")


@case("Q待认领", "待认领只留真正无署名的图")
def q7():
    """
    待认领是合法状态：正文确实没写画师名时就该留在这里，
    不能为了「清零」硬凑归属（曾把普通词「争议」当成画师）。
    这里只要求：留下的图必须是 unknown，且不得混入已确定归属的图。
    """
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    box = next((a for a in d["artists"] if a["name"] == "待认领"), None)
    if box is None:
        return
    bad = [im.get("conf") for im in box["images"] if im.get("conf") != "unknown"]
    check(not bad, f"待认领里混入已确定归属的图: {bad[:5]}")


@case("Q待认领", "身份词后普通词不算画师")
def q8():
    """「插画师所有作品🈲AI」「如果以上画师有争议」不是人名。"""
    d = ("插画师おこげゴリゴリ（twi：okoge_gorigori）的作品很震撼！\n"
         "插画师所有作品🈲AI请尊重插画师的原创作品\n"
         "插画版权©️归作者本人所有")
    r = E.parse_artists(d, "画功强悍")
    check([a["name"] for a in r] == ["おこげゴリゴリ"], f"普通词被当画师: {r}")
    check(r[0]["aliases"] == ["okoge_gorigori"], f"账号未归为别名: {r}")
    plan = E.build_plan({"title": "t", "desc": d, "images": ["x"] * 18}, 0)
    check(all(x["artist"] == "おこげゴリゴリ" for x in plan), "归属被拆分")
    check(all(x["confidence"] == "single" for x in plan), "单人帖应判确定")
    # 纯吐槽帖没写画师名，应老实留待认领
    d2 = ("我还要再加个香油（p8）……\n可以收藏。如果以上画师有争议，请提醒我\n"
          "#绘画[话题]#")
    check(E.parse_artists(d2, "自存全家都想吃的画师。") == [],
          "无署名帖不应硬凑出画师")
    for w in ["所有", "原创", "争议", "本人", "版权"]:
        check(E.clean_name(w) is None, f"普通词未被拦: {w}")


@case("Q待认领", "标题与换行署名可识别")
def q9():
    """名字只在标题、或身份词冒号后换行时，也要能取到。"""
    r = E.parse_artists("作者大大：\n织布机loom｜国人二次元画师\n#插画[话题]#",
                        "头像｜织布机loom")
    check([a["name"] for a in r] == ["织布机loom"], f"换行署名未识别: {r}")
    r2 = E.parse_artists("#画风绝绝子[话题]# #少女[话题]#", "画师@みっか")
    check([a["name"] for a in r2] == ["みっか"], f"标题署名未识别: {r2}")
    # 正文有可靠署名时，标题不得盖过它
    r3 = E.parse_artists("画师：米室", "每日插画分享｜审美积累")
    check([a["name"] for a in r3] == ["米室"], f"标题盖过正文: {r3}")


# ============ R. 新规则误判防护 ============
@case("R误判", "括号内国籍不算别名")
def r1():
    """「画师：kieed（中国）」——括号里是国籍，不是账号。"""
    r = E.parse_artists("画师：kieed（中国）\n账号全平台可搜索\n#插画[话题]#",
                        "宝藏画师推荐No.8｜审美提升｜kieed")
    check([a["name"] for a in r] == ["kieed"], f"主名错: {r}")
    check(not r[0]["aliases"], f"国籍被当成别名: {r[0]['aliases']}")
    for country in ["日本", "韩国", "美国", "西班牙", "国内"]:
        rr = E.parse_artists(f"画师：某名（{country}）", "")
        check(not rr[0]["aliases"], f"{country} 被当别名: {rr}")


@case("R误判", "括号内真账号仍收别名")
def r2():
    for h in ["@tuyuji_0724", "neko_pushio", "@abc123", "some.name"]:
        r = E.parse_artists(f"画师：主名（{h}）", "")
        check(len(r) == 1 and len(r[0]["aliases"]) == 1,
              f"{h} 未收为别名: {r}")


@case("R误判", "身份词不跨行取名")
def r3():
    """「…这位画师\\n希望你也喜欢！！！」不能把下一句当名字。"""
    d = ("今天推荐的插画师是X上的画师：あるてら ☾  老师\n"
         "毫无疑问就是copy的这位画师\n"
         "希望你也喜欢！！！Enjoy～～\n"
         "X （推特）：@TeraAru6262\n#分享[话题]#")
    r = E.parse_artists(d, "Vol.268｜画师推荐  这下知道AI抄的是谁了")
    names = [a["name"] for a in r]
    check(names == ["あるてら"], f"跨行误判: {names}")
    check("TeraAru6262" in r[0]["aliases"], "别名丢失")


@case("R误判", "is_handle判定准确")
def r4():
    for good in ["@abc", "abc123", "neko_pushio", "some.name", "@X_1"]:
        check(E.is_handle(good), f"{good} 应判为账号")
    for bad in ["中国", "日本", "推特", "侵删", "全平台", "", None, "很喜欢"]:
        check(not E.is_handle(bad), f"{bad} 不应判为账号")


@case("R误判", "归类保留在线图片")
def r5():
    src = (ROOT / "重新归类.py").read_text(encoding="utf-8")
    check('if not rel:' in src, "归类脚本未处理在线模式（无本地路径）")
    i = src.find("if not rel:")
    seg = src[i:i + 200]
    check("newimgs.append(im)" in seg, "在线图片未保留，会被丢弃")


# ============ S. D站凭证安全 ============
def make_dan(td):
    wb = load("wb_d_" + str(int(time.time() * 1000))[-6:], ROOT / "工作台.py")
    wb.CRED_FILE = Path(td) / "d站凭证.json"
    return wb, wb.Danbooru()


@case("S凭证", "未配置时不发请求")
def s1():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        check(not d.configured(), "初始应为未配置")
        data, err = d.get("/artists/1.json")
        check(data is None and err, "未配置应直接返回错误而非发请求")


@case("S凭证", "保存与脱敏回显")
def s2():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        ok, err = d.save("myuser", "SECRET_KEY_123456")
        check(ok, err)
        check(d.configured(), "保存后应为已配置")
        m = d.masked()
        check(m["login"] == "myuser", "账号名应可见")
        check(m["key_len"] == len("SECRET_KEY_123456"), "应只回长度")
        check("SECRET_KEY_123456" not in json.dumps(m), "脱敏信息泄露了密钥")


@case("S凭证", "空值被拒")
def s3():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        for a, b in [("", "k"), ("u", ""), ("  ", "  "), (None, None)]:
            ok, err = d.save(a, b)
            check(ok is False and err, f"空值应被拒: {a!r},{b!r}")


@case("S凭证", "错误信息剔除凭证")
def s4():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        d.save("myuser", "SECRET_KEY_123456")
        msg = d._scrub("connect failed for myuser with SECRET_KEY_123456")
        check("SECRET_KEY_123456" not in msg, "错误信息未抹掉密钥")
        check("myuser" not in msg, "错误信息未抹掉账号")
        check("***" in msg, "应替换为掩码")


@case("S凭证", "清除后文件消失")
def s5():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        d.save("u", "k")
        check(wb.CRED_FILE.is_file(), "凭证文件未生成")
        ok, err = d.clear()
        check(ok, err)
        check(not wb.CRED_FILE.exists(), "清除后文件仍在")
        check(not d.configured(), "清除后仍显示已配置")


@case("S凭证", "损坏凭证可自愈")
def s6():
    with tempfile.TemporaryDirectory() as td:
        wb, d = make_dan(td)
        wb.CRED_FILE.write_text("{坏JSON", encoding="utf-8")
        d2 = wb.Danbooru()
        check(not d2.configured(), "损坏凭证应回落未配置")


@case("S凭证", "仅GET无写操作")
def s7():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("class Danbooru")
    seg = src[i:src.find("DANBOORU = Danbooru()")]
    check("urllib.request.Request(url" in seg, "缺少请求构造")
    for bad in ['method="POST"', 'method="PUT"', 'method="DELETE"',
                "data=", "/favorites", "/votes", "/uploads"]:
        check(bad not in seg, f"出现写操作痕迹: {bad}")


@case("S凭证", "日志不记录密钥")
def s8():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find('if p == "/api/d_cred_save"')
    seg = src[i:i + 500]
    check("ENGINE.log" in seg, "缺少保存事件日志")
    check("api_key" not in seg.split("ENGINE.log")[1][:200],
          "日志语句里带入了密钥字段")


@case("S凭证", "接口齐备且ID校验")
def s9():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    for k in ["/api/d_cred", "/api/d_cred_save", "/api/d_cred_clear", "/api/d_probe"]:
        check(k in src, f"缺少接口 {k}")
    i = src.find('if p == "/api/d_probe"')
    seg = src[i:i + 400]
    check("isdigit()" in seg, "画师 ID 未做数字校验")


@case("S凭证", "前端不回显密钥")
def s10():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ["apiModal", "apiKey", "apiTest", "apiClear", "d_cred", "d_probe"]:
        check(k in html, f"界面缺少要素 {k}")
    check('type="password"' in html, "密钥输入应为密码框")
    check("$('apiKey').value = '';" in html, "保存后应清空密钥输入")
    check("内容不回显" in html, "缺少不回显说明")


@case("S凭证", "凭证文件不进交付")
def s11():
    # 凭证文件不应被任何打包/交付逻辑引用
    for f in ["测试套件.py", "设计说明.md"]:
        p2 = ROOT / f
        if p2.is_file():
            t = p2.read_text(encoding="utf-8")
            check("api_key\":" not in t, f"{f} 中疑似含凭证明文")


# ============ T. 名称匹配算法 ============
def wb_mod():
    return load("wb_m_" + str(int(time.time() * 1000))[-6:], ROOT / "工作台.py")


@case("T匹配", "归一化形态统一")
def t1():
    W = wb_mod()
    cases = [("@Abc", "abc"), ("  ABC  ", "abc"), ("a b", "a_b"),
             ("a-b", "a_b"), ("a・b", "a_b"), ("ＡＢＣ", "abc"),
             ("米室老师", "米室"), ("abcです", "abc")]
    for src, want in cases:
        got = W.name_norm(src)
        check(got == want, f"{src!r} 归一为 {got!r}，期望 {want!r}")
    check(W.name_norm(None) == "" and W.name_norm("") == "", "空值未兜底")


@case("T匹配", "编辑距离正确")
def t2():
    W = wb_mod()
    check(W.edit_distance("abc", "abc") == 0, "相同应为0")
    check(W.edit_distance("zhibuiiloom", "zhibujiloom") == 1, "单字母差应为1")
    check(W.edit_distance("abc", "abd") == 1, "替换应为1")
    check(W.edit_distance("abc", "ab") == 1, "删除应为1")
    check(W.edit_distance("a", "abcdefgh") == 99, "长度差过大应早停")


@case("T匹配", "真实案例拼写差异判疑似")
def t3():
    """小红书写 Zhibuiiloom，D 站是 zhibujiloom —— 差一个字母。"""
    W = wb_mod()
    entry = {"id": 149913, "name": "zhibuji_loom",
             "other_names": ["zhibujiloom", "织布机loom", "LOOOOM君", "十四般"]}
    r = W.match_names(["Zhibuiiloom"], entry)
    check(r["verdict"] == "near", f"应判疑似同人: {r}")
    check(r["nears"][0]["theirs"] == "zhibujiloom", f"最近项错: {r}")
    check(r["nears"][0]["distance"] == 1, "距离应为1")
    check(r["nears"][0]["similarity"] >= 0.85, "相似度应达标")


@case("T匹配", "精确命中优先于近似")
def t4():
    W = wb_mod()
    entry = {"id": 1, "name": "zhibuji_loom",
             "other_names": ["zhibujiloom", "织布机loom"]}
    for nm in ["zhibuji_loom", "织布机loom", "@ZHIBUJI_LOOM", "zhibuji-loom"]:
        r = W.match_names([nm], entry)
        check(r["verdict"] == "exact", f"{nm} 应精确命中: {r['verdict']}")


@case("T匹配", "别名参与匹配")
def t5():
    W = wb_mod()
    entry = {"id": 1, "name": "main_name", "other_names": ["alias_x"]}
    r = W.match_names(["不相关名", "alias_x"], entry)
    check(r["verdict"] == "exact", "别名应能命中")
    check(r["hits"][0]["ours"] == "alias_x", "命中来源记录错")


@case("T匹配", "短名不做近似匹配")
def t6():
    """LOOM 不能误配到 L◇◆M 这类形近短串。"""
    W = wb_mod()
    entry = {"id": 1, "name": "zhibuji_loom",
             "other_names": ["L◇◆M", "LOOOOM君"]}
    r = W.match_names(["LOOM"], entry)
    check(r["verdict"] == "none", f"短名不应近似命中: {r}")


@case("T匹配", "无关名判无结果")
def t7():
    W = wb_mod()
    entry = {"id": 1, "name": "zhibuji_loom", "other_names": ["织布机loom"]}
    for nm in ["希望你也喜欢", "完全不同的名字", "中国"]:
        r = W.match_names([nm], entry)
        check(r["verdict"] == "none", f"{nm} 不应命中: {r}")


@case("T匹配", "空输入与坏结构不崩")
def t8():
    W = wb_mod()
    for entry in [{}, {"name": None}, {"name": "x", "other_names": None},
                  {"name": "x", "other_names": "a b c"}]:
        r = W.match_names(["abc"], entry)
        check("verdict" in r, f"坏结构未兜底: {entry}")
    r = W.match_names([], {"name": "x"})
    check(r["verdict"] == "none", "空名字应判无结果")


@case("T匹配", "核验接口与只读约束")
def t9():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("/api/d_verify" in src, "缺少核验接口")
    i = src.find("def verify(self")
    seg = src[i:i + 1800]
    check("self.search(" in seg, "核验应走检索")
    check("不自动合并" in seg or "供人工确认" in seg, "缺少不自动合并的说明")
    j = src.find("def search(self")
    seg2 = src[j:j + 700]
    check("any_name_matches" in seg2, "检索应用 any_name_matches")


@case("T匹配", "probe不再编造作品数")
def t10():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("def probe(self")
    seg = src[i:i + 1200]
    body = "\n".join(l for l in seg.splitlines()
                      if not l.strip().startswith("#"))
    check('"post_count"' not in body, "接口不返回 post_count，不应作为字段返回")
    check("other_count" in seg, "应给出别名数量")


# ============ U. 模糊召回与ID唯一 ============
@case("U召回", "模糊策略覆盖词中错拼")
def u1():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("def search(self")
    seg = src[i:i + 2200]
    check("fuzzy" in seg, "缺少模糊开关")
    # 头/尾/中三段：错拼在词中间时单一前缀通配救不了
    check("core[:4]" in seg, "缺少头段召回")
    check("core[-4:]" in seg, "缺少尾段召回")
    check("mid" in seg, "缺少中段召回")
    check("seen" in seg, "多片段结果未去重")


@case("U召回", "零召回时才启用模糊")
def u2():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("def verify(self")
    seg = src[i:i + 2600]
    check("if not entries and not errors:" in seg, "模糊应仅在精确零召回时启用")
    check("fuzzy=True" in seg, "未调用模糊检索")
    check('"fuzzy"' in seg, "结果未标明是否用了模糊")


@case("U召回", "模糊结论标注证据来源")
def u3():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("经模糊召回后比对得出" in src, "模糊得出的结论应标注来源")


@case("U召回", "账号ID同毫秒不重复")
def u4():
    with tempfile.TemporaryDirectory() as td:
        wb = load("wb_uid_" + str(int(time.time() * 1000))[-6:], ROOT / "工作台.py")
        base = Path(td)
        wb.ROOT = base
        wb.PROFILE = base / "_profile"
        wb.ACCOUNTS_DIR = base / "_accounts"
        wb.ACCOUNTS_FILE = base / "账号.json"
        acc = wb.Accounts()
        ids = [acc.add(f"号{i}") for i in range(30)]
        check(len(set(ids)) == 30, f"连续创建出现重复ID: {len(ids)-len(set(ids))} 个")
        for i in ids:
            check(acc.profile_dir(i).is_dir(), f"目录未建: {i}")


@case("U召回", "ID生成含随机与重试")
def u5():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("def add(self, label")
    seg = src[i:i + 700]
    check("secrets" in seg, "ID 应含随机成分")
    check("not in self.meta" in seg, "缺少冲突检测")


# ============ V. 自动核验与确认 ============
# 保留真实实现，供需要验证反查逻辑的用例恢复（底层 get 仍被桩接管）
_WB_SRC = load("wb_ref", ROOT / "工作台.py")
orig_who = _WB_SRC.Danbooru.who_by_handle
_WB_SRC.DANBOORU._login = ""
_WB_SRC.DANBOORU._key = ""


def make_eng_verify(td, stub):
    """
    构造引擎并把 D 站核验替换为可控桩。
    同时把底层 get 也堵死：即使某条路径漏用桩，也绝不会真的联网。
    """
    wb = make_wb(td)
    eng = wb.Engine()
    wb.DANBOORU._login = "u"
    wb.DANBOORU._key = "k"
    wb.DANBOORU.verify = stub

    def _no_net(*a, **k):
        raise AssertionError("测试中不允许真实联网请求 D 站")

    wb.DANBOORU.get = _no_net
    wb.DANBOORU.search = lambda *a, **k: ([], "测试桩：不联网")
    # 账号铁证路径也要堵死：默认无证据，需要的用例自行覆盖
    wb.DANBOORU.who_by_handle = lambda *a, **k: []
    wb.DANBOORU.urls_of = lambda *a, **k: []
    # 搜图兜底同样默认关闭，避免测试真实联网
    wb.SAUCENAO._key = ""
    wb.SAUCENAO.search = lambda *a, **k: ([], "测试桩：不联网")
    return wb, eng


@case("V自动核验", "采集收尾才核验")
def v1():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    i = src.find("采集完成：")
    seg = src[i:i + 700]
    check("verify_all()" in seg, "采集结束应自动核验")
    check("别名已从各篇笔记累积完整" in seg, "应说明为何整轮后才核验")
    # 逐篇循环内不应调用核验
    j = src.find("for i, it in enumerate(items, 1)")
    loop = src[j:src.find("finally:", j)]
    check("verify_all" not in loop and "verify_one" not in loop,
          "不应在逐篇采集时核验（别名未齐会误判）")


@case("V自动核验", "未配置凭证时跳过")
def v2():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("DANBOORU.configured()" in src, "应检查凭证是否已配置")
    check("跳过自动核验" in src, "未配置时应明确提示跳过")


@case("V自动核验", "核验结果写入记录")
def v3():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "candidates": [
                {"id": "123", "name": "real_name", "url": "u",
                 "match": {"verdict": "exact", "hits": [{"ours": nm}], "nears": []}}],
                "message": "ok"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "测试名", 2)
        ok, info = eng.verify_one("测试名")
        check(ok, info)
        v = eng.artists["测试名"]["verify"]
        check(v["state"] == "matched", f"状态错: {v}")
        check(v["id"] == "123", "未记录 D 站 ID")


@case("X指向", "模糊召回不得直连")
def x1():
    """
    Blanc.ブラン 曾被模糊匹配蹭到 Blanched_Z（完全不同的画师）。
    模糊召回即使编辑距离判定为 exact，也只能当候选，不能写 id。
    """
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "fuzzy": True, "candidates": [
                {"id": "695468", "name": "baizhuoxiaoz", "url": "u",
                 "match": {"verdict": "exact",
                           "hits": [{"ours": nm, "field": "other_names",
                                     "theirs": "Blanched_Z"}], "nears": []}}],
                "message": "模糊召回"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "Blanc.ブラン", 1)
        eng.verify_one("Blanc.ブラン")
        v = eng.artists["Blanc.ブラン"]["verify"]
        check(v["id"] == "", f"模糊召回却写了直连ID: {v['id']}")
        check(v["state"] != "matched", f"模糊召回不应判为命中: {v['state']}")
        check(v.get("suggest_id") == "695468", "候选应另存供人工核对")
        rec = [r for r in eng.data() if r["name"] == "Blanc.ブラン"][0]
        check(rec["d_direct"] is False, "模糊召回不应直连")
        check("/artists/695468" not in rec["d_url"],
              f"仍指向错误画师: {rec['d_url']}")


@case("X指向", "未找到不得留残余ID")
def x2():
    """asikumin 曾被判 missing 却仍填 id=703320，导致跳到 asikusa。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [
                {"id": "703320", "name": "asikusa", "url": "u",
                 "match": {"verdict": "none", "hits": [], "nears": []}}],
                "message": "名字都不匹配"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "asikumin", 1)
        eng.verify_one("asikumin")
        v = eng.artists["asikumin"]["verify"]
        check(v["state"] == "missing", f"状态错: {v['state']}")
        check(v["id"] == "" and v["url"] == "",
              f"未找到却留下指向: id={v['id']} url={v['url']}")
        rec = [r for r in eng.data() if r["name"] == "asikumin"][0]
        check(rec["d_direct"] is False and "/artists/703320" not in rec["d_url"],
              f"未找到仍指向他人: {rec['d_url']}")


@case("X指向", "精确命中须带证据")
def x3():
    """nyz 真在 nyzziz 的别名里，属正确命中，应直连并给出依据。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "fuzzy": False, "candidates": [
                {"id": "480154", "name": "nyzziz", "url": "u",
                 "match": {"verdict": "exact",
                           "hits": [{"ours": "nyz", "field": "other_names",
                                     "theirs": "nyz"}], "nears": []}}],
                "message": "ok"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "nyz", 1)
        eng.verify_one("nyz")
        v = eng.artists["nyz"]["verify"]
        check(v["id"] == "480154", "真别名命中应记录ID")
        check("other_names" in v.get("evidence", ""),
              f"缺少命中依据: {v.get('evidence')}")
        rec = [r for r in eng.data() if r["name"] == "nyz"][0]
        check(rec["d_direct"] is True, "精确命中应直连")
        check(rec["d_url"].endswith("/artists/480154"), f"直连地址错: {rec['d_url']}")


@case("X指向", "疑似只给候选不给指向")
def x4():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "near", "candidates": [
                {"id": "149913", "name": "zhibuji_loom", "url": "u",
                 "match": {"verdict": "near", "hits": [],
                           "nears": [{"ours": nm, "theirs": "zhibuji_loom",
                                      "distance": 1, "similarity": 0.9}]}}],
                "message": "高度相似"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "Zhibuiiloom", 1)
        eng.verify_one("Zhibuiiloom")
        v = eng.artists["Zhibuiiloom"]["verify"]
        check(v["state"] == "suspect" and v["id"] == "",
              f"疑似不应写直连ID: {v}")
        rec = [r for r in eng.data() if r["name"] == "Zhibuiiloom"][0]
        check(rec["d_direct"] is False, "疑似不应直连")


@case("X指向", "多个同名须待消歧不直连")
def x5b():
    """みっか：6 个条目都把「みっか」当别名，绝不能随手取第一个。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            cands = []
            for cid, cnm in [("457499", "ichinichime"), ("448768", "3icca5"),
                             ("330924", "mikka_2022")]:
                cands.append({"id": cid, "name": cnm, "url": f"u/{cid}",
                              "primary": False,
                              "match": {"verdict": "exact",
                                        "hits": [{"ours": nm, "field": "other_names",
                                                  "theirs": nm}], "nears": []}})
            return {"verdict": "ambiguous", "candidates": cands,
                    "message": "多个同名"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "みっか", 1)
        eng.verify_one("みっか")
        v = eng.artists["みっか"]["verify"]
        check(v["state"] == "ambiguous", f"应判待消歧: {v['state']}")
        check(v["id"] == "", f"待消歧却写了直连ID: {v['id']}")
        check(v.get("ambiguous") is True, "未标记 ambiguous")
        check(len(v["candidates"]) >= 3, "应保留全部同名候选供点选")
        check(all(c.get("url") for c in v["candidates"]), "候选缺预览链接")
        rec = [r for r in eng.data() if r["name"] == "みっか"][0]
        check(rec["d_direct"] is False, "待消歧不应直连")
        check("/artists/" not in rec["d_url"], f"待消歧不应指向条目: {rec['d_url']}")


@case("X指向", "主名唯一时多个别名命中仍可定案")
def x6b():
    """同名条目多，但只有一个是主名命中 → 主名是强证据，可信直连。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "candidates": [
                {"id": "136198", "name": "kieed", "url": "u/136198",
                 "primary": True,
                 "match": {"verdict": "exact",
                           "hits": [{"ours": nm, "field": "name",
                                     "theirs": nm}], "nears": []}},
                {"id": "425173", "name": "kieed12", "url": "u/425173",
                 "primary": False,
                 "match": {"verdict": "exact",
                           "hits": [{"ours": nm, "field": "other_names",
                                     "theirs": nm}], "nears": []}}],
                "message": "主名唯一"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "kieed", 1)
        eng.verify_one("kieed")
        v = eng.artists["kieed"]["verify"]
        check(v["state"] == "matched" and v["id"] == "136198",
              f"主名唯一应定案到主名条目: {v['id']}")
        rec = [r for r in eng.data() if r["name"] == "kieed"][0]
        check(rec["d_direct"] is True, "主名唯一应直连")


@case("Z搜图", "凭证不回显且不进日志")
def z1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        s = wb.SAUCENAO
        key = "z" * 40
        ok, err = s.save(key)
        check(ok, err)
        mk = s.masked()
        check(mk["configured"] and mk["key_len"] == 40, f"脱敏信息错: {mk}")
        check(key not in json.dumps(mk), "明文密钥出现在回传信息里")
        check(s._scrub(f"失败 {key}") == "失败 ***", "错误信息未抹掉密钥")
        check(s._key == key, "未正确保存")
        ok, err = s.clear()
        check(ok and not s.configured(), f"清除失败: {err}")
        check(not wb.SAUCE_FILE.exists(), "凭证文件未删除")


@case("Z搜图", "短Key被拒")
def z2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        for bad in ["", "abc", "x" * 19]:
            ok, err = wb.SAUCENAO.save(bad)
            check(not ok and err, f"非法Key未被拒: {bad!r}")


@case("Z搜图", "未配置时不发请求")
def z3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        rows, err = wb.SAUCENAO.search("https://example.com/a.jpg")
        check(rows == [] and "尚未配置" in err, f"未配置时应拒绝: {err}")
        r = wb.SAUCENAO.probe("https://example.com/a.jpg")
        check(r["ok"] is False, "未配置时探测应失败")


@case("Z搜图", "限流与额度保护")
def z4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        s = wb.SAUCENAO
        s._key = "k" * 40
        # 30 秒内超过上限应给出等待时间，而不是硬闯
        for _ in range(s.short_cap):
            wait, err = s._throttle()
            check(wait == 0 and not err, f"正常额度被拦: {wait} {err}")
        wait, err = s._throttle()
        check(wait > 0, "超出短周期上限却未要求等待")
        # 当日用尽应直接拒绝
        s._day_used = s.daily_cap
        wait, err = s._throttle()
        check(wait == -1 and "额度" in err, f"日额度用尽未拒绝: {wait} {err}")


@case("Z搜图", "低相似度结果被丢弃")
def z5():
    """同画风也会高分，低于阈值的结果不能用来判定身份。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        s = wb.SAUCENAO
        s._key = "k" * 40
        payload = {"header": {"status": 0}, "results": [
            {"header": {"similarity": "92.5", "index_id": 9,
                        "index_name": "Danbooru"},
             "data": {"member_name": "real_author", "member_id": "123",
                      "ext_urls": ["https://danbooru.donmai.us/posts/1"]}},
            {"header": {"similarity": "51.0", "index_id": 5,
                        "index_name": "Pixiv"},
             "data": {"member_name": "someone_else"}},
        ]}

        class R:
            headers = {"Content-Type": "application/json"}

            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        import urllib.request
        old = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: R()
        try:
            rows, err = s.search("https://example.com/a.jpg", minsim=80)
        finally:
            urllib.request.urlopen = old
        check(err is None, f"解析失败: {err}")
        check(len(rows) == 1, f"低相似度未过滤: {len(rows)}")
        check(rows[0]["author"] == "real_author", f"作者字段错: {rows[0]}")
        check(rows[0]["index_id"] == 9, "库编号丢失")


@case("Z搜图", "额度耗尽有明确提示")
def z6():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        s = wb.SAUCENAO
        s._key = "k" * 40
        payload = {"header": {"status": -2,
                              "message": "Daily Search Limit Exceeded"}}

        class R:
            headers = {"Content-Type": "application/json"}

            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        import urllib.request
        old = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: R()
        try:
            rows, err = s.search("https://example.com/a.jpg")
        finally:
            urllib.request.urlopen = old
        check(rows == [] and "额度" in err, f"额度提示不明确: {err}")


@case("Z搜图", "作品反查可自动定案")
def z8():
    """Blanc.ブラン 型：名字搜不到，但作品图在 D 站有登记。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        wb.SAUCENAO.search = lambda *a, **k: ([{
            "similarity": 96.2, "index_id": 9, "index_name": "Danbooru",
            "author": "mont blanca", "author_id": "",
            "urls": ["https://danbooru.donmai.us/posts/6147887"],
            "title": "", "source": "", "thumbnail": ""}], None)
        wb.DANBOORU.get = lambda path, *a, **k: (
            {"tag_string_artist": "mont_blanca"}, None) if "/posts/" in path else (
            [{"id": 294127, "name": "mont_blanca",
              "other_names": ["Blanc"]}], None)
        seed(wb, eng, "Blanc.ブラン", 1)
        eng.verify_one("Blanc.ブラン")
        v = eng.artists["Blanc.ブラン"]["verify"]
        check(v["state"] == "matched", f"搜图未定案: {v['state']}")
        check(v["id"] == "294127", f"定案ID错: {v['id']}")
        check("搜图铁证" in v.get("evidence", ""), "缺少搜图依据")
        rec = [r for r in eng.data() if r["name"] == "Blanc.ブラン"][0]
        check(rec["d_direct"] is True and rec["d_url"].endswith("/artists/294127"),
              f"未直连真身: {rec['d_url']}")


@case("Z搜图", "多作者冲突不定案")
def z9():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        seq = iter([
            ([{"similarity": 95, "index_id": 9, "index_name": "Danbooru",
               "author": "a", "urls": ["https://danbooru.donmai.us/posts/1"],
               "title": "", "source": "", "thumbnail": "", "author_id": ""}], None),
            ([{"similarity": 94, "index_id": 9, "index_name": "Danbooru",
               "author": "b", "urls": ["https://danbooru.donmai.us/posts/2"],
               "title": "", "source": "", "thumbnail": "", "author_id": ""}], None),
        ])
        wb.SAUCENAO.search = lambda *a, **k: next(seq)
        tags = iter([{"tag_string_artist": "artist_a"},
                     {"tag_string_artist": "artist_b"}])
        wb.DANBOORU.get = lambda path, *a, **k: (
            next(tags), None) if "/posts/" in path else ([], None)
        seed(wb, eng, "冲突名", 2)
        eng.verify_one("冲突名")
        v = eng.artists["冲突名"]["verify"]
        check(v["id"] == "", f"两张图指向不同作者却定案: {v['id']}")


@case("Z搜图", "低相似度不参与定案")
def z10():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        # minsim=85 时低分结果应已被 search 过滤，这里模拟返回空
        wb.SAUCENAO.search = lambda *a, **k: ([], None)
        seed(wb, eng, "低分名", 1)
        eng.verify_one("低分名")
        v = eng.artists["低分名"]["verify"]
        check(v["id"] == "" and v["state"] != "matched", "低分不应定案")


@case("Z搜图", "命中结果不被搜图改写")
def z11():
    """
    搜图复核已按授权移除：名字精确命中的结论不应被搜图改写，
    也不应因此产生任何搜图调用。
    """
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "fuzzy": False, "candidates": [
                {"id": "192433", "name": "yonemuro", "url": "u",
                 "match": {"verdict": "exact",
                           "hits": [{"ours": nm, "field": "other_names",
                                     "theirs": nm}], "nears": []}}],
                "message": "ok"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return ([{"similarity": 96, "index_id": 9, "index_name": "Danbooru",
                      "author": "someone_else", "author_id": "",
                      "urls": ["https://danbooru.donmai.us/posts/777"],
                      "title": "", "source": "", "thumbnail": ""}], None)
        wb.SAUCENAO.search = spy
        seed(wb, eng, "米室", 3)
        eng.verify_one("米室")
        v = eng.artists["米室"]["verify"]
        check(v["id"] == "192433", f"命中ID被改写: {v['id']}")
        check(not calls, f"已命中仍调用搜图 {len(calls)} 次")
        check(not v.get("cross"), "不应再产生搜图复核结论")


@case("M合并", "同ID分组检测")
def m1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "Z3zz", 1)
        seed(wb, eng, "Z3zz4", 1)
        seed(wb, eng, "米室", 1)
        for nm in ["Z3zz", "Z3zz4"]:
            eng.artists[nm]["verify"] = {"state": "matched", "id": "261471"}
        eng.artists["米室"]["verify"] = {"state": "matched", "id": "192433"}
        groups = eng.state()["same_id"]
        check(len(groups) == 1, f"分组数错: {groups}")
        check(set(groups[0]["names"]) == {"Z3zz", "Z3zz4"}, f"分组成员错: {groups}")


@case("M合并", "合并保留全部图片")
def m2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 0     # 不限制时全量并入
        seed(wb, eng, "Z3zz", 2)
        seed(wb, eng, "Z3zz4", 3)
        ok, err = eng.rename_artist("Z3zz4", "Z3zz")
        check(ok, err)
        check("Z3zz4" not in eng.artists, "被合并条未移除")
        check(len(eng.artists["Z3zz"]["images"]) == 5, "合并丢图")


@case("M合并", "合并守上限且一张不丢")
def m3():
    """
    合并绕过上限曾让 Zhibuiiloom 从 28 张冲到 34 张。
    更危险的是：源记录在合并前已被 pop，装不下的图若不保全就永久消失。
    """
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 5
        seed(wb, eng, "甲", 4)
        seed(wb, eng, "乙", 4)
        before = sum(len(a["images"]) for a in eng.artists.values())
        check(before == 8, f"准备数据不符: {before}")
        ok, err = eng.rename_artist("乙", "甲")
        check(ok, err)
        check(len(eng.artists["甲"]["images"]) == 5,
              f"合并未守上限: {len(eng.artists['甲']['images'])}")
        after = sum(len(a["images"]) for a in eng.artists.values())
        check(after == before, f"图片丢失: {before} → {after}")
        check("乙" in eng.artists, "装不下的图未留在原画师名下")
        check(len(eng.artists["乙"]["images"]) == 3,
              f"原画师应留下 3 张: {len(eng.artists['乙']['images'])}")
        # 落盘后重启仍守恒
        eng.save()
        eng2 = wb.Engine()
        total2 = sum(len(a["images"]) for a in eng2.artists.values())
        check(total2 == before, f"重启后图片丢失: {total2}")


@case("M合并", "加载与撤销还原不受上限限制")
def m4():
    """
    启动加载若套用上限，历史超限图片会被丢弃且立刻落盘 → 永久丢失。
    撤销还原同理：用户点撤销就是为了把东西找回来。
    """
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 2
        seed(wb, eng, "甲", 5)          # 采集时受上限，只入 2 张
        check(len(eng.artists["甲"]["images"]) == 2, "采集未守上限")
        # 构造一份历史数据：同一人有 5 张（超上限），加载必须全量并入
        wb.DATA_FILE.write_text(json.dumps({"artists": [
            {"name": "历史画师", "aliases": [], "styles": [], "notes": [],
             "images": [{"src": f"https://x/h{i}.jpg", "key": f"H{i}",
                         "file": "", "conf": "single"} for i in range(5)]},
        ]}, ensure_ascii=False), encoding="utf-8")
        eng2 = wb.Engine()
        eng2.max_per_artist = 2
        check(len(eng2.artists["历史画师"]["images"]) == 5,
              f"加载时被上限裁掉，历史图片永久丢失: "
              f"{len(eng2.artists['历史画师']['images'])}")
        # 撤销还原同样不得受限
        snapshot = {"name": "还原画师", "aliases": [], "styles": [],
                    "notes": [], "images": [
                        {"src": f"https://x/r{i}.jpg", "key": f"R{i}",
                         "file": "", "conf": "single"} for i in range(5)]}
        ok, err = eng2.restore_artist(snapshot)
        check(ok, err)
        check(len(eng2.artists["还原画师"]["images"]) == 5,
              f"撤销还原被上限裁掉: {len(eng2.artists['还原画师']['images'])}")


@case("M合并", "上限为0时合并不受限")
def m5():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 0
        seed(wb, eng, "甲", 6)
        seed(wb, eng, "乙", 6)
        ok, err = eng.rename_artist("乙", "甲")
        check(ok, err)
        check(len(eng.artists["甲"]["images"]) == 12, "上限0应全量合并")
        check("乙" not in eng.artists, "上限0时源记录应被移除")


@case("W授权", "已命中画师不得搜图")
def w1():
    """
    用户授权：只在 D 站找不到/对应不上时才以图搜图。
    对已命中画师再搜图属越界调用，会白烧上百次额度。
    """
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "exact", "fuzzy": False, "candidates": [
                {"id": "192433", "name": "yonemuro", "url": "u",
                 "match": {"verdict": "exact",
                           "hits": [{"ours": nm, "field": "other_names",
                                     "theirs": nm}], "nears": []}}],
                "message": "ok"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return [], None
        wb.SAUCENAO.search = spy
        seed(wb, eng, "米室", 6)
        eng.verify_one("米室")
        v = eng.artists["米室"]["verify"]
        check(v["state"] == "matched", f"应命中: {v['state']}")
        check(not calls, f"已命中却仍搜图 {len(calls)} 次（越界烧额度）")


@case("W授权", "搜图每位最多两张且不重试")
def w2():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []

        def spy(u, **k):
            calls.append(u)
            return [], None      # 一直无命中，考验是否停手
        wb.SAUCENAO.search = spy
        seed(wb, eng, "查无此人", 10)
        eng.verify_one("查无此人")
        check(len(calls) <= eng.SAUCE_MAX_IMGS,
              f"无命中仍硬试 {len(calls)} 次，上限 {eng.SAUCE_MAX_IMGS}")
        n0 = len(calls)
        eng.verify_one("查无此人", force=True)
        check(len(calls) == n0,
              f"无命中的图被重复搜（{len(calls)-n0} 次），白烧额度")


def _png_bytes(color, w=64, h=64, mark=None):
    """生成可区分的测试图字节；mark 用来制造画面差异。"""
    from PIL import Image
    import io
    im = Image.new("RGB", (w, h), color)
    if mark:
        for x in range(*mark[0]):
            for y in range(*mark[1]):
                im.putpixel((x, y), mark[2])
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@case("W授权", "搜图额度跨轮次累计")
def w6():
    """
    用户要求：每位画师累计最多 2 张，不是每轮 2 张。
    今天搜 2 张、明天重核再搜 2 张就是 4 张，违规。
    """
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []
        wb.SAUCENAO.search = lambda u, **k: (calls.append(u), ([], None))[1]
        eng._image_phash = lambda im: ""   # 指纹取不到时退回 URL 去重
        seed(wb, eng, "累计测试", 8)
        for _ in range(4):        # 模拟四轮重核
            eng.verify_one("累计测试", force=True)
        check(len(calls) == eng.SAUCE_MAX_IMGS,
              f"四轮累计搜了 {len(calls)} 次，应恰好 {eng.SAUCE_MAX_IMGS} 次")
        uid = eng.artists["累计测试"]["uid"]
        check(eng.sauce_left(uid) == 0, "额度未耗尽")
        eng.save()
        eng2 = wb.Engine()
        eng2._image_phash = lambda im: ""
        calls2 = []
        wb.SAUCENAO.search = lambda u, **k: (calls2.append(u), ([], None))[1]
        eng2.verify_one("累计测试", force=True)
        check(not calls2, f"重启后额度被重置，又搜了 {len(calls2)} 次")


@case("W授权", "改名不重置搜图额度")
def w7():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []
        wb.SAUCENAO.search = lambda u, **k: (calls.append(u), ([], None))[1]
        eng._image_phash = lambda im: ""
        seed(wb, eng, "旧名", 6)
        eng.verify_one("旧名", force=True)
        n0 = len(calls)
        check(n0 == eng.SAUCE_MAX_IMGS, f"首轮应搜满: {n0}")
        ok, err = eng.rename_artist("旧名", "新名")
        check(ok, err)
        eng.verify_one("新名", force=True)
        check(len(calls) == n0,
              f"改名后额度被重置，又搜了 {len(calls)-n0} 次")


@case("W授权", "同画不同ID不重复搜")
def w8():
    """
    最阴的情况：同一张画被裁切/加水印/重新上传后拿到新图片ID，
    URL 去重抓不到。必须靠画面指纹识别，否则 2 次额度花在同一张画上。
    """
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []
        wb.SAUCENAO.search = lambda u, **k: (calls.append(u), ([], None))[1]
        base = _png_bytes((200, 60, 90), 64, 64)
        small = _png_bytes((200, 60, 90), 32, 32)
        big = _png_bytes((200, 60, 90), 128, 128)
        h1, h2, h3 = E.phash(base), E.phash(small), E.phash(big)
        check(h1 and E.same_picture(h1, h2) and E.same_picture(h1, h3),
              f"同画不同尺寸未被识别为同一张: {h1} {h2} {h3}")
        phs = {"http://i/A": h1, "http://i/B": h2, "http://i/C": h3}
        eng._image_phash = lambda im: phs.get(im.get("src"), "")
        seed(wb, eng, "同画测试", 1)
        eng.artists["同画测试"]["images"] = [
            {"src": "http://i/A", "key": "KA", "file": "", "conf": "single"},
            {"src": "http://i/B", "key": "KB", "file": "", "conf": "single"},
            {"src": "http://i/C", "key": "KC", "file": "", "conf": "single"},
        ]
        eng.verify_one("同画测试", force=True)
        check(len(calls) == 1,
              f"同一张画的三个版本各搜了一次，共 {len(calls)} 次，应为 1 次")


@case("W授权", "两张不同的画各搜一次")
def w9():
    """内容去重不能过度：两张真正不同的画必须都能搜。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.SAUCENAO._key = "k" * 40
        calls = []
        wb.SAUCENAO.search = lambda u, **k: (calls.append(u), ([], None))[1]
        a = _png_bytes((20, 200, 90), 64, 64, mark=((0, 32), (0, 64), (0, 0, 0)))
        b = _png_bytes((240, 240, 30), 64, 64, mark=((32, 64), (0, 64), (0, 0, 0)))
        ha, hb = E.phash(a), E.phash(b)
        check(ha and hb and not E.same_picture(ha, hb),
              f"两张不同的画被误判为同一张: {ha} {hb}")
        phs = {"http://i/X": ha, "http://i/Y": hb}
        eng._image_phash = lambda im: phs.get(im.get("src"), "")
        seed(wb, eng, "两画测试", 1)
        eng.artists["两画测试"]["images"] = [
            {"src": "http://i/X", "key": "KX", "file": "", "conf": "single"},
            {"src": "http://i/Y", "key": "KY", "file": "", "conf": "single"},
        ]
        eng.verify_one("两画测试", force=True)
        check(len(calls) == 2, f"两张不同的画应各搜一次，实际 {len(calls)} 次")


@case("W授权", "单画师收图有上限")
def w3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 5
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/1"}
        for r in range(4):
            plan = [{"artist": "甲", "style": "", "image_url": f"http://i/{r}/{j}",
                     "seq": j, "confidence": "single"} for j in range(4)]
            eng._ingest(FakeCtx(), note, plan, f"http://n/{r}")
        check(len(eng.artists["甲"]["images"]) == 5,
              f"上限未生效: {len(eng.artists['甲']['images'])}")
        eng.max_per_artist = 0
        plan = [{"artist": "乙", "style": "", "image_url": f"http://z/{j}",
                 "seq": j, "confidence": "single"} for j in range(12)]
        eng._ingest(FakeCtx(), note, plan, "http://n/z")
        check(len(eng.artists["乙"]["images"]) == 12, "0 应为不限制")


@case("W授权", "占位名不得作身份别名")
def w4():
    """
    「待认领」被收作别名后，resolve() 会把后续所有无归属图
    都判给那位画师（曾让一人吞下 49 张别人的图）。
    """
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        seed(wb, eng, "甲", 1)
        eng.artists["甲"]["aliases"] = ["待认领"]
        check(eng.resolve("待认领") != "甲",
              "占位名仍参与身份匹配，无归属图会被判给他人")
        note = {"title": "t", "author": "a", "desc": "", "url": "http://n/9"}
        plan = [{"artist": "待认领", "style": "", "image_url": "http://i/none",
                 "seq": 1, "confidence": "unknown"}]
        eng._ingest(FakeCtx(), note, plan, "http://n/9")
        check(len(eng.artists["甲"]["images"]) == 1, "无归属图被并入他人")
        check("待认领" in eng.artists, "无归属图未进待认领")
        check("待认领" not in (eng.artists["甲"].get("aliases") or []),
              "占位名仍被留作别名")
        ok, err = eng.rename_artist("待认领", "甲")
        check(not ok and err, "占位筐整筐改名未被拒绝")


@case("W授权", "加载时清除占位别名")
def w5():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DATA_DIR.mkdir(parents=True, exist_ok=True)
        wb.DATA_FILE.write_text(json.dumps({"artists": [{
            "name": "甲", "aliases": ["待认领", "真别名"],
            "images": [{"src": "https://x/a.jpg", "file": "", "conf": "single"}],
        }]}, ensure_ascii=False), encoding="utf-8")
        eng = wb.Engine()
        al = eng.artists["甲"]["aliases"]
        check("待认领" not in al, f"加载未清除占位别名: {al}")
        check("真别名" in al, "误删了正常别名")
        saved = json.loads(wb.DATA_FILE.read_text(encoding="utf-8"))
        check("待认领" not in saved["artists"][0]["aliases"], "清理未落盘")


@case("Z搜图", "缓存复跑不重复搜")
def z13():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        wb.SAUCENAO._key = "k" * 40
        calls = []

        def fake_search(u, **k):
            calls.append(u)
            return ([{"similarity": 95, "index_id": 9, "index_name": "Danbooru",
                      "author": "a", "author_id": "",
                      "urls": ["https://danbooru.donmai.us/posts/1"],
                      "title": "", "source": "", "thumbnail": ""}], None)
        wb.SAUCENAO.search = fake_search
        wb.DANBOORU.get = lambda *a, **k: ({"tag_string_artist": "a"}, None)
        imgs = [{"src": "https://img/x/1", "key": "K1"}]
        v1, e1 = eng._sauce_votes(imgs)
        v2, e2 = eng._sauce_votes(imgs)
        check(e1 is None and e2 is None, f"出错: {e1} {e2}")
        check(len(calls) == 1, f"缓存未生效，重复搜: {len(calls)}")
        check(v1 == v2 and "a" in v1, "缓存结果不一致")
        check(wb.SAUCE_CACHE_FILE.is_file(), "缓存未落盘")
        saved = json.loads(wb.SAUCE_CACHE_FILE.read_text(encoding="utf-8"))
        check("K1" in saved, "缓存键错")


def make_sem(wb, payload):
    """在 Engine() 创建前写入语义映射表（引擎构造时加载）。"""
    wb.SEMANTIC_FILE.write_text(json.dumps(payload, ensure_ascii=False),
                                encoding="utf-8")


SEM_SAMPLE = {
    "通用词": {"审美积累": "栏目名", "蛋挞": "编辑署名"},
    "改名": {"gomdori.muousse.cake": "곰미", "zbibuji loom": "Zhibuiiloom"},
    "补别名": {"곰미": ["gomdori.muousse.cake"], "soresaki": ["1100_2299"]},
}


@case("S语义", "通用词不建假画师")
def s1():
    """「审美积累」是栏目名，规则层抽到它时图片应进待认领。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        make_sem(wb, SEM_SAMPLE)
        eng = wb.Engine()
        check(eng.is_generic_word("审美积累"), "通用词未被识别")
        check(eng.is_generic_word(" 审美积累 "), "通用词判定未忽略空格")
        check(not eng.is_generic_word("米室"), "正常画师被误判为通用词")
        seed(wb, eng, "审美积累", 2, conf="guess")
        check("审美积累" not in eng.artists, "栏目名被建成假画师")
        check("待认领" in eng.artists, "通用词图片未退回待认领")
        check(len(eng.artists["待认领"]["images"]) == 2, "图片数量不对")
        check(all(im["conf"] == "unknown"
                  for im in eng.artists["待认领"]["images"]),
              "退回待认领应标记为无归属")


@case("S语义", "账号名自动纠正为真名")
def s2():
    """规则层把 ins 账号当主名时，应按语义映射纠正为 곰미。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        make_sem(wb, SEM_SAMPLE)
        eng = wb.Engine()
        check(eng.semantic_canonical("gomdori.muousse.cake") == "곰미",
              "改名映射未生效")
        seed(wb, eng, "gomdori.muousse.cake", 3)
        check("gomdori.muousse.cake" not in eng.artists, "仍用账号名建档")
        check("곰미" in eng.artists, "未纠正为真名")
        rec = eng.artists["곰미"]
        check(len(rec["images"]) == 3, "图片未跟随改名")
        check("gomdori.muousse.cake" in rec["aliases"],
              f"原写法未留作溯源别名: {rec['aliases']}")


@case("S语义", "纠正后同人合并不重复建档")
def s3():
    """zbibuji loom 与已有的 Zhibuiiloom 应合成一条，不是两位画师。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        make_sem(wb, SEM_SAMPLE)
        eng = wb.Engine()
        seed(wb, eng, "Zhibuiiloom", 4)
        seed(wb, eng, "zbibuji loom", 3)
        check(len(eng.artists) == 1, f"同人被拆成两条: {list(eng.artists)}")
        rec = eng.artists["Zhibuiiloom"]
        check(len(rec["images"]) == 7, f"合并后图片数错: {len(rec['images'])}")
        check("zbibuji loom" in rec["aliases"], "错拼未留作别名")


@case("S语义", "别名回填提高核验命中")
def s4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        make_sem(wb, SEM_SAMPLE)
        eng = wb.Engine()
        seed(wb, eng, "soresaki", 1)
        check("1100_2299" in eng.semantic_aliases("soresaki"), "别名映射缺失")
        # 已入库的存量记录：重载时应自动回填
        eng.save()
        eng2 = wb.Engine()
        check("1100_2299" in eng2.artists["soresaki"]["aliases"],
              f"重载后别名未回填: {eng2.artists['soresaki']['aliases']}")


@case("S语义", "加载时清除通用词别名")
def s5():
    """通用词曾污染 Zhibuiiloom 的别名，加载时必须清掉。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        make_sem(wb, SEM_SAMPLE)
        wb.DATA_DIR.mkdir(parents=True, exist_ok=True)
        wb.DATA_FILE.write_text(json.dumps({"artists": [{
            "name": "Zhibuiiloom",
            "aliases": ["审美积累", "织布机loom"],
            "images": [{"src": "https://x/a.jpg", "file": "", "conf": "single"}],
        }]}, ensure_ascii=False), encoding="utf-8")
        eng = wb.Engine()
        al = eng.artists["Zhibuiiloom"]["aliases"]
        check("审美积累" not in al, f"通用词别名未清除: {al}")
        check("织布机loom" in al, "误删了正常别名")
        saved = json.loads(wb.DATA_FILE.read_text(encoding="utf-8"))
        check("审美积累" not in saved["artists"][0]["aliases"], "清理未落盘")


@case("S语义", "映射缺失与损坏均安全降级")
def s6():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        check(not wb.SEMANTIC_FILE.exists(), "隔离目录不应有映射文件")
        eng = wb.Engine()
        check(eng._sem == {"generic": {}, "rename": {}, "aliases": {}},
              "缺失时应为空映射")
        check(seed(wb, eng, "米室", 2) == 2, "无映射时采集应正常")
        check(not eng.is_generic_word("米室"), "空映射误判为通用词")
    with tempfile.TemporaryDirectory() as td2:
        wb2 = make_wb(td2)
        wb2.SEMANTIC_FILE.write_text("{坏掉的JSON", encoding="utf-8")
        eng2 = wb2.Engine()
        check(eng2._sem["generic"] == {}, "损坏映射未安全降级")
        check(seed(wb2, eng2, "米室", 1) == 1, "损坏映射导致采集失败")


@case("S语义", "真实映射表内容自洽")
def s8():
    """交付的映射表本身必须自洽，否则会引入新错误。"""
    f = ROOT / "语义映射.json"
    if not f.exists():
        return
    d = json.loads(f.read_text(encoding="utf-8"))
    gen, ren = d.get("通用词") or {}, d.get("改名") or {}
    both = {k for k in gen if not k.startswith("_")} & \
           {k for k in ren if not k.startswith("_")}
    check(not both, f"通用词与改名冲突: {both}")
    bad = [(k, v) for k, v in ren.items()
           if not k.startswith("_") and v in gen]
    check(not bad, f"改名目标是通用词: {bad}")
    for nm, als in (d.get("补别名") or {}).items():
        if nm.startswith("_") or not isinstance(als, list):
            continue
        hit = [x for x in als if x in gen]
        check(not hit, f"{nm} 的别名含通用词: {hit}")
        check(nm not in gen, f"{nm} 既是画师又是通用词")


@case("S语义", "笔记正文必须存盘")
def s9():
    """
    小红书 token 会失效，失效后笔记再也打不开。语义判定的证据全在正文里，
    不存盘就等于证据永久蒸发（第1篇 Z3zz 的正文已经因此丢失）。
    """
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        desc = "画师：米室\n#插画师推荐[话题]#"
        note = {"title": "美图分享", "author": "作者", "desc": desc,
                "url": "http://n/1", "images": ["a"]}
        plan = [{"artist": "米室", "style": "", "image_url": "http://img/1",
                 "seq": 1, "confidence": "single"}]
        eng._ingest(FakeCtx(), note, plan, note["url"])
        nt = eng.artists["米室"]["notes"][0]
        check(nt.get("desc") == desc, f"正文未存盘: {nt.get('desc')!r}")
        check(nt.get("img_count") == 1, f"图片数未存: {nt.get('img_count')}")
        # 重启后仍在，且旧记录缺正文时会趁 token 有效补上
        eng.save()
        eng2 = wb.Engine()
        check(eng2.artists["米室"]["notes"][0].get("desc") == desc,
              "重启后正文丢失")
        eng2.artists["米室"]["notes"][0].pop("desc")
        eng2._ingest(FakeCtx(), note, plan, "http://n/1")
        check(eng2.artists["米室"]["notes"][0].get("desc") == desc,
              "旧记录未回填正文")


@case("I身份", "主名胜过他人别名")
def i6():
    """
    风险C：「米室」被登记为甲的别名时，米室自己的图不能被甲吞走。
    resolve 必须两遍匹配：先全局比主名，再比别名。
    """
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "画师甲", "a1")
        # 手工注入：甲的别名里有真画师「米室」（弱证据，无来源）
        eng.set_alias(eng.artists["画师甲"], "米室", eng.ALIAS_TIER_WEAK)
        ingest_one(eng, "米室", "m1")
        check("米室" in eng.artists, f"米室的图被甲吞掉: {list(eng.artists)}")
        check(len(eng.artists["米室"]["images"]) == 1, "米室未拿到自己的图")
        check(len(eng.artists["画师甲"]["images"]) == 1, "甲多拿了不属于他的图")
        # 弱别名不参与认人
        check(eng.resolve("米室") == "米室", "主名未优先于别名")


@case("I身份", "弱别名不参与认人")
def i7():
    """帖内共现提取的写法差异只是弱证据，不能据此认定同一人。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "画师甲", "a1")
        eng.set_alias(eng.artists["画师甲"], "画师乙", eng.ALIAS_TIER_WEAK)
        check(eng.resolve("画师乙") is None, "弱别名不应认人")
        check("画师乙" not in eng.strong_aliases(eng.artists["画师甲"]),
              "弱别名混进了强别名")
        # 用户主动操作可按弱别名找到对象
        check(eng.resolve("画师乙", allow_weak=True) == "画师甲",
              "用户主动操作应能按别名定位")


@case("I身份", "明示账号别名可认人")
def i8():
    """「X：@TeraAru6262」是博主明示的身份声明，属于强证据，应认人。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        d = ("今天推荐的插画师是X上的画师：あるてら ☾ 老师\n"
             "X （推特）：@TeraAru6262")
        note = {"title": "Vol.268", "author": "a", "desc": d,
                "url": "http://n/1", "images": ["x"] * 3}
        plan = E.build_plan(note, 1)
        eng._ingest(FakeCtx(), note, plan, note["url"])
        check(len(eng.artists) == 1, f"同人被拆开: {list(eng.artists)}")
        rec = eng.artists["あるてら"]
        check("TeraAru6262" in rec["aliases"], f"明示账号未收为别名: {rec['aliases']}")
        check(eng.alias_tier(rec, "TeraAru6262") == eng.ALIAS_TIER_POST,
              f"明示账号应定级为帖内明示: {eng.alias_tier(rec, 'TeraAru6262')}")
        # 反向：后续笔记直接用账号名，应认成同一人而不是新建
        ingest_one(eng, "TeraAru6262", "t2")
        check(len(eng.artists) == 1, f"账号反向出现被拆开: {list(eng.artists)}")


@case("I身份", "别名等级只升不降")
def i9():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        # 通用词表由语义映射提供，测试隔离后需自行造一份
        wb.SEMANTIC_FILE.write_text(json.dumps(
            {"通用词": {"审美积累": "栏目名"}}, ensure_ascii=False),
            encoding="utf-8")
        eng = wb.Engine()
        ingest_one(eng, "画师甲", "a1")
        rec = eng.artists["画师甲"]
        eng.set_alias(rec, "别名X", eng.ALIAS_TIER_D)
        check(eng.alias_tier(rec, "别名X") == eng.ALIAS_TIER_D, "权威级未写入")
        eng.set_alias(rec, "别名X", eng.ALIAS_TIER_WEAK)
        check(eng.alias_tier(rec, "别名X") == eng.ALIAS_TIER_D,
              f"强证据被弱证据降级: {eng.alias_tier(rec, '别名X')}")
        # 占位名与通用词任何等级都不收
        check(eng.is_generic_word("审美积累"), "语义映射未生效，用例无效")
        for bad in ["待认领", "审美积累"]:
            eng.set_alias(rec, bad, eng.ALIAS_TIER_D)
            check(bad not in rec["aliases"], f"{bad} 被收作别名")


@case("I身份", "uid 不可变且随改名保留")
def i10():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "旧名", "o1")
        uid = eng.artists["旧名"].get("uid")
        check(uid, "未生成 uid")
        ok, err = eng.rename_artist("旧名", "新名")
        check(ok, err)
        check(eng.artists["新名"].get("uid") == uid, "改名后 uid 变了")
        check(eng.resolve_by_uid(uid) == "新名", "uid 反查失败")
        # 落盘重载后 uid 稳定
        eng.save()
        eng2 = wb.Engine()
        check(eng2.artists["新名"].get("uid") == uid, "重启后 uid 丢失")


@case("I身份", "存量别名迁移分级")
def i11():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DATA_DIR.mkdir(parents=True, exist_ok=True)
        wb.DATA_FILE.write_text(json.dumps({"artists": [
            {"name": "あるてら", "aliases": ["TeraAru6262"], "styles": [],
             "notes": [], "images": [{"src": "https://x/a.jpg", "file": "",
                                     "conf": "single"}],
             "verify": {"state": "matched", "id": "76259",
                        "hits": [{"ours": "TeraAru6262", "field": "other_names",
                                  "theirs": "teraaru6262"}]}},
            {"name": "老画师", "aliases": ["老账号"], "styles": [],
             "notes": [], "images": []},
        ]}, ensure_ascii=False), encoding="utf-8")
        eng = wb.Engine()
        rec = eng.artists["あるてら"]
        check(eng.alias_tier(rec, "TeraAru6262") == eng.ALIAS_TIER_D,
              f"D站核验过的别名未升为权威: {eng.alias_tier(rec, 'TeraAru6262')}")
        check("TeraAru6262" in eng.strong_aliases(rec), "权威别名未进强别名")
        # 无核验记录的存量别名按明示级迁移，仍可认人（避免拆成两条）
        rec2 = eng.artists["老画师"]
        check(eng.alias_tier(rec2, "老账号") == eng.ALIAS_TIER_POST,
              f"存量别名迁移等级错: {eng.alias_tier(rec2, '老账号')}")
        check(eng.resolve("老账号") == "老画师", "存量别名迁移后认不出人")
        check(eng.artists["あるてら"].get("uid"), "迁移未补 uid")


@case("I身份", "身份冲突只报告不合并")
def i12():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        # 构造异常：两个 uid 相同的记录
        eng.artists["甲"] = {"name": "甲", "uid": "SAME_UID", "images": [],
                             "aliases": [], "alias_src": {}, "styles": [],
                             "notes": []}
        eng.artists["乙"] = {"name": "乙", "uid": "SAME_UID", "images": [],
                             "aliases": ["丙"], "alias_src": {"丙": 2},
                             "styles": [], "notes": []}
        eng.artists["丁"] = {"name": "丁", "uid": "OTHER", "images": [],
                             "aliases": ["丙"], "alias_src": {"丙": 2},
                             "styles": [], "notes": []}
        rep = eng._detect_identity_conflicts()
        check(any("SAME_UID" in x for x in rep), f"未检出 uid 冲突: {rep}")
        check(any("丙" in x for x in rep), f"未检出别名冲突: {rep}")
        check(len(eng.artists) == 3, "冲突检测不应自动合并或删除")


@case("I身份", "归属冲突被记录不静默")
def i13():
    """风险A：同一张图被两篇笔记归给不同画师，后到者必须留痕。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        shared = ("http://sns-webpic-qc.xhscdn.com/2026/x/SIG/"
                  "spectrum/SHARED_IMG!nd_dft_wlteh_webp_3")
        n1 = eng._ingest(FakeCtx(),
                         {"title": "帖一", "author": "a", "desc": "",
                          "url": "http://n/1", "images": [shared]},
                         [{"artist": "画师甲", "style": "", "image_url": shared,
                           "seq": 1, "confidence": "single"}], "http://n/1")
        n2 = eng._ingest(FakeCtx(),
                         {"title": "帖二", "author": "b", "desc": "",
                          "url": "http://n/2", "images": [shared]},
                         [{"artist": "画师乙", "style": "", "image_url": shared,
                           "seq": 1, "confidence": "single"}], "http://n/2")
        check(n1 == 1 and n2 == 0, f"去重行为异常: {n1},{n2}")
        check(eng._conflicts, "归属冲突未被记录（静默吞掉了画师乙）")
        c = eng._conflicts[0]
        check(c["want"] == "画师乙" and c["held_by"] == "画师甲",
              f"冲突记录内容错: {c}")
        check(c["note_url"] == "http://n/2", "未记录来源笔记")
        # 落盘且重载后仍在，不重复记录
        check(wb.CONFLICT_FILE.is_file(), "冲突未落盘")
        eng._ingest(FakeCtx(),
                    {"title": "帖二", "author": "b", "desc": "",
                     "url": "http://n/2", "images": [shared]},
                    [{"artist": "画师乙", "style": "", "image_url": shared,
                      "seq": 1, "confidence": "single"}], "http://n/2")
        check(len(eng._conflicts) == 1, f"冲突重复记录: {len(eng._conflicts)}")
        eng2 = wb.Engine()
        check(len(eng2._conflicts) == 1, "重启后冲突记录丢失")


@case("I身份", "同ID画师自动合并")
def i14():
    """风险B 治本：核验到同一 D 站 ID 即权威证据，自动合并不需点按钮。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        ingest_one(eng, "Z3zz", "z1")
        ingest_one(eng, "Z3zz4", "z2")
        ingest_one(eng, "米室", "m1")
        for nm in ["Z3zz", "Z3zz4"]:
            eng.artists[nm]["verify"] = {"state": "matched", "id": "261471"}
        eng.artists["米室"]["verify"] = {"state": "matched", "id": "192433"}
        before = sum(len(a["images"]) for a in eng.artists.values())
        n = eng._auto_merge_same_id()
        check(n == 1, f"应合并 1 组: {n}")
        check("Z3zz4" not in eng.artists, "被合并条未移除")
        check("米室" in eng.artists, "不同 ID 的被误合并")
        check(len(eng.artists["Z3zz"]["images"]) == before - 1,
              f"合并丢图: {len(eng.artists['Z3zz']['images'])}")
        check("Z3zz4" in eng.artists["Z3zz"]["aliases"], "被并主名未留作别名")
        check(eng.alias_tier(eng.artists["Z3zz"], "Z3zz4") == eng.ALIAS_TIER_D,
              "合并别名未标为权威级")
        # 幂等：再跑一次不应产生变化
        check(eng._auto_merge_same_id() == 0, "自动合并不幂等")


@case("I身份", "自动合并不受上限限制")
def i15():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        eng.max_per_artist = 3
        ingest_one(eng, "甲", "a1")
        ingest_one(eng, "乙", "b1")
        for nm in ["甲", "乙"]:
            eng.artists[nm]["verify"] = {"state": "matched", "id": "999"}
        eng._auto_merge_same_id()
        # 合并后只剩一条，且两张图都在（不因上限丢图）；保留哪条由内部排序决定
        remain = [n for n in ("甲", "乙") if n in eng.artists]
        check(len(remain) == 1, f"应只剩一条: {remain}")
        kept = eng.artists[remain[0]]
        check(len(kept["images"]) == 2,
              f"自动合并丢图: {len(kept['images'])}")


@case("Z搜图", "面板与接口齐备")
def z7():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for tok in ["btnSauce", "sauceModal", "sauceKey", "sauceTest",
                "sauceClear", "sauceDot", "/api/s_cred", "/api/s_probe"]:
        check(tok in html, f"界面缺少 {tok}")
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    for tok in ["/api/s_cred_save", "/api/s_cred_clear", "/api/s_probe",
                "class SauceNao", "SAUCE_FILE"]:
        check(tok in src, f"服务缺少 {tok}")
    # 凭证绝不能进交付文件
    check("搜图凭证.json" in src, "凭证文件名未定义")


@case("Y铁证", "账号反查须账号位精确")
def y1():
    """asikumin 不能蹭到 asikumin123 这类别人的账号。"""
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DANBOORU._login, wb.DANBOORU._key = "u", "k"
        rows = [
            {"artist_id": 162830, "url": "https://x.com/asikumin",
             "is_active": False},
            {"artist_id": 999999, "url": "https://x.com/asikumin123",
             "is_active": True},
            {"artist_id": 888888, "url": "https://x.com/xxasikumin",
             "is_active": True},
        ]
        wb.DANBOORU.get = lambda *a, **k: (rows, None)
        got = wb.DANBOORU.who_by_handle("asikumin")
        ids = {g[0] for g in got}
        check(ids == {"162830"}, f"账号位不精确，蹭到他人: {ids}")


@case("Y铁证", "账号可自动定案")
def y2():
    """名字搜不到时，账号铁证应自动定案，不需要人工过目。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.DANBOORU.get = lambda path, *a, **k: (
            [{"artist_id": 162830, "url": "https://x.com/asikumin",
              "is_active": False}], None) if "artist_urls" in path else (
            {"id": 162830, "name": "dayama", "other_names": ["あさひ"]}, None)
        # 恢复真实反查实现（底层 get 已被桩接管，不会联网）
        wb.DANBOORU.who_by_handle = orig_who.__get__(wb.DANBOORU)
        seed(wb, eng, "asikumin", 1)
        eng.verify_one("asikumin")
        v = eng.artists["asikumin"]["verify"]
        check(v["state"] == "matched", f"账号铁证未定案: {v['state']}")
        check(v["id"] == "162830", f"定案ID错: {v['id']}")
        check(v.get("auto") is True, "未标记为自动定案")
        check("账号铁证" in v.get("evidence", ""), "缺少铁证依据")
        rec = [r for r in eng.data() if r["name"] == "asikumin"][0]
        check(rec["d_direct"] is True and rec["d_url"].endswith("/artists/162830"),
              f"未直连真身: {rec['d_url']}")


@case("Y铁证", "账号有歧义时不定案")
def y3():
    """两个不同条目都登记了同名账号 → 证据冲突，绝不猜。"""
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "none", "candidates": [], "message": "搜不到"}
        wb, eng = make_eng_verify(td, stub)
        wb.DANBOORU.get = lambda *a, **k: ([
            {"artist_id": 111, "url": "https://x.com/somename",
             "is_active": True},
            {"artist_id": 222, "url": "https://x.com/somename",
             "is_active": True}], None)
        seed(wb, eng, "somename", 1)
        eng.verify_one("somename")
        v = eng.artists["somename"]["verify"]
        check(v["id"] == "", f"证据冲突却定案: {v['id']}")
        check(v["state"] != "matched", "冲突时不应判为命中")


@case("Y铁证", "短名不做账号反查")
def y4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.DANBOORU._login, wb.DANBOORU._key = "u", "k"
        called = []
        wb.DANBOORU.get = lambda *a, **k: (called.append(1), ([], None))[1]
        for h in ["", "ab", "abc", None, "@a"]:
            check(wb.DANBOORU.who_by_handle(h) == [], f"短名未拦: {h!r}")
        check(not called, "短名不应发起请求")


@case("X指向", "真实数据无错误指向")
def x5():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    bad = []
    for a in d["artists"]:
        v = a.get("verify") or {}
        st = v.get("state")
        if st in ("missing", "suspect", "error", "absent") and v.get("id"):
            bad.append(f"{a['name']}:{st} 却留 id={v['id']}")
        if v.get("id") and st not in ("matched", "confirmed"):
            bad.append(f"{a['name']}:{st} 不应有 id")
    check(not bad, f"存在错误指向: {bad}")


@case("V自动核验", "疑似不自动合并")
def v4():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "near", "candidates": [
                {"id": "9", "name": "almost_same", "url": "u",
                 "match": {"verdict": "near", "hits": [],
                           "nears": [{"ours": nm, "theirs": "almost_sam",
                                      "distance": 1, "similarity": 0.9}]}}],
                "message": "疑似"}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "原名", 2)
        eng.verify_one("原名")
        check("原名" in eng.artists, "疑似不应改名或合并")
        check(len(eng.artists) == 1, "疑似不应新增条目")
        check(eng.artists["原名"]["verify"]["state"] == "suspect", "应标为待确认")


@case("V自动核验", "已确认默认跳过")
def v5():
    with tempfile.TemporaryDirectory() as td:
        calls = []
        def stub(nm, aliases=None):
            calls.append(nm)
            return {"verdict": "exact", "candidates": [
                {"id": "1", "name": "x", "match": {"hits": [], "nears": []}}],
                "message": ""}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "甲", 1)
        eng.verify_one("甲")
        eng.artists["甲"]["verify"]["state"] = "confirmed"
        n = len(calls)
        eng.verify_one("甲")
        check(len(calls) == n, "已确认的不应重复请求")
        eng.verify_one("甲", force=True)
        check(len(calls) == n + 1, "force 应允许重核")


@case("V自动核验", "人工确认与否认")
def v6():
    with tempfile.TemporaryDirectory() as td:
        def stub(nm, aliases=None):
            return {"verdict": "near", "candidates": [
                {"id": "777", "name": "cand", "match": {"hits": [], "nears": []}}],
                "message": ""}
        wb, eng = make_eng_verify(td, stub)
        seed(wb, eng, "乙", 1)
        eng.verify_one("乙")
        ok, err = eng.confirm_verify("乙")
        check(ok, err)
        v = eng.artists["乙"]["verify"]
        check(v["state"] == "confirmed" and v["id"] == "777", f"确认失败: {v}")
        ok, err = eng.confirm_verify("乙", reject=True)
        check(ok, err)
        check(eng.artists["乙"]["verify"]["state"] == "absent", "否认未生效")


@case("V自动核验", "非法确认被拒")
def v7():
    with tempfile.TemporaryDirectory() as td:
        wb, eng = make_eng_verify(td, lambda n, a=None: {"verdict": "none", "candidates": []})
        seed(wb, eng, "丙", 1)
        for aid in ["", "abc", "12a", None]:
            ok, err = eng.confirm_verify("丙", aid)
            check(ok is False and err, f"非法ID应被拒: {aid!r}")
        ok, err = eng.confirm_verify("不存在的人", "1")
        check(ok is False and err, "不存在的画师应被拒")


@case("V自动核验", "确认后按钮直连条目")
def v8():
    with tempfile.TemporaryDirectory() as td:
        wb, eng = make_eng_verify(td, lambda n, a=None: {
            "verdict": "exact", "candidates": [
                {"id": "149913", "name": "zhibuji_loom",
                 "match": {"hits": [], "nears": []}}], "message": ""})
        seed(wb, eng, "Zhibuiiloom", 1)
        eng.verify_one("Zhibuiiloom")
        eng.confirm_verify("Zhibuiiloom")
        wb.ENGINE = eng
        rec = [x for x in eng.data() if x["name"] == "Zhibuiiloom"][0]
        check(rec["d_direct"] is True, "确认后应直连")
        check(rec["d_url"].endswith("/artists/149913"), f"链接错: {rec['d_url']}")


@case("V自动核验", "未确认仍走检索页")
def v9():
    with tempfile.TemporaryDirectory() as td:
        wb, eng = make_eng_verify(td, lambda n, a=None: {"verdict": "none", "candidates": []})
        seed(wb, eng, "丁", 1)
        rec = eng.data()[0]
        check(rec["d_direct"] is False, "未确认不应直连")
        check("/artists?" in rec["d_url"], "未确认应走检索页")


@case("V自动核验", "接口与开关齐备")
def v10():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    for k in ["/api/d_verify_all", "/api/d_verify_one", "/api/d_confirm"]:
        check(k in src, f"缺少接口 {k}")
    check("auto_verify" in src, "缺少自动核验开关")
    check('"verifying"' in src, "缺少核验中状态")
    i = src.find('if p == "/api/d_verify_all"')
    seg = src[i:i + 400]
    check("ENGINE.phase" in seg, "批量核验未做运行中保护")


@case("V自动核验", "前端徽章与兜底按钮")
def v11():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ["vBadge", "V_TXT", "data-vok", "data-vno", "btnVerifyAll",
              "autoVerify", "d_verify_one", "d_verify_all", "d_confirm",
              "verify_stat"]:
        check(k in html, f"界面缺少要素 {k}")
    check("采完自动核验" in html, "缺少自动核验开关文案")
    check("补核验" in html, "缺少兜底按钮")


@case("V自动核验", "指纹含核验统计")
def v12():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    i = html.find("const sig = s.artist_count")
    seg = html[i:i + 220]
    check("verify_stat" in seg, "指纹未含核验统计，徽章不会刷新")


# ============ W. 死锁与测试隔离 ============
@case("W死锁", "持锁期间不得调save或log")
def w1():
    """save() 内部会取 self.lock，持锁再调必然死锁。"""
    lines = (ROOT / "工作台.py").read_text(encoding="utf-8").splitlines()
    inlock, lockind, bad = False, 0, []
    for i, l in enumerate(lines, 1):
        if not l.strip():
            continue
        ind = len(l) - len(l.lstrip())
        if "with self.lock:" in l:
            inlock, lockind = True, ind
            continue
        if inlock:
            if ind <= lockind:
                inlock = False
            elif "self.save()" in l or "self.log(" in l:
                bad.append(f"第{i}行: {l.strip()[:50]}")
    check(not bad, "持锁期间调用了 save/log，会死锁:\n" + "\n".join(bad))


@case("W死锁", "确认操作能快速返回")
def w2():
    with tempfile.TemporaryDirectory() as td:
        wb, eng = make_eng_verify(td, lambda n, a=None: {
            "verdict": "near", "candidates": [
                {"id": "42", "name": "cand", "match": {"hits": [], "nears": []}}],
            "message": ""})
        seed(wb, eng, "锁测试", 1)
        eng.verify_one("锁测试")
        done = []

        def run():
            ok, err = eng.confirm_verify("锁测试")
            done.append(ok)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=8)
        check(not t.is_alive(), "确认操作卡住，疑似死锁")
        check(done and done[0], "确认应成功")


@case("W死锁", "测试隔离真实凭证")
def w3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        check(not wb.DANBOORU.configured(),
              "测试实例读到了真实凭证，会意外联网")
        check(wb.CRED_FILE.parent == Path(td), "凭证路径未隔离到临时目录")
        check(wb.ACCOUNTS_FILE.parent == Path(td), "账号配置未隔离")


@case("W死锁", "核验测试禁止真实联网")
def w4():
    with tempfile.TemporaryDirectory() as td:
        wb, eng = make_eng_verify(td, lambda n, a=None: {
            "verdict": "none", "candidates": [], "message": ""})
        raised = False
        try:
            wb.DANBOORU.get("/artists/1.json")
        except AssertionError:
            raised = True
        check(raised, "底层 get 未被堵死，测试可能真的联网")


# ============ J. D站链接 ============
@case("J链接", "主入口是画师条目检索")
def j1():
    u = E.danbooru_url("米室", [])
    check(u.startswith("https://danbooru.donmai.us/artists?"), f"入口应为 artists: {u}")
    check("search%5Bany_name_matches%5D=" in u, f"缺少 any_name_matches: {u}")
    check("search%5Border%5D=created_at" in u, f"缺少排序参数: {u}")
    check("commit=Search" in u, f"缺少 commit: {u}")
    check("/posts?tags=" not in u, "主入口不应是标签搜图")


@case("J链接", "检索保留原名不替换")
def j2():
    """原名必须原样送检索，不能被换成罗马字别名。"""
    for nm, al in [("猫屋敷ぷしお", ["neko_pushio"]),
                   ("あるてら", ["TeraAru6262"]),
                   ("Blanc.ブラン", []), ("米室", []), ("りたお", None)]:
        u = E.danbooru_url(nm, al)
        from urllib.parse import unquote as _u
        got = _u(u.split("any_name_matches%5D=")[1].split("&")[0])
        check(got == nm, f"{nm} 被改写成 {got}")
        check(E.danbooru_query(nm) == nm, f"查询名被改写: {nm}")


@case("J链接", "与用户给定格式一致")
def j3():
    want = ("https://danbooru.donmai.us/artists?commit=Search"
            "&search%5Bany_name_matches%5D=%E7%B1%B3%E5%AE%A4"
            "&search%5Border%5D=created_at")
    check(E.danbooru_url("米室") == want,
          f"与给定链接不一致:\n实得 {E.danbooru_url('米室')}\n期望 {want}")


@case("J链接", "去@与首尾空白")
def j4():
    check(E.danbooru_query("@handle") == "handle", "@前缀未去掉")
    check(E.danbooru_query("  米室  ") == "米室", "空白未清理")
    check(E.danbooru_query(None) == "" and E.danbooru_query("") == "", "空值未兜底")


@case("J链接", "别名与标签作为附加入口")
def j5():
    alt = E.danbooru_alt_url("猫屋敷ぷしお", ["neko_pushio"])
    check("/artists?" in alt and "neko_pushio" in alt, f"别名入口错: {alt}")
    check(E.danbooru_alt_url("米室", []) == "", "无别名应返回空")
    check(E.danbooru_alt_url("甲", ["甲"]) == "", "同名别名不应产生入口")
    p = E.danbooru_posts_url("猫屋敷ぷしお", ["neko_pushio"])
    check(p.startswith("https://danbooru.donmai.us/posts?tags="), f"标签入口错: {p}")
    check(p.endswith("neko_pushio"), "标签入口应用罗马字")


@case("J链接", "特殊字符安全编码")
def j6():
    for n in ['a"b', "a<b>", "a&b", "a b#c", "../../x", "a=b"]:
        u = E.danbooru_url(n, [])
        check("\\" not in u and '"' not in u and "<" not in u, f"危险字符: {n} -> {u}")
        val = u.split("any_name_matches%5D=")[1].split("&search")[0]
        check("&" not in val and "=" not in val, f"参数未编码可注入: {n} -> {val}")
    check(E.danbooru_url("", []) == "", "空名应返回空链接")


@case("J链接", "真实数据均为检索入口")
def j7():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    for a in d["artists"]:
        u = E.danbooru_url(a["name"], a.get("aliases"))
        check("/artists?" in u and "any_name_matches" in u, f"{a['name']} 入口不对: {u}")


@case("J链接", "前端文案与入口一致")
def j8():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("在 D 站找这位画师" in html, "卡片文案未更新为找画师")
    check("d_query" in html, "未显示实际检索名")
    check("d_posts_url" in html and "d_alt_url" in html, "缺少附加入口")
    check("在 D 站看作品" not in html, "仍残留旧的看作品文案")


# ============ N. 排印与呈现规范 ============
@case("N规范", "字号收敛到音阶")
def n1():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = html[:html.find("</style>")]
    hard = re.findall(r"font-size:([\d.]+)px", css)
    # 仅允许空态图标一处装饰性硬编码
    check(len(hard) <= 1, f"仍有 {len(hard)} 处硬编码字号未走音阶: {hard}")
    for v in ["--t-display", "--t-title", "--t-head", "--t-body",
              "--t-label", "--t-meta", "--t-micro"]:
        check(v + ":" in css, f"缺少音阶变量 {v}")
    check(css.count("font-size:var(--t-") >= 40, "音阶未被广泛使用")


@case("N规范", "最小字号不低于10px")
def n2():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]
    m = re.search(r"--t-micro:(\d+)px", css)
    check(m and int(m.group(1)) >= 10, "最小字号低于10px，可读性不达标")


@case("N规范", "中日文混排与等宽数字")
def n3():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]
    check("Yu Gothic" in css and "Microsoft YaHei" in css, "缺少中日文字体回退")
    check("tabular-nums" in css, "数字未等宽，统计跳动")
    check("palt" in css, "未启用中日文标点挤压")
    check("text-wrap:balance" in css, "标题未做换行平衡")


@case("N规范", "间距走栅格变量")
def n4():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]
    for v in ["--s1:", "--s2:", "--s3:", "--s4:", "--s5:", "--s6:"]:
        check(v in css, f"缺少间距变量 {v}")
    check(css.count("var(--s") >= 30, "间距变量未被广泛使用")


@case("N规范", "卡片等高且不溢出")
def n5():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = html[:html.find("</style>")]
    check(re.search(r"\.card\{[^}]*height:\d+px", css), "卡片未固定高度，会参差")
    check(".cbody{" in css and ".cleft{" in css and ".cright{" in css,
          "缺少横向画廊布局结构")


@case("N规范", "图像装裱语言统一")
def n6():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]
    # 主图与缩略图均铺满画框；灯箱大图完整显示
    check(re.search(r"\.hero img\.hero-fg\{[^}]*object-fit:cover", css), "主图未铺满画框")
    check(re.search(r"\.im img\{[^}]*object-fit:cover", css), "缩略图装裱不一致")
    check(re.search(r"\.lb-stage img\{[^}]*object-fit:contain", css), "灯箱应完整显示原图")
    check(".gframe{" in css, "图廊缺少统一画框")


@case("N规范", "无障碍语义齐备")
def n7():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for k in ['role="dialog"', 'aria-modal="true"', 'role="list"',
              'role="log"', 'aria-live="polite"', 'role="alert"',
              'aria-label=', 'decoding="async"']:
        check(k in html, f"缺少无障碍标记 {k}")
    check(":focus-visible" in html, "缺少键盘焦点样式")
    check("prefers-reduced-motion" in html, "缺少减弱动效降级")


@case("N规范", "灯箱焦点与滚动管理")
def n8():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("LB_FOCUS" in html, "缺少焦点归还机制")
    check("document.body.style.overflow = 'hidden'" in html, "打开灯箱未锁定背景滚动")
    check("document.body.style.overflow = ''" in html, "关闭灯箱未解锁滚动")


@case("N规范", "空态含上手引导")
def n9():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("emptyGuide" in html and "EMPTY_STEPS" in html, "缺少空态引导")
    check(html.count('class="step"') >= 3, "引导步骤不足三步")
    check("没有匹配的画师" in html and "还没有采集到画师" in html, "两类空态未区分")


@case("N规范", "文字对比度达AA")
def n10():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]

    def lum(h):
        h = h.lstrip("#")
        ch = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(ch[0]) + 0.7152 * f(ch[1]) + 0.0722 * f(ch[2])

    def ratio(a, b):
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    def var(name):
        m = re.search(r"--" + name + r":(#[0-9A-Fa-f]{6})", css)
        return m.group(1) if m else None

    for fg in ["txt", "txt2", "dim", "dim2"]:
        for bg in ["panel", "bg"]:
            a, b = var(fg), var(bg)
            check(a and b, f"缺少颜色变量 {fg}/{bg}")
            r = ratio(a, b)
            check(r >= 4.5, f"{fg} on {bg} 对比度 {r:.2f} 低于 AA 4.5")


@case("N规范", "语义色与画框走令牌")
def n11():
    css = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = css[:css.find("</style>")]
    for v in ["--ok-bg:", "--warn-bg:", "--danger-bg:", "--info-bg:",
              "--sakura-bg:", "--fuji-bg:", "--mat:", "--scroll:"]:
        check(v in css, f"缺少设计令牌 {v}")
    check(css.count("var(--mat)") >= 3, "画框底未统一走令牌")
    check("background:var(--scroll)" in css, "滚动条未走令牌")


@case("N规范", "氛围背景走令牌且可关闭")
def n12():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = html[:html.find("</style>")]
    for v in ["--amb-blur:", "--amb-bright:", "--amb-sat:", "--amb-scale:"]:
        check(v in css, f"缺少氛围令牌 {v}")
    # 卡片与焦点区必须共用同一套参数，避免两处视觉不一致
    seg = css[css.find(".card-amb img"):css.find(".card-amb::after")]
    for v in ["--amb-blur", "--amb-bright", "--amb-sat", "--amb-scale"]:
        check(v in seg, f"卡片氛围未走令牌 {v}")
    check("body.no-amb .card-amb" in css, "缺少氛围关闭样式")
    check("body.no-amb .spot-art" in css, "关闭开关未覆盖焦点区")
    for tok in ["ambLayer(", "function ambOk", "function ambFail",
                'id="ambBg"', "readPref('ambBg'", "savePref('ambBg'"]:
        check(tok in html, f"缺少氛围实现 {tok}")
    # 背景层必须是装饰、不可交互，且不能虚化清晰主图
    check('class="card-amb" aria-hidden="true"' in html, "氛围层未标记为装饰")
    check(".hero img.hero-fg" in css, "清晰主图样式丢失")
    hero = css[css.find(".hero img.hero-fg"):css.find(".hero:hover img.hero-fg")]
    check("blur(" not in hero, "清晰主图被虚化")


@case("N规范", "氛围层失效可退回纯色")
def n13():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    i = html.find("function ambFail")
    seg = html[i:i + 420]
    check("data.retried" in seg or "dataset.retried" in seg, "缺少本地备份回退")
    check("box.remove()" in seg, "彻底失效时未移除氛围层")
    # 卡片本身必须是定位容器，否则氛围层会溢出到页面
    css = html[:html.find("</style>")]
    card = css[css.find("\n.card{"):css.find("@keyframes rise")]
    check("position:relative" in card, "卡片未设为定位容器")


# ============ O. 图标体系 ============
@case("O图标", "图标库完整且无断链")
def o1():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'<symbol id="i-([\w-]+)"', html))
    check(len(ids) >= 25, f"图标数量不足: {len(ids)}")
    refs = set(re.findall(r'href="#i-([\w-]+)"', html))
    refs |= set(re.findall(r"svgIcon\('([\w-]+)'", html))
    missing = refs - ids
    check(not missing, f"引用了不存在的图标: {sorted(missing)}")


@case("O图标", "统一栅格与描边")
def o2():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    css = html[:html.find("</style>")]
    check(re.search(r"\.ic\{[^}]*stroke-width:1\.75", css), "描边宽度未统一")
    check("stroke-linecap:round" in css and "stroke-linejoin:round" in css,
          "端点未统一为圆角")
    check('viewBox="0 0 24 24"' in html, "图标未使用统一 24 栅格")
    check("currentColor" in css, "图标未继承文字颜色")


@case("O图标", "不再混用文字符号")
def o3():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    body = html[html.find("<body>"):]
    # 去掉脚本里的键盘提示文案后检查可见符号
    for ch in ["‹", "›", "✦", "▶"]:
        check(ch not in body, f"仍残留文字符号 {ch}，跨系统字形不一致")


@case("O图标", "纯图标按钮有无障碍标签")
def o4():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    for bid in ["lbPrev", "lbNext", "lbPrevT", "lbNextT", "lbClose"]:
        m = re.search(r'<button[^>]*id="' + bid + r'"[^>]*>', html)
        check(m, f"缺少按钮 {bid}")
        check("aria-label=" in m.group(0), f"{bid} 是纯图标按钮但缺少 aria-label")


@case("O图标", "应用图标文件齐备")
def o5():
    ico = ROOT / "应用图标.ico"
    png = ROOT / "应用图标.png"
    svg = ROOT / "应用图标.svg"
    for f in (ico, png, svg):
        check(f.is_file(), f"缺少图标文件 {f.name}")
    data = ico.read_bytes()
    check(data[:4] == b"\x00\x00\x01\x00", "ICO 文件头不合法")
    count = int.from_bytes(data[4:6], "little")
    check(count >= 5, f"ICO 尺寸档位不足: {count}")
    sizes = [data[6 + 16 * i] or 256 for i in range(count)]
    for need in (16, 32, 48, 256):
        check(need in sizes, f"ICO 缺少 {need}px 档位")


@case("O图标", "服务端提供图标路由")
def o6():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check('"/favicon.ico"' in src, "缺少 favicon 路由")
    check("image/x-icon" in src, "favicon 未按图标类型返回")
    check("def set_console_icon" in src, "缺少控制台窗口图标设置")
    check("SetCurrentProcessExplicitAppUserModelID" in src, "缺少任务栏独立归组标识")


@case("O图标", "网页图标与元信息")
def o7():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check('rel="icon"' in html, "缺少网页图标")
    check("/favicon.ico" in html, "未提供 ico 兜底")
    check('name="theme-color"' in html, "缺少浏览器主题色")
    check('name="application-name"' in html, "缺少应用名元信息")


@case("O图标", "快捷方式工具不静默覆盖")
def o8():
    f = ROOT / "创建桌面快捷方式.py"
    check(f.is_file(), "缺少快捷方式工具")
    src = f.read_text(encoding="utf-8")
    check("lnk.exists()" in src and "input(" in src, "同名快捷方式未先询问")
    check("IconLocation" in src, "快捷方式未挂图标")
    check("SHGetKnownFolderPath" in src, "未兼容桌面重定向")


# ============ E. 安全 ============
def start_server(wb, port):
    import http.server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), wb.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.4)
    return srv


def http_get(port, path):
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


@case("E安全", "图片接口路径穿越")
def e1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        # 在 ROOT 之外放一个机密文件
        secret = Path(td).parent / (Path(td).name + "_secret.txt")
        secret.write_text("SECRET", encoding="utf-8")
        inside = wb.IMG_DIR / "ok.jpg"
        inside.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        port = 8811
        srv = start_server(wb, port)
        try:
            attacks = [
                "../" + secret.name,
                "..%2f" + secret.name,
                "..%252f" + secret.name,
                "%2e%2e/" + secret.name,
                "....//..../" + secret.name,
                str(secret).replace("\\", "/"),
            ]
            leaked = []
            for a in attacks:
                code, body = http_get(port, "/img?p=" + a)
                if code == 200 and b"SECRET" in body:
                    leaked.append(a)
            check(not leaked, f"路径穿越泄露文件: {leaked}")
            code, body = http_get(port, "/img?p=" +
                                  urllib.parse.quote("采集结果/画师图片/ok.jpg"))
            check(code == 200, f"正常图片被误拦: {code}")
        finally:
            srv.shutdown()
            secret.unlink(missing_ok=True)


@case("E安全", "同前缀兄弟目录不可读")
def e2():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "proj"
        base.mkdir()
        sibling = Path(td) / "proj_evil"
        sibling.mkdir()
        (sibling / "s.txt").write_text("SECRET", encoding="utf-8")
        wb = load("wb_sib", ROOT / "工作台.py")
        wb.ROOT = base
        wb.DATA_DIR = base / "采集结果"
        wb.IMG_DIR = wb.DATA_DIR / "画师图片"
        wb.DATA_FILE = wb.DATA_DIR / "data.json"
        wb.IMG_DIR.mkdir(parents=True, exist_ok=True)
        port = 8812
        srv = start_server(wb, port)
        try:
            code, body = http_get(port, "/img?p=../proj_evil/s.txt")
            check(not (code == 200 and b"SECRET" in body),
                  "同前缀兄弟目录被读取（startswith 判据不严）")
        finally:
            srv.shutdown()


@case("E安全", "接口仅本机可达")
def e3():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check('("127.0.0.1"' in src or "'127.0.0.1'" in src, "未绑定回环地址")
    check("0.0.0.0" not in src, "不应监听所有网卡")


@case("E安全", "界面转义防注入")
def e4():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("function esc" in html or "const esc" in html, "缺少转义函数")
    # 画师名与文件名必须经转义/编码
    check('esc(a.name)' in html, "画师名未转义")
    check('encodeURIComponent(im.file)' in html, "文件路径未编码")


@case("E安全", "外链协议受限")
def e5():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    # note.url 直接进 href，应限制 http(s)
    check("safeUrl" in html or "startsWith('http')" in html
          or 'startsWith("http")' in html, "外链未做协议白名单")


# ============ F. 接口契约与健壮性 ============
@case("F接口", "状态与数据接口结构")
def f1():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.ENGINE = wb.Engine()
        port = 8813
        srv = start_server(wb, port)
        try:
            code, body = http_get(port, "/api/state")
            s = json.loads(body)
            for k in ["phase", "logged_in", "progress", "total", "logs",
                      "artist_count", "image_count", "notes_done"]:
                check(k in s, f"state 缺字段 {k}")
            code, body = http_get(port, "/api/data")
            check("artists" in json.loads(body), "data 缺 artists")
        finally:
            srv.shutdown()


@case("F接口", "非法请求体不崩溃")
def f2():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.ENGINE = wb.Engine()
        port = 8814
        srv = start_server(wb, port)
        try:
            for payload in [b"{bad json", b"", b"[]", b"null", b'{"limit":"abc"}']:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/collect", data=payload,
                    headers={"Content-Type": "application/json"})
                try:
                    r = urllib.request.urlopen(req, timeout=10)
                    json.loads(r.read())
                except urllib.error.HTTPError as e:
                    check(e.code < 500, f"非法请求导致服务端错误 {e.code}")
            code, _ = http_get(port, "/api/state")
            check(code == 200, "非法请求后服务不可用")
        finally:
            srv.shutdown()


@case("F接口", "未知路径404")
def f3():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.ENGINE = wb.Engine()
        port = 8815
        srv = start_server(wb, port)
        try:
            for p in ["/nope", "/api/nope", "/../app.py", "/%2e%2e/app.py",
                      "/..%2fapp.py", "/api/../../x", "/%2e%2e%2fapp.py"]:
                code, _ = http_get(port, p)
                check(code in (404, 400), f"{p} 应404，实得{code}")
        finally:
            srv.shutdown()


@case("F接口", "参数边界钳制")
def f4():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        eng = wb.Engine()
        captured = {}
        eng.start_collect = lambda k, l, h, auto_verify=True: (
            captured.update(k=k, l=l, h=h, av=auto_verify) or (True, ""))
        wb.ENGINE = eng
        port = 8816
        srv = start_server(wb, port)
        try:
            for raw, want in [(-5, 1), (0, 1), (99999, 200), ("abc", 20)]:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/collect",
                    data=json.dumps({"keyword": "x", "limit": raw}).encode(),
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
                check(captured.get("l") == want, f"limit {raw} 应钳为 {want}，实得 {captured.get('l')}")
        finally:
            srv.shutdown()


@case("F接口", "端口占用可降级")
def f5():
    src = (ROOT / "工作台.py").read_text(encoding="utf-8")
    check("for port in" in src or "OSError" in src or "port +" in src,
          "端口被占用时没有备用端口逻辑")


@case("F接口", "空关键词被拒")
def f6():
    with tempfile.TemporaryDirectory() as td:
        wb = make_wb(td)
        wb.ENGINE = wb.Engine()
        port = 8817
        srv = start_server(wb, port)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/collect",
                data=json.dumps({"keyword": "   "}).encode(),
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=10).read())
            check(r["ok"] is False, "空关键词应被拒绝")
        finally:
            srv.shutdown()


# ============ G. 前端静态检查 ============
@case("G前端", "无数据空态文案")
def g1():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("还没有采集到画师" in html, "缺少空态")
    # 筛选后无结果应有别于「从未采集」
    check("没有匹配" in html or "无匹配" in html or "换个筛选" in html,
          "筛选无结果与未采集共用同一文案，会误导")


@case("G前端", "服务断连有提示")
def g2():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("catch(e) {}" not in html.replace(" ", "").replace("catch(e){}", "catch(e) {}")
          or "连接" in html, "请求失败被静默吞掉，用户无感知")


@case("G前端", "灯箱可键盘关闭")
def g3():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("Escape" in html, "灯箱不支持Esc关闭")


@case("G前端", "图片加载失败兜底")
def g4():
    html = (ROOT / "工作台界面.html").read_text(encoding="utf-8")
    check("onerror" in html, "图片加载失败无兜底，会显示破图")


# ============ H. 真实数据完整性 ============
@case("H真实数据", "现有采集结果自洽")
def h1():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    missing, invalid, no_src = [], [], []
    for a in d.get("artists", []):
        for im in a.get("images", []):
            rel = im.get("file") or ""
            if not rel:
                # 在线模式不落盘，此时必须有可用的图床链接
                if not str(im.get("src", "")).startswith("https://"):
                    no_src.append(a["name"])
                continue
            f = ROOT / rel
            if not f.is_file():
                missing.append(rel)
                continue
            head = f.read_bytes()[:12]
            if not (head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n"
                    or head[:4] == b"RIFF"):
                invalid.append(rel)
    check(not missing, f"清单指向缺失文件 {len(missing)} 个")
    check(not invalid, f"非法图像 {len(invalid)} 个")
    check(not no_src, f"在线模式图片缺少可用链接 {len(no_src)} 个")


@case("H真实数据", "无重复图片记录")
def h2():
    df = ROOT / "采集结果" / "data.json"
    if not df.exists():
        return
    d = json.loads(df.read_text(encoding="utf-8"))
    srcs = [im.get("src", "").split("?")[0]
            for a in d["artists"] for im in a["images"] if im.get("src")]
    dup = len(srcs) - len(set(srcs))
    check(dup == 0, f"存在 {dup} 条重复图片记录")


def main():
    groups = {}
    for g, n, fn in CASES:
        try:
            fn()
            groups.setdefault(g, []).append((n, "PASS", ""))
        except AssertionError as e:
            groups.setdefault(g, []).append((n, "FAIL", str(e)))
        except Exception as e:
            groups.setdefault(g, []).append((n, "ERROR", f"{type(e).__name__}: {e}"))

    total = passed = 0
    lines = []
    for g, items in groups.items():
        lines.append(f"\n【{g}】")
        for n, st, msg in items:
            total += 1
            if st == "PASS":
                passed += 1
                lines.append(f"  ✓ {n}")
            else:
                lines.append(f"  ✗ {n}  [{st}] {msg}")
    lines.append(f"\n{'='*54}")
    lines.append(f"合计 {total} 项，通过 {passed}，失败 {total-passed}")
    report = "\n".join(lines)
    print(report)
    (ROOT / "测试报告.txt").write_text(report, encoding="utf-8")
    return total - passed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)