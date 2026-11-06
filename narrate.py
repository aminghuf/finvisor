#!/usr/bin/env python3
"""LLM narrative over data/stats.json via any OpenAI-compatible endpoint.

Env config (no key needed for a local Ollama):
  LLM_API_KEY   (required for cloud providers)
  LLM_BASE_URL  default https://api.deepseek.com/v1
  LLM_MODEL     default deepseek-chat

Examples:
  # cloud (DeepSeek / OpenAI / OpenRouter — set base_url + key)
  LLM_API_KEY=sk-... python3 narrate.py
  # local Ollama, nothing leaves the machine
  LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=llama3.1 python3 narrate.py
  # ask a specific question instead of the default summary
  python3 narrate.py --question "How much did I spend on food last quarter?"
"""
import argparse
import json
import os

import requests


def summarize(stats):
    t, c = stats["totals"], stats["counts"]
    cats = ", ".join(f"{k} €{v:,.0f}" for k, v in stats["by_category"].items())
    subs = "; ".join(f"{x['merchant']} ~€{x['avg_amount']}/mo"
                     for x in stats["subscriptions"][:12])
    inc = "; ".join(f"{k} €{v:,.0f}" for k, v in stats["income_sources"].items())
    return (f"Period {stats['period'][0]} to {stats['period'][1]}. "
            f"{c['spending']} card payments totaling €{t['spend']:,.2f} "
            f"(net of €{t['refund']:,.2f} refunds), €{t['income']:,.2f} money in, "
            f"€{t['fees']:,.2f} fees.\nCategories: {cats}.\n"
            f"Recurring: {subs}.\nIncome sources: {inc}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    stats = json.load(open(os.path.join(here, "data", "stats.json")))

    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    q = args.question or ("Give a concise financial analysis of this data: "
                          "key trends, where the money goes, subscriptions, and "
                          "2-3 actionable suggestions. Cite the numbers.")
    payload = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You are a personal finance analyst. Be specific, cite "
                        "the numbers, use short bullets."},
            {"role": "user", "content": f"{q}\n\nDATA:\n{summarize(stats)}"},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    r = requests.post(f"{base}/chat/completions", headers=headers,
                      json=payload, timeout=120)
    r.raise_for_status()
    print(r.json()["choices"][0]["message"]["content"])


if __name__ == "__main__":
    main()
