#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 tail_pick.py / scan_market.py 生成的 tail_pick_result.json，
生成飞书交互卡片并推送到飞书群自定义机器人。

特性：
  - 交互卡片（interactive），比纯文本更好看
  - 红涨绿跌配色（中国习惯）
  - scan 模式输出仅含 buy 候选；watchlist 模式显示全部

用法：
    python notify_feishu.py                      # 读取默认 tail_pick_result.json
    python notify_feishu.py path/to/result.json  # 指定结果文件

环境变量：
    FEISHU_WEBHOOK   必填，飞书群自定义机器人 Webhook 地址
    FEISHU_SECRET     选填，机器人开启「签名校验」时提供
    NOTIFY_EMPTY      选填，默认 1；设为 0 时若任何结果都没有则不推送
"""
import os
import sys
import json
import time
import hmac
import base64
import hashlib
import urllib.request


def gen_sign(secret: str):
    """飞书自定义机器人签名校验：timestamp + "\n" + secret 做 HmacSHA256。"""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return timestamp, base64.b64encode(hmac_code).decode("utf-8")


def _chg_color(chg):
    """涨=红，跌=绿（中国习惯）。"""
    if isinstance(chg, (int, float)):
        if chg > 0:
            return "red"
        if chg < 0:
            return "green"
    return "grey"


def _verdict_color(verdict):
    v = verdict or ""
    if "强烈推荐" in v:
        return "green"
    if "可以考虑" in v or "形态偏多" in v:
        return "orange"
    if "回避" in v:
        return "red"
    return "blue"


def _score_color(score):
    if score >= 70:
        return "red"
    if score >= 55:
        return "orange"
    return "grey"


def build_card(results, max_cards=20):
    date = time.strftime("%Y-%m-%d %H:%M")
    ok = [r for r in results if not r.get("error")]
    err = [r for r in results if r.get("error")]
    ok.sort(key=lambda r: (r.get("summary") or {}).get("final_score", 0), reverse=True)

    has = len(ok) > 0
    template = "green" if has else "grey"
    title = f"📊 尾盘选股 · {len(ok)} 只买入候选" if has else "📊 尾盘选股 · 今日无候选"

    elements = []
    if not has:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "今日没有符合买入条件（signal=buy 且综合评分达标）的候选。\n"
                           "策略较严属正常，空仓也是交易的一部分。",
            },
        })
    else:
        for r in ok[:max_cards]:
            code = r.get("code", "")
            name = r.get("name", code)
            s = r.get("summary") or {}
            score = s.get("final_score", 0)
            p = r.get("pattern") or {}
            q = r.get("quote") or {}
            chg = q.get("change_pct")
            chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "-"
            pname = p.get("pattern_name", "-")
            verdict = r.get("verdict", "")
            rec = r.get("recommendation", "")
            cc = _chg_color(chg)
            sc = _score_color(score)
            vc = _verdict_color(verdict)
            content = (
                f"**{name} ({code})**　综合评分 "
                f"<font color=\"{sc}\">{score}</font>\n"
                f"涨幅 <font color=\"{cc}\">{chg_str}</font>　形态：{pname}\n"
                f"<font color=\"{vc}\">{verdict}</font>\n"
                f"{rec}"
            )
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
            elements.append({"tag": "hr"})
        if elements and elements[-1].get("tag") == "hr":
            elements.pop()
        if len(ok) > max_cards:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"_还有 {len(ok) - max_cards} 只未显示_"},
            })

    if err:
        err_lines = "\n".join(f"{r.get('code', '')}：{r.get('error')}" for r in err[:5])
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"⚠️ 获取失败（{len(err)} 只）：\n{err_lines}"},
        })

    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "规则化分析，仅供参考，不构成投资建议。"}],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        },
    }


def send(webhook, payload, secret=None):
    if secret:
        ts, sign = gen_sign(secret)
        payload["timestamp"] = ts
        payload["sign"] = sign
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    print("飞书响应:", body)
    result = json.loads(body)
    # 飞书成功返回 {"StatusCode":0,...} 或 {"code":0,...}
    if result.get("StatusCode") not in (0, None) or result.get("code") not in (0, None):
        raise SystemExit(f"飞书推送失败: {body}")


def main():
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        raise SystemExit("未设置 FEISHU_WEBHOOK 环境变量")
    secret = os.environ.get("FEISHU_SECRET", "").strip() or None
    notify_empty = os.environ.get("NOTIFY_EMPTY", "1").strip() not in ("0", "false", "False")

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tail_pick_result.json"
    )
    if not os.path.exists(path):
        raise SystemExit(f"结果文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    if not results and not notify_empty:
        print("无结果且 NOTIFY_EMPTY=0，跳过推送。")
        return

    payload = build_card(results)
    print("即将推送飞书卡片...")
    send(webhook, payload, secret)


if __name__ == "__main__":
    main()
