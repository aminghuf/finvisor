#!/usr/bin/env python3
"""Deterministic financial analysis over Enable Banking / Revolut exports.

Reads data/transactions.csv (produced by connect.py) and computes:
  - flow classification (spending / income / fees / refunds / transfers)
  - merchant category breakdown (keyword rules)
  - monthly aggregates + trend
  - recurring-charge (subscription) detection
Writes data/report.md and data/stats.json, prints a summary.

The numbers are pure pandas math; an LLM only adds narrative on top.
"""
import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CSV = os.path.join(DATA, "transactions.csv")

# --- category rules live in categories.json (shared with the web UI, index.html)
_RULES = json.load(open(os.path.join(HERE, "categories.json"), encoding="utf-8"))
_LOCAL = os.path.join(HERE, "categories.local.json")  # personal keywords, gitignored
if os.path.exists(_LOCAL):
    _extra = json.load(open(_LOCAL, encoding="utf-8")).get("categories", [])
    _RULES["categories"] = _extra + _RULES["categories"]
CATEGORIES = [(c["name"], c["keywords"]) for c in _RULES["categories"]]
# money out of the account into own savings pocket / own accounts -> not spending
INTERNAL_PATTERNS = _RULES["internal_patterns"]


def norm(s):
    return (s or "").strip().lower()


def categorize(desc):
    d = norm(desc)
    for cat, kws in CATEGORIES:
        for kw in kws:
            if kw in d:
                return cat
    return "other"


def classify(row):
    code = (row["bank_code"] or "").split(":")[0]
    desc = norm(row["description"])
    if code == "CARD_PAYMENT":
        return "spending"
    if code in ("CARD_REFUND", "CARD_CREDIT", "CARD_CHARGEBACK"):
        return "refund"
    if code == "TOPUP":
        return "income"
    if code in ("CHARGE", "FEE"):
        return "fee"
    if code == "REWARD":
        return "income"
    if code == "EXCHANGE":
        return "internal"
    if code == "TRANSFER":
        if any(p in desc for p in INTERNAL_PATTERNS):
            return "internal"
        # "For X | To/From Person" and "To/From Person" -> P2P
        if " | " in desc or desc.startswith(("from ", "to ")):
            return "p2p"
        return "transfer"
    return "other"


def month_key(d):
    return d[:7]  # YYYY-MM


def main():
    rows = list(csv.DictReader(open(CSV)))
    for r in rows:
        r["signed_amount"] = float(r["signed_amount"]) if r["signed_amount"] else 0.0

    # classify
    for r in rows:
        r["flow"] = classify(r)
        r["cat"] = categorize(r["description"]) if r["flow"] == "spending" else None

    spending = [r for r in rows if r["flow"] == "spending"]
    income = [r for r in rows if r["flow"] == "income"]
    fees = [r for r in rows if r["flow"] == "fee"]
    refunds = [r for r in rows if r["flow"] == "refund"]
    p2p = [r for r in rows if r["flow"] == "p2p"]
    internal = [r for r in rows if r["flow"] == "internal"]

    total_spend = sum(-r["signed_amount"] for r in spending)
    total_refund = sum(r["signed_amount"] for r in refunds)
    total_income = sum(r["signed_amount"] for r in income)
    total_fees = sum(-r["signed_amount"] for r in fees)

    # monthly series (spending = card out)
    monthly = defaultdict(lambda: {"spend": 0.0, "income": 0.0, "fees": 0.0,
                                   "refund": 0.0, "n": 0})
    for r in spending:
        m = month_key(r["booking_date"])
        monthly[m]["spend"] += -r["signed_amount"]
        monthly[m]["n"] += 1
    for r in income:
        monthly[month_key(r["booking_date"])]["income"] += r["signed_amount"]
    for r in fees:
        monthly[month_key(r["booking_date"])]["fees"] += -r["signed_amount"]
    for r in refunds:
        monthly[month_key(r["booking_date"])]["refund"] += r["signed_amount"]

    # category breakdown of spending
    by_cat = defaultdict(float)
    for r in spending:
        by_cat[r["cat"]] += -r["signed_amount"]
    by_cat = dict(sorted(by_cat.items(), key=lambda x: -x[1]))

    # top merchants (spending only)
    merch = Counter()
    for r in spending:
        merch[norm(r["description"])] += -r["signed_amount"]
    top_merchants = merch.most_common(20)

    # income sources
    income_src = Counter()
    for r in income:
        income_src[norm(r["description"])] += r["signed_amount"]

    # subscription detection: recurring card charges
    by_merchant = defaultdict(list)
    for r in spending:
        by_merchant[norm(r["description"])].append(r)
    subs = []
    for m, txs in by_merchant.items():
        if len(txs) < 3:
            continue
        dates = sorted(tx["booking_date"] for tx in txs)
        gaps = []
        for a, b in zip(dates, dates[1:]):
            da, db = datetime.strptime(a, "%Y-%m-%d"), datetime.strptime(b, "%Y-%m-%d")
            gaps.append((db - da).days)
        if not gaps:
            continue
        median_gap = sorted(gaps)[len(gaps) // 2]
        avg_amt = sum(-tx["signed_amount"] for tx in txs) / len(txs)
        if 20 <= median_gap <= 40:
            subs.append({"merchant": m, "count": len(txs),
                         "median_gap_days": median_gap,
                         "avg_amount": round(avg_amt, 2),
                         "total": round(sum(-tx["signed_amount"] for tx in txs), 2),
                         "first": dates[0], "last": dates[-1]})
    subs.sort(key=lambda s: -s["total"])

    # ---- output ----
    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out("# Financevisor — Revolut analysis")
    out(f"\nPeriod: {monthly and min(monthly)} → {monthly and max(monthly)}")
    out(f"Transactions: {len(rows)} "
        f"(spending {len(spending)}, transfers {len(p2p)+len(internal)}, "
        f"income {len(income)}, fees {len(fees)}, refunds {len(refunds)})")
    out("\n## Headline (full period)")
    out(f"- Card spending: **€{total_spend:,.2f}** "
        f"(net of €{total_refund:,.2f} refunds)")
    out(f"- Money added (top-ups): **€{total_income:,.2f}**")
    out(f"- Plan fees: **€{total_fees:,.2f}**")

    out("\n## Spending by category")
    for cat, amt in by_cat.items():
        pct = 100 * amt / total_spend if total_spend else 0
        out(f"- {cat:<18} €{amt:>9,.2f}  ({pct:4.1f}%)")

    out("\n## Top merchants (card spending)")
    for m, amt in top_merchants:
        out(f"- {m:<35} €{amt:>9,.2f}")

    out("\n## Recurring charges (likely subscriptions)")
    if subs:
        for s in subs:
            out(f"- {s['merchant']:<30} x{s['count']} "
                f"~€{s['avg_amount']:,.2f}/mo (every ~{s['median_gap_days']}d) "
                f"= €{s['total']:,.2f} total")
    else:
        out("- none detected")

    out("\n## Income sources (top-ups)")
    for s, amt in income_src.most_common(12):
        out(f"- {s:<50} €{amt:>9,.2f}")

    out("\n## Monthly (card spending)")
    out("```")
    out("month      spend      income     fees")
    for m in sorted(monthly):
        d = monthly[m]
        out(f"{m}   €{d['spend']:>8,.2f}  €{d['income']:>8,.2f}  €{d['fees']:>6,.2f}")
    out("```")

    report = "\n".join(lines)
    with open(os.path.join(DATA, "report.md"), "w") as f:
        f.write(report + "\n")

    stats = {
        "period": [min(monthly), max(monthly)] if monthly else [],
        "counts": {"spending": len(spending), "income": len(income),
                   "fees": len(fees), "refunds": len(refunds),
                   "p2p": len(p2p), "internal": len(internal)},
        "totals": {"spend": total_spend, "refund": total_refund,
                   "income": total_income, "fees": total_fees},
        "by_category": by_cat,
        "top_merchants": [[m, round(a, 2)] for m, a in top_merchants],
        "subscriptions": subs,
        "income_sources": dict(income_src.most_common(20)),
        "monthly": {m: {k: round(v, 2) for k, v in d.items()}
                    for m, d in sorted(monthly.items())},
    }
    with open(os.path.join(DATA, "stats.json"), "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\nWrote {os.path.join(DATA, 'report.md')} and stats.json")


if __name__ == "__main__":
    main()
