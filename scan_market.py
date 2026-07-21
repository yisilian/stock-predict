#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_market.py — 全市场尾盘扫描，只输出 buy 候选。

流程：
  1. Tushare stock_basic 拉全市场上市股票（SH+SZ）
  2. 腾讯轻量行情预筛：涨幅区间 + 流通市值区间（不消耗 Tushare 额度）
  3. 对预筛命中者跑完整 analyze_stock（含 Tushare 日K）
  4. 仅保留 signal=buy 且 final_score>=阈值的候选
  5. 写出 tail_pick_result.json（复用结构，notify_feishu.py 直接读）

环境变量：
  TUSHARE_TOKEN    必填（拉列表 + 日K）
  SCAN_CHG_MIN     预筛涨幅下限(%)，默认 2.5
  SCAN_CHG_MAX     预筛涨幅上限(%)，默认 6.0
  SCAN_MCAP_MIN    预筛流通市值下限(亿)，默认 40
  SCAN_MCAP_MAX    预筛流通市值上限(亿)，默认 250
  SCAN_MAX_ANALYZE 最多完整分析几只，默认 40
  SCAN_SCORE_MIN   buy 候选最低综合评分，默认 55
"""
import os
import sys
import time
import random
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from astock_data import get_quote_tencent, _tushare_api
from tail_pick import analyze_stock


def get_all_codes():
    pro = _tushare_api()
    if pro is None:
        raise SystemExit("缺少 TUSHARE_TOKEN，无法拉取全市场列表")
    codes = []
    for exchange in ("SH", "SZ"):
        try:
            df = pro.stock_basic(exchange=exchange, list_status="L",
                                 fields="ts_code,symbol,name")
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                codes.append(str(row["symbol"]))
        except Exception as e:
            print(f"[WARN] stock_basic {exchange} 失败: {e}")
    return codes


def prescreen(code, chg_min, chg_max, mcap_min, mcap_max):
    """腾讯轻量预筛：只判断涨幅与流通市值，避免消耗 Tushare 额度。"""
    try:
        q = get_quote_tencent(code)
    except Exception:
        return False
    if not q or q.get("price", 0) <= 0:
        return False
    chg = q.get("change_pct", 0)
    mcap = q.get("circ_mcap_yi", 0)
    if not (chg_min <= chg <= chg_max):
        return False
    if mcap > 0 and not (mcap_min <= mcap <= mcap_max):
        return False
    return True


def main():
    chg_min = float(os.getenv("SCAN_CHG_MIN", "2.5"))
    chg_max = float(os.getenv("SCAN_CHG_MAX", "6.0"))
    mcap_min = float(os.getenv("SCAN_MCAP_MIN", "40"))
    mcap_max = float(os.getenv("SCAN_MCAP_MAX", "250"))
    max_analyze = int(os.getenv("SCAN_MAX_ANALYZE", "40"))
    score_min = int(os.getenv("SCAN_SCORE_MIN", "55"))

    print("== 全市场尾盘扫描 ==")
    codes = get_all_codes()
    print(f"全市场共 {len(codes)} 只，开始腾讯行情预筛"
          f"（涨幅 {chg_min}~{chg_max}%，市值 {mcap_min}~{mcap_max}亿）...")

    hits = []
    for i, code in enumerate(codes):
        if prescreen(code, chg_min, chg_max, mcap_min, mcap_max):
            hits.append(code)
        time.sleep(0.12 + random.uniform(0, 0.08))
        if (i + 1) % 500 == 0:
            print(f"  预筛 {i + 1}/{len(codes)}，命中 {len(hits)}")

    print(f"预筛命中 {len(hits)} 只，开始完整分析（上限 {max_analyze}）...")

    results = []
    for code in hits[:max_analyze]:
        try:
            r = analyze_stock(code)
        except Exception as e:
            print(f"  [ERR] {code}: {e}")
            continue
        if r.get("error"):
            continue
        sig = (r.get("pattern") or {}).get("signal", "")
        score = (r.get("summary") or {}).get("final_score", 0)
        if sig == "buy" and score >= score_min:
            results.append(r)
            print(f"  ✅ {r.get('name')}({code}) 评分 {score} 入选")
        time.sleep(0.8 + random.uniform(0, 0.4))

    results.sort(key=lambda r: (r.get("summary") or {}).get("final_score", 0), reverse=True)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tail_pick_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n扫描完成：{len(codes)} 只中预筛命中 {len(hits)} 只，"
          f"最终 buy 候选 {len(results)} 只")
    print(f"结果已写入: {out}")


if __name__ == "__main__":
    main()
