#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 tail_pick.py 生成的 tail_pick_result.json，格式化后推送到飞书群自定义机器人。

用法：
    python notify_feishu.py                       # 读取默认 tail_pick_result.json
    python notify_feishu.py path/to/result.json   # 指定结果文件

环境变量：
    FEISHU_WEBHOOK  必填，飞书群自定义机器人的 Webhook 地址
    FEISHU_SECRET   选填，若机器人开启了「签名校验」则需要提供
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
    """飞书自定义机器人签名校验：timestamp + "\n" + secret 作为 key，做 HmacSHA256。"""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign


SIGNAL_EMOJI = {"buy": "🟢", "neutral": "🟡", "avoid": "🔴"}


def build_text(results):
    """把结果列表拼成飞书文本消息。"""
    date = time.strftime("%Y-%m-%d %H:%M")
    ok = [r for r in results if not r.get("error")]
    err = [r for r in results if r.get("error")]

    # 按综合评分降序
    ok.sort(key=lambda r: (r.get("summary") or {}).get("final_score", 0), reverse=True)

    lines = [f"📊 尾盘选股分析 · {date}", ""]

    if not ok and not err:
        lines.append("（无结果）")
        return "\n".join(lines)

    for r in ok:
        code = r.get("code", "")
        name = r.get("name", code)
        summary = r.get("summary") or {}
        pattern = r.get("pattern") or {}
        quote = r.get("quote") or {}
        score = summary.get("final_score", 0)
        signal = pattern.get("signal", "neutral")
        emoji = SIGNAL_EMOJI.get(signal, "⚪")
        pname = pattern.get("pattern_name", "-")
        chg = quote.get("change_pct")
        chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "-"
        verdict = r.get("verdict", "")
        rec = r.get("recommendation", "")

        lines.append(f"{emoji} {name}({code})  评分 {score}  涨幅 {chg_str}")
        lines.append(f"   形态：{pname}")
        if verdict:
            lines.append(f"   结论：{verdict}")
        if rec:
            lines.append(f"   建议：{rec}")
        lines.append("")

    if err:
        lines.append("⚠️ 获取失败：")
        for r in err:
            lines.append(f"   {r.get('code', '')}：{r.get('error')}")
        lines.append("")

    lines.append("规则化分析，仅供参考，不构成投资建议。")
    return "\n".join(lines).rstrip()


def send(webhook, text, secret=None):
    payload = {"msg_type": "text", "content": {"text": text}}
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

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tail_pick_result.json"
    )
    if not os.path.exists(path):
        raise SystemExit(f"结果文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    text = build_text(results)
    print("即将推送:\n" + text)
    send(webhook, text, secret)


if __name__ == "__main__":
    main()
