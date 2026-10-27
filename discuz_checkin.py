#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discuz! 论坛每日签到自动化脚本
================================
适用：Discuz! X 系列（含 X5.0），默认适配常见的「DSU 每日签到」插件，
      也可通过环境变量适配其它签到插件。

运行环境：Python 3.8+，支持 GitHub Actions / 本地 / 服务器定时任务。

配置（全部通过环境变量，方便在 GitHub Actions Secrets 中配置）：
  FORUM_URL       论坛根地址，如 https://bbs.example.com        （必填）
  DZ_USERNAME     登录用户名                                     （必填）
  DZ_PASSWORD     登录密码                                       （必填）
  DZ_QUESTION_ID  安全提问 id，无提问填 0                        （可选，默认 0）
  DZ_ANSWER       安全提问答案                                   （可选）
  DZ_SIGN_URL     自定义签到页面地址；留空使用默认 DSU 插件        （可选）
  DZ_MOOD         签到心情，如 kua / nu / lei ...                （可选，默认 kua）
  DZ_TODAYSAY     签到留言                                       （可选）
  DZ_MIN_DELAY    随机延迟下限（秒）                             （可选，默认 0）
  DZ_MAX_DELAY    随机延迟上限（秒）                             （可选，默认 0）
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


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def die(msg, code=1):
    log(f"❌ {msg}")
    sys.exit(code)


def mask(s, keep=3):
    if not s or len(s) <= keep:
        return "*" * len(s or "")
    return s[:keep] + "*" * (len(s) - keep)


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
    if r.status_code != 200:
        die(f"无法访问登录页，HTTP {r.status_code}")

    action, fields = parse_form(r.text)
    post_url = urljoin(login_page, action) if action else login_page
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
def checkin(session, forum_url, formhash, sign_url="", mood="kua", todaysay=""):
    if sign_url:
        page_url = sign_url
    else:
        page_url = urljoin(forum_url + "/", "plugin.php?id=dsu_paulsign:sign")

    log(f"访问签到页：{page_url}")
    r = fetch(session, page_url)
    html = r.text

    already_kw = [
        "已签到",
        "已经签到",
        "今日已签",
        "今天已签",
        "您今天已经签到",
        "重复签到",
    ]
    if any(k in html for k in already_kw):
        log("ℹ️ 今日已签到，无需重复操作")
        return True

    fh = get_formhash(html) or formhash
    if not fh:
        die("无法获取签到 formhash，请确认签到页面地址是否正确")

    # 默认 DSU 签到提交地址
    submit_url = urljoin(
        forum_url + "/",
        "plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=yes&inajax=1",
    )
    data = {
        "formhash": fh,
        "qdxq": mood,
        "qdmode": "1",
        "todaysay": todaysay,
        "fastreply": "1",
    }

    # 若签到页本身是一个表单，则按表单字段提交（更通用，适配其它插件）
    action, fields = parse_form(html)
    if action and any(k in action for k in ("sign", "qiandao", "checkin")):
        submit_url = urljoin(page_url, action)
        fields.update(data)
        data = fields

    log(f"提交签到：{submit_url}")
    rp = post(session, submit_url, data=data)
    result = rp.text

    ok_kw = ["签到成功", "成功签到", "恭喜", "签到完成", "已签到", "success"]
    fail_kw = ["失败", "错误", "未登录", "请先登录", "非法", "重复"]
    if any(k in result for k in ok_kw) and not any(k in result for k in fail_kw):
        log("✅ 签到成功")
        return True
    if any(k in result for k in already_kw):
        log("ℹ️ 今日已签到")
        return True

    # Discuz 的 ajax 返回可能是 XML，再核验一次页面状态
    log("⚠️ 签到返回内容不明确，尝试再次核验...")
    recheck = fetch(session, page_url).text
    if any(k in recheck for k in already_kw):
        log("✅ 经核验，今日已签到")
        return True
    die(f"签到结果不明确：{result[:200]}")


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
