#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discuz! 论坛每日签到自动化脚本
================================
适用：Discuz! X 系列（含 X5.0）。

签到入口自动检测，按优先级尝试：
  1) JSON API 模式（推荐，适配 kxdao 这类自定义签到插件）
     脚本从签到页（首页或 DZ_SIGN_URL 指定的页面）的 <script> 中提取
     页面定义的 `_api` 与 `_fh`，复刻浏览器 silentCheckin 行为：
        POST  {_api}&action=checkin
        body: formhash={_fh}&source=checkin_page
        => JSON: {code:0, data:{streak,credits_got,today_rank,milestone}}
     判定：code==0 视为成功；否则按 error 文案判断是否已签到。
  2) 表单/插件模式兜底：首页寻找 plugin.php?id=xxx 签到入口，尝试
     - dsu_paulsign:sign   （DSU 每日签到）
     - k_misign:sign       （K_misign 每日签到）
     - 通用 operation=qiandao / operation=sign
  可通过 DZ_SIGN_URL 强制指定「含签到按钮/脚本的签到页」地址。

配置（全部通过环境变量，方便在 GitHub Actions Secrets 中配置）：
  FORUM_URL       论坛根地址，如 https://bbs.example.com        （必填）
  DZ_USERNAME     登录用户名                                     （必填）
  DZ_PASSWORD     登录密码                                       （必填）
  DZ_QUESTION_ID  安全提问 id，无提问填 0                        （可选，默认 0）
  DZ_ANSWER       安全提问答案                                   （可选）
  DZ_SIGN_URL     含签到按钮/脚本的签到页地址；留空则自动检测         （可选）
                  （JSON API 模式下指向定义 _api/_fh 的那个页面）
  DZ_MOOD         签到心情，如 kua / nu / lei ...                （可选，默认 kua）
  DZ_TODAYSAY     签到留言                                       （可选）
  DZ_MIN_DELAY    随机延迟下限（秒）                             （可选，默认 0）
  DZ_MAX_DELAY    随机延迟上限（秒）                             （可选，默认 0）
  DZ_DEBUG        设为 1 输出详细调试信息                         （可选）
  TG_BOT_TOKEN / TG_CHAT_ID   Telegram 通知（可选）
  SCKEY                     Server 酱通知（可选）

退出码：0 成功 / 已签到，非 0 失败（便于 Actions 标记红色）。
"""

import os
import re
import sys
import time
import random
import argparse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEBUG = os.environ.get("DZ_DEBUG", "") == "1"

# 首页未检测到签到链接时，依次兜底尝试的常见签到插件
DEFAULT_SIGN_IDS = ["dsu_paulsign:sign", "k_misign:sign"]

ALREADY_KW = [
    "已签到", "已经签到", "今日已签", "今天已签",
    "您今天已经签到", "重复签到", "已连续签到",
]
OK_KW = ["签到成功", "成功签到", "恭喜", "签到完成", "success"]
FAIL_KW = ["失败", "错误", "未登录", "请先登录", "非法", "参数"]


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def dbg(msg):
    if DEBUG:
        log(f"🔍 {msg}")


def die(msg, code=1):
    log(f"❌ {msg}")
    sys.exit(code)


def mask(s, keep=3):
    if not s or len(s) <= keep:
        return "*" * len(s or "")
    return s[:keep] + "*" * (len(s) - keep)


def debug_dump(name, html):
    """保存页面快照，供 Actions Artifact / 本地排查。"""
    try:
        with open(name, "w", encoding="utf-8") as f:
            f.write(html)
        dbg(f"已保存页面快照：{name}")
    except OSError as e:
        log(f"保存快照失败：{e}")


def page_brief(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "(无标题)"
    return f"标题「{title}」长度{len(html)}"


# ---------- 表单解析 ----------
def parse_form(html, prefer_name=None):
    """返回 (action_url, {field: value})，优先匹配指定 name/id 的表单。"""
    soup = BeautifulSoup(html, "html.parser")
    form = None
    if prefer_name:
        form = soup.find("form", id=prefer_name) or soup.find(
            "form", attrs={"name": prefer_name}
        )
    if form is None:
        # 优先选包含密码框的表单（登录页）
        for f in soup.find_all("form"):
            if f.find("input", attrs={"type": "password"}):
                form = f
                break
        if form is None:
            forms = soup.find_all("form")
            if forms:
                form = forms[0]
    if form is None:
        return None, {}
    action = form.get("action") or ""
    fields = {}
    for tag in form.find_all(["input", "select", "textarea"]):
        name = tag.get("name")
        if not name:
            continue
        t = (tag.get("type") or "text").lower()
        if t in ("submit", "button", "image", "reset"):
            continue
        fields[name] = tag.get("value", "") or ""
    return action, fields


def get_formhash(html):
    m = re.search(r'name=["\']formhash["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not m:
        m = re.search(r"formhash\s*=\s*['\"]([^'\"]+)['\"]", html)
    if not m:
        m = re.search(r'id=["\']formhash["\'][^>]*value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def fetch(session, url, **kw):
    kw.setdefault("headers", {})
    kw["headers"].setdefault("User-Agent", DEFAULT_UA)
    kw.setdefault("timeout", 30)
    return session.get(url, **kw)


def post(session, url, data, **kw):
    kw.setdefault("headers", {})
    kw["headers"].setdefault("User-Agent", DEFAULT_UA)
    kw.setdefault("timeout", 30)
    return session.post(url, data=data, **kw)


# ---------- 登录 ----------
def login(session, forum_url, username, password, question_id="0", answer=""):
    log(f"正在登录：{forum_url} 用户：{mask(username)}")
    login_page = urljoin(forum_url + "/", "member.php?mod=logging&action=login")
    r = fetch(session, login_page)
    dbg(f"登录页 HTTP {r.status_code}，{page_brief(r.text)}")
    if r.status_code != 200:
        die(f"无法访问登录页，HTTP {r.status_code}")

    action, fields = parse_form(r.text)
    post_url = urljoin(login_page, action) if action else login_page
    dbg(f"登录提交地址：{post_url}")
    fields["username"] = username
    fields["password"] = password
    fields["questionid"] = question_id
    fields["answer"] = answer
    fields["cookietime"] = fields.get("cookietime", "2592000")

    r2 = post(session, post_url, data=fields, allow_redirects=True)

    # 二次确认：访问首页看是否出现登出链接或用户名
    home = fetch(session, forum_url + "/")
    html = home.text
    if (
        "member.php?mod=logging&action=logout" in html
        or username in html
        or "退出" in html
    ):
        fh = get_formhash(html)
        log("✅ 登录成功")
        return fh

    err = extract_error(r2.text) or extract_error(html)
    die(
        f"登录失败{('：' + err) if err else '，请检查账号密码 / 安全提问 / 是否需要验证码'}"
    )


def extract_error(html):
    soup = BeautifulSoup(html, "html.parser")
    for sel in [".error", ".alert_error", "#messagetext", "p", "div"]:
        for n in soup.select(sel):
            txt = n.get_text(strip=True)
            if any(
                k in txt
                for k in ["失败", "错误", "不正确", "验证码", "不存在", "锁定", "禁止"]
            ):
                return txt[:120]
    return None


# ---------- 签到 ----------
def detect_sign_ids(html):
    """从首页 HTML 中检测签到插件入口，返回插件 id 列表。"""
    ids = []
    for m in re.finditer(r'plugin\.php\?id=([A-Za-z0-9_:]+)', html):
        pid = m.group(1)
        low = pid.lower()
        if any(k in low for k in ("sign", "qiandao", "checkin")) and pid not in ids:
            ids.append(pid)
    dbg(f"首页检测到签到相关插件：{ids or '无，将使用默认列表兜底'}")
    return ids


def submit_and_check(session, submit_desc, submit_fn, page_url):
    """执行一次提交并检查响应；返回 'success' / 'already' / None。"""
    try:
        rp = submit_fn()
    except requests.RequestException as e:
        log(f"⚠️ 提交 {submit_desc} 网络异常：{e}")
        return None
    dbg(f"提交 {submit_desc} → HTTP {rp.status_code}，响应前200字：{rp.text[:200]!r}")
    text = rp.text
    if any(k in text for k in ALREADY_KW):
        return "already"
    if any(k in text for k in OK_KW) and not any(k in text for k in FAIL_KW):
        return "success"
    # Discuz 的 ajax 返回可能是 XML/空内容，重新核验页面状态
    try:
        recheck = fetch(session, page_url).text
    except requests.RequestException:
        return None
    if any(k in recheck for k in ALREADY_KW):
        return "already"
    return None


def attempt_sign(session, forum_url, formhash, target, mood, todaysay):
    """尝试一个签到入口。target 是插件 id 或完整 URL。返回 'success'/'already'/None。"""
    if re.match(r"^https?://", target):
        page_url = target
        pid = ""
    else:
        page_url = urljoin(forum_url + "/", f"plugin.php?id={target}")
        pid = target
    log(f"尝试签到入口：{page_url}")

    r = fetch(session, page_url)
    dbg(f"签到页 HTTP {r.status_code}，{page_brief(r.text)}")
    if r.status_code != 200:
        log(f"⚠️ 签到页 HTTP {r.status_code}，跳过该入口")
        return None
    html = r.text
    if any(k in html for k in ALREADY_KW):
        return "already"

    fh = get_formhash(html) or formhash
    if not fh:
        log(f"⚠️ 该页面未找到 formhash（可能插件不存在），跳过")
        debug_dump(f"debug_sign_{re.sub(r'[^A-Za-z0-9]', '_', target or 'url')}.html", html)
        return None
    dbg(f"formhash = {fh}")

    results = []

    # 1) 页面自带表单：直接按表单 action 提交（适配大多数插件）
    action, fields = parse_form(html)
    if action and any(k in action.lower() for k in ("sign", "qiandao", "checkin")):
        submit_url = urljoin(page_url, action)
        fields.update(
            {"formhash": fh, "qdxq": mood, "todaysay": todaysay, "fastreply": "1"}
        )
        dbg(f"提交页面表单：{submit_url}")
        results.append(
            submit_and_check(
                session, "页面表单",
                lambda: post(session, submit_url, data=fields),
                page_url,
            )
        )

    # 2) 插件专属提交端点
    base = urljoin(forum_url + "/", f"plugin.php?id={pid}") if pid else page_url
    if pid == "dsu_paulsign:sign":
        data = {
            "formhash": fh, "qdxq": mood, "qdmode": "1",
            "todaysay": todaysay, "fastreply": "1",
        }
        url = base + "&operation=qiandao&infloat=yes&inajax=1"
        dbg(f"提交 DSU 端点：{url}")
        results.append(
            submit_and_check(
                session, "DSU 端点",
                lambda: post(session, url, data=data),
                page_url,
            )
        )
    elif pid.startswith("k_misign"):
        url = f"{base}&operation=qiandao&formhash={fh}&format=empty"
        dbg(f"提交 K_misign 端点：{url}")
        results.append(
            submit_and_check(
                session, "K_misign 端点",
                lambda: fetch(session, url),
                page_url,
            )
        )

    # 3) 通用兜底：operation=qiandao / operation=sign
    if pid:
        for op in ("qiandao", "sign"):
            url = f"{base}&operation={op}&formhash={fh}"
            results.append(
                submit_and_check(
                    session, f"通用端点 {op}",
                    lambda u=url: post(session, u, data={"formhash": fh}),
                    page_url,
                )
            )

    for res in results:
        if res in ("success", "already"):
            return res
    return None


def try_json_api(session, forum_url, page_url, formhash):
    """JSON API 模式：复刻浏览器 silentCheckin。

    从签到页（含 _api / _fh 定义）提取接口并 POST，返回
    'success' / 'already' / None。若页面不含 _api 标记返回 None（交由其他模式）。
    """
    try:
        r = fetch(session, page_url)
    except requests.RequestException as e:
        dbg(f"JSON API 模式获取 {page_url} 失败：{e}")
        return None
    html = r.text
    if r.status_code != 200:
        dbg(f"JSON API 页面 HTTP {r.status_code}，跳过")
        return None
    if not re.search(r"\b_api\s*=", html):
        # 该页面没有 _api 定义，明显不是自定义 JSON 签到页
        return None

    api_m = re.search(r"_api\s*=\s*[\"']([^\"']+)[\"']", html)
    if not api_m:
        dbg("页面含 _api 但无法提取字符串，跳过")
        return None
    _api = api_m.group(1).strip()
    dbg(f"发现 _api = {_api}")

    fh_m = re.search(r"_fh\s*=\s*[\"']([^\"']+)[\"']", html)
    fh = fh_m.group(1).strip() if fh_m else None
    if not fh:
        # 兼容 _fh = formhash 的写法：取页面全局 formhash
        fh = get_formhash(html) or formhash
    if not fh:
        log("⚠️ 未找到 formhash，JSON API 模式跳过")
        return None
    dbg(f"_fh / formhash = {fh}")

    url = urljoin(forum_url + "/", _api) + "&action=checkin"
    dbg(f"提交签到 API：{url}")

    try:
        rp = post(
            session, url,
            data={"formhash": fh, "source": "checkin_page"},
        )
    except requests.RequestException as e:
        log(f"⚠️ 签到 API 网络异常：{e}")
        return None

    text = rp.text.strip()
    dbg(f"API 响应(前300字)：{text[:300]!r}")

    # 优先解析 JSON
    try:
        d = rp.json()
    except ValueError:
        # 非 JSON：退化为关键词判断
        if any(k in text for k in ALREADY_KW):
            return "already"
        if any(k in text for k in OK_KW) and not any(k in text for k in FAIL_KW):
            return "success"
        debug_dump("debug_sign_api_response.html", text)
        log("⚠️ 签到 API 返回非 JSON，无法判定结果")
        return None

    code = d.get("code")
    if code == 0:
        data = d.get("data", {}) or {}
        msg = (
            f"✅ 签到成功！连续 {data.get('streak', '?')} 天，"
            f"+{data.get('credits_got', '?')} 积分，"
            f"今日第 {data.get('today_rank', '?')} 位"
        )
        if data.get("milestone"):
            msg += f"，{data['milestone']}"
        log(msg)
        return "success"

    err = d.get("error") or "未知错误"
    if any(k in err for k in ALREADY_KW):
        log("ℹ️ 今日已签到，无需重复操作")
        return "already"
    log(f"⚠️ 签到 API 返回失败：{err}")
    return None


def discover_checkin_pages(forum_url, html):
    """从首页 HTML 中找可能的签到页链接（含 checkin/qiandao/sign 的 plugin 链接
    或锚文本含「签到/checkin」的链接），返回绝对 URL 列表。"""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if re.search(r"plugin\.php\?id=[A-Za-z0-9_:]+", href):
            pid = re.search(r"id=([A-Za-z0-9_:]+)", href).group(1).lower()
            if any(k in pid for k in ("sign", "qiandao", "checkin")):
                found.append(urljoin(forum_url + "/", href))
        elif any(k in txt.lower() for k in ("签到", "checkin", "qiandao")):
            found.append(urljoin(forum_url + "/", href))
    dbg(f"首页发现候选签到页：{found or '无'}")
    return found


def checkin(session, forum_url, formhash, sign_url="", mood="kua", todaysay=""):
    log("开始每日签到...")

    # ---- 1) JSON API 模式（优先）----
    api_pages = []
    if sign_url:
        api_pages.append(sign_url)
    api_pages.append(forum_url + "/")  # 多数插件的静默签到按钮挂在首页头部

    for page_url in api_pages:
        res = try_json_api(session, forum_url, page_url, formhash)
        if res == "success":
            return True
        if res == "already":
            return True

    # 若首页未命中，尝试自动发现并扫描候选签到页
    try:
        home_html = fetch(session, forum_url + "/").text
    except requests.RequestException:
        home_html = ""
    for page_url in discover_checkin_pages(forum_url, home_html):
        res = try_json_api(session, forum_url, page_url, formhash)
        if res in ("success", "already"):
            return True

    # ---- 2) 旧插件/表单模式兜底 ----
    log("未检测到 JSON API 签到，回退到插件/表单模式...")
    candidates = []
    if sign_url:
        candidates.append(sign_url)
    else:
        debug_dump("debug_home.html", home_html)
        ids = detect_sign_ids(home_html)
        candidates.extend(ids)
        for pid in DEFAULT_SIGN_IDS:
            if pid not in candidates:
                candidates.append(pid)

    if not candidates:
        die("未找到任何签到入口，请用 DZ_SIGN_URL 指定签到页地址")

    for target in candidates:
        try:
            res = attempt_sign(session, forum_url, formhash, target, mood, todaysay)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            log(f"⚠️ 入口 {target} 异常：{e}")
            continue
        if res == "success":
            log("✅ 签到成功")
            return True
        if res == "already":
            log("ℹ️ 今日已签到，无需重复操作")
            return True

    debug_dump("debug_final_home.html", fetch(session, forum_url + "/").text)
    die(
        "所有签到入口均未能完成签到。请下载 Actions 中的 debug-snapshots 工件，"
        "确认论坛实际的签到插件后，将其页面地址填入 DZ_SIGN_URL。"
    )


# ---------- 通知 ----------
def notify(title, text):
    token = os.environ.get("TG_BOT_TOKEN")
    chat = os.environ.get("TG_CHAT_ID")
    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat, "text": f"{title}\n{text}"},
                timeout=15,
            )
        except Exception as e:  # noqa: BLE001
            log(f"Telegram 通知失败：{e}")

    sckey = os.environ.get("SCKEY")
    if sckey:
        try:
            requests.post(
                f"https://sctapi.ftqq.com/{sckey}.send",
                data={"title": title, "desp": text},
                timeout=15,
            )
        except Exception as e:  # noqa: BLE001
            log(f"Server 酱通知失败：{e}")


def main():
    p = argparse.ArgumentParser(description="Discuz 每日签到")
    p.add_argument("--forum", default=os.environ.get("FORUM_URL", ""))
    p.add_argument("--user", default=os.environ.get("DZ_USERNAME", ""))
    p.add_argument("--pass", dest="pwd", default=os.environ.get("DZ_PASSWORD", ""))
    p.add_argument("--qid", default=os.environ.get("DZ_QUESTION_ID", "0"))
    p.add_argument("--answer", default=os.environ.get("DZ_ANSWER", ""))
    p.add_argument("--sign-url", default=os.environ.get("DZ_SIGN_URL", ""))
    p.add_argument("--mood", default=os.environ.get("DZ_MOOD", "kua"))
    p.add_argument("--say", default=os.environ.get("DZ_TODAYSAY", ""))
    args = p.parse_args()

    if not args.forum or not args.user or not args.pwd:
        die("缺少必填参数：FORUM_URL / DZ_USERNAME / DZ_PASSWORD")

    forum_url = args.forum.rstrip("/")

    # 随机延迟，避免所有用户同一秒请求
    try:
        lo = int(os.environ.get("DZ_MIN_DELAY", "0"))
        hi = int(os.environ.get("DZ_MAX_DELAY", "0"))
        if hi > lo:
            d = random.randint(lo, hi)
            log(f"随机延迟 {d}s 后执行")
            time.sleep(d)
    except ValueError:
        pass

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_UA})

    try:
        fh = login(session, forum_url, args.user, args.pwd, args.qid, args.answer)
        ok = checkin(session, forum_url, fh, args.sign_url, args.mood, args.say)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"❌ 发生异常：{e}")
        notify("Discuz 签到失败", str(e))
        sys.exit(1)

    if ok:
        notify("Discuz 签到成功", f"{args.user} 已在 {forum_url} 完成签到")
        sys.exit(0)


if __name__ == "__main__":
    main()
