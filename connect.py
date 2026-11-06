#!/usr/bin/env python3
"""Connect Revolut via Enable Banking and dump transactions + balances.

Consent flow (manual):
  python3 connect.py --redirect-url "https://.../"
  -> prints an authorization URL; open it, authorize in Revolut,
     copy the ?code=... value, paste it back -> data pulled to ./data/

Two-step flow (for scripting / the agent to drive):
  python3 connect.py --redirect-url "https://.../" --auth-only   # prints URL
  python3 connect.py --redirect-url "https://.../" --code CODE   # pulls data

Options:
  --pem PATH        app private key (default: auto-find *.pem in ~/Downloads, ~, cwd)
  --app-id ID       default: inferred from the .pem filename
  --country IT      first country to search for the bank (auto-falls back)
  --bank Revolut    substring matched against ASPSP name
  --days 180        consent validity in days
  --strategy longest|default   "longest" pulls max history (extra ASPSP calls)
  --open            auto-open the authorization URL in the browser
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import requests

BASE = "https://api.enablebanking.com"


def find_pem():
    cands = []
    for pat in ["~/Downloads/*.pem", "~/*.pem", "./*.pem"]:
        cands += glob.glob(os.path.expanduser(pat))
    seen, uniq = set(), []
    for c in cands:
        rp = os.path.realpath(c)
        if rp not in seen:
            seen.add(rp)
            uniq.append(c)
    return uniq


def build_jwt(key_pem: bytes, app_id: str) -> str:
    iat = int(time.time())
    body = {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
            "iat": iat, "exp": iat + 3600}
    return pyjwt.encode(body, key_pem, algorithm="RS256",
                        headers={"kid": app_id})


def find_aspsp(headers, bank_substr, country):
    """Search for the bank; try the given country, then common Revolut homes."""
    tried = [country.upper()] if country else []
    tried += ["GB", "LT", "DE", "PL", "IE", "FR", "ES", "NL", "PT", ""]
    seen = set()
    for c in tried:
        if c in seen:
            continue
        seen.add(c)
        q = f"?country={c}" if c else ""
        try:
            data = requests.get(f"{BASE}/aspsps{q}", headers=headers,
                                timeout=30).json()
        except Exception as e:
            print(f"  [warn] aspsps?country={c or '(all)'}: {e}", file=sys.stderr)
            continue
        matches = [a for a in data.get("aspsps", [])
                   if bank_substr.lower() in (a.get("name") or "").lower()]
        if matches:
            return matches
    return []


def get_transactions(headers, uid, strategy, date_from):
    all_tx, key = [], None
    while True:
        params = {"strategy": strategy, "continuation_key": key}
        if date_from and strategy != "longest":
            params["date_from"] = date_from
        r = requests.get(f"{BASE}/accounts/{uid}/transactions",
                         headers=headers, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        all_tx.extend(data.get("transactions", []))
        key = data.get("continuation_key")
        if not key:
            break
    return all_tx


def tx_amount(tx):
    amt = (tx.get("transaction_amount") or {}).get("amount")
    cur = (tx.get("transaction_amount") or {}).get("currency")
    return amt, cur


def describe(tx):
    rem = tx.get("remittance_information") or []
    if rem:
        return " | ".join(x for x in rem if x)
    ref = tx.get("reference_number")
    if ref:
        return ref
    for k in ("creditor_name", "debtor_name"):
        if tx.get(k):
            return tx[k]
    return ""


def flatten(tx, uid):
    amt, cur = tx_amount(tx)
    sign = -1 if tx.get("credit_debit_indicator") == "DBIT" else 1
    code = tx.get("bank_transaction_code") or {}
    return {
        "account_uid": uid,
        "transaction_id": tx.get("transaction_id") or "",
        "entry_reference": tx.get("entry_reference") or "",
        "booking_date": tx.get("booking_date") or "",
        "value_date": tx.get("value_date") or "",
        "credit_debit": tx.get("credit_debit_indicator") or "",
        "amount": amt or "",
        "currency": cur or "",
        "signed_amount": (float(amt) * sign) if amt else "",
        "description": describe(tx),
        "counterparty": tx.get("creditor_name") or tx.get("debtor_name") or "",
        "bank_code": f"{code.get('code','')}:{code.get('sub_code','')}".strip(":"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pem", default=None)
    ap.add_argument("--app-id", default=None)
    ap.add_argument("--redirect-url", default=None)
    ap.add_argument("--country", default="IT")
    ap.add_argument("--bank", default="Revolut")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--strategy", default="longest",
                    choices=["longest", "default"])
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--code", default=None,
                    help="skip auth; exchange this authorization code")
    ap.add_argument("--auth-only", action="store_true",
                    help="just print the authorization URL and exit")
    args = ap.parse_args()

    # locate key
    pem_path = args.pem
    if not pem_path:
        pems = find_pem()
        if not pems:
            sys.exit("No .pem found. Pass --pem /path/to/your-app.pem")
        pem_path = pems[0]
    pem_path = os.path.abspath(os.path.expanduser(pem_path))
    app_id = args.app_id or os.path.splitext(os.path.basename(pem_path))[0]
    key_pem = open(pem_path, "rb").read()

    redirect_url = args.redirect_url
    if not redirect_url:
        redirect_url = input("Redirect URL (exact value you registered): ").strip()

    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(outdir, exist_ok=True)

    headers = {"Authorization": f"Bearer {build_jwt(key_pem, app_id)}"}
    print(f"app_id  : {app_id}")
    print(f"key     : {pem_path}")

    # 1. find Revolut ASPSP
    print(f"searching ASPSPs for '{args.bank}'...")
    matches = find_aspsp(headers, args.bank, args.country)
    if not matches:
        sys.exit("Could not find the ASPSP. Check --bank/--country.")
    m = matches[0]
    aspsp = {"name": m["name"], "country": m["country"]}
    print(f"using   : {m['name']} (country={m['country']}, bic={m.get('bic')})")

    # 2. start authorization (unless a code was already provided)
    code = args.code
    if not code:
        valid_until = (datetime.now(timezone.utc)
                       + timedelta(days=args.days)).isoformat()
        body = {
            "access": {"valid_until": valid_until},
            "aspsp": aspsp,
            "state": str(uuid.uuid4()),
            "redirect_url": redirect_url,
            "psu_type": "personal",
        }
        r = requests.post(f"{BASE}/auth", headers=headers, json=body, timeout=30)
        if r.status_code != 200:
            sys.exit(f"POST /auth failed {r.status_code}: {r.text}")
        auth_url = r.json().get("url")
        if not auth_url:
            sys.exit(f"No url in /auth response: {r.json()}")
        if args.auth_only:
            print("\nAuthorization URL (open it, authorize, copy the code):")
            print(auth_url)
            return
        print("\nOpen this URL, authorize in Revolut, then copy the 'code' param:")
        print(auth_url)
        if args.open:
            webbrowser.open(auth_url)
        code = input("\nPaste the code value: ").strip()

    # 3. exchange code for session
    r = requests.post(f"{BASE}/sessions", headers=headers,
                      json={"code": code}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"POST /sessions failed {r.status_code}: {r.text}")
    session = r.json()
    session_id = session.get("session_id")
    accounts = session.get("accounts") or []
    print(f"\nsession : {session_id}")
    print(f"accounts: {len(accounts)}")
    for a in accounts:
        print(f"  - {a.get('name') or a.get('iban') or a.get('uid')} "
              f"({a.get('currency','?')}, usage={a.get('usage')})")
    with open(os.path.join(outdir, "session.json"), "w") as f:
        json.dump(session, f, indent=2)

    # 4. pull transactions + balances per account
    rows = []
    for a in accounts:
        uid = a["uid"]
        print(f"\n>> {a.get('name') or uid}: fetching balances + transactions...")
        try:
            bal = requests.get(f"{BASE}/accounts/{uid}/balances",
                               headers=headers, timeout=30).json()
            with open(os.path.join(outdir, f"balances_{uid}.json"), "w") as f:
                json.dump(bal, f, indent=2)
        except Exception as e:
            print(f"   [warn] balances: {e}")

        try:
            tx = get_transactions(headers, uid, args.strategy, None)
            print(f"   {len(tx)} transactions")
            with open(os.path.join(outdir, f"transactions_{uid}.json"), "w") as f:
                json.dump(tx, f, indent=2)
            for t in tx:
                rows.append(flatten(t, uid))
        except Exception as e:
            print(f"   [error] transactions: {e}", file=sys.stderr)

    # 5. write flat CSV
    if rows:
        csv_path = os.path.join(outdir, "transactions.csv")
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"\nSaved {len(rows)} transactions -> {csv_path}")

    print(f"\nAll data in: {outdir}")
    print("Next: run the analysis step over ./data/")


if __name__ == "__main__":
    main()
