# -*- coding: utf-8 -*-
"""
Spor Istanbul - Seans (session) availability monitor.

- Logs in once with the credentials from config.json
- Every N minutes reloads the session page
- Detects GREEN availability badges (a free booking slot)
- Alerts you: local alarm sound + Telegram message

Run:
    python monitor.py            # 24/7 monitor
    python monitor.py --once     # single check then exit
    python monitor.py --debug    # single check, visible browser, dumps page + colors
"""

import os
import sys
import json
import time
import datetime
import traceback
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# Make console output UTF-8 safe (Turkish/Arabic) regardless of code page,
# so a stray non-ASCII character can never crash the 24/7 loop.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
LOG_PATH = HERE / "monitor.log"
DEBUG_HTML = HERE / "debug_page.html"
DEBUG_PNG = HERE / "debug_page.png"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Each session on the weekly grid is a <div id="..._dvSeans_N" class="well">
# whose BORDER color encodes its reservation status:
#   #08f51a green  -> Rezervasyona Acik  (OPEN for booking)  <-- we alert on this
#   #3ed1ff blue   -> Secilmis           (you already picked it)
#   #E81F69 pink   -> Dolu               (FULL)
#   #808080 gray   -> Rezervasyona Kapali(closed)
#   #E8FD2F yellow -> Secili
# We read the border color (not the number badge) because the number can be
# green while the session itself is Full/closed.
DETECT_JS = r"""
() => {
  function rgb(el, prop){
    const m = getComputedStyle(el)[prop].match(/(\d+),\s*(\d+),\s*(\d+)/);
    return m ? [ +m[1], +m[2], +m[3] ] : null;
  }
  function classify(c){
    if (!c) return 'other';
    const [r, g, b] = c;
    if (g > 150 && r < 120 && b < 120) return 'green';   // open
    if (r > 180 && g > 180 && b < 120) return 'yellow';  // selected
    if (r > 150 && g < 120 && (r - g) > 60) return 'pink';   // full
    if (b > 150 && r < 150 && (b - r) > 40) return 'blue';   // yours
    if (Math.abs(r - g) < 40 && Math.abs(g - b) < 40) return 'gray'; // closed
    return 'other';
  }
  const cards = [...document.querySelectorAll('[id*="dvSeans"]')];
  const out = [];
  for (const card of cards){
    const col = rgb(card, 'borderTopColor') || rgb(card, 'borderColor');
    const category = classify(col);
    const nameEl = card.querySelector('label[title="Salon Adı"]');
    const timeEl = card.querySelector('[id*="lblSeansSaat"]');
    const cntEl  = card.querySelector('[title="Kalan Kontenjan"]');
    let day = '';
    const panel = card.closest('.panel');
    if (panel){
      const t = panel.querySelector('.panel-title');
      if (t) day = t.innerText.replace(/\s+/g, ' ').trim();
    }
    out.push({
      day: day,
      name: (nameEl ? nameEl.innerText : '').trim(),
      time: (timeEl ? timeEl.innerText : '').trim(),
      count: cntEl ? parseInt((cntEl.innerText || '0').trim(), 10) : null,
      category: category,
      color: col ? `rgb(${col.join(',')})` : null
    });
  }
  return out;
}
"""

CATEGORY_LABEL = {
    "green": "🟢 Açık",
    "blue": "🔵 Seçilmiş",
    "pink": "🔴 Dolu",
    "gray": "⚫ Kapalı",
    "yellow": "🟡 Seçili",
    "other": "❔ Bilinmeyen",
}


def summarize(cards):
    counts = {}
    for c in cards:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    return counts


def summary_line(cards):
    counts = summarize(cards)
    order = ["green", "blue", "pink", "gray", "yellow", "other"]
    parts = [f"{k}:{counts.get(k, 0)}" for k in order if counts.get(k, 0)]
    return f"{len(cards)} كرت | " + " ".join(parts) if parts else f"{len(cards)} كرت"


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    line = f"[{now()}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        try:
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
            sys.stdout.flush()
        except Exception:
            pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# Built-in defaults so the tool also works with no config.json present
# (e.g. on GitHub Actions, where secrets arrive via environment variables).
DEFAULTS = {
    "tc": "",
    "password": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    "check_interval_minutes": 7,
    "renotify_cooldown_minutes": 15,
    "heartbeat": True,
    "headless": True,
    "alarm_sound": True,
    "alarm_beeps": 8,
    "seanslarim_url": "https://online.spor.istanbul/uyespor",
    "session_url": "https://online.spor.istanbul/uyeseanssecim",
    "login_url": "https://online.spor.istanbul/uyegiris",
    "membership_keyword": "",
}

# Environment variables (GitHub Secrets) override config.json values.
ENV_MAP = {
    "SPOR_TC": "tc",
    "SPOR_PASSWORD": "password",
    "TELEGRAM_TOKEN": "telegram_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log(f"config.json read error: {e}")
    for env, key in ENV_MAP.items():
        v = os.environ.get(env)
        if v:
            cfg[key] = v
    hb = os.environ.get("HEARTBEAT")
    if hb is not None:
        cfg["heartbeat"] = hb.strip().lower() in ("1", "true", "yes", "on")
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"config.json write skipped: {e}")


# ----------------------------- notifications --------------------------------

def play_alarm(cfg):
    if not cfg.get("alarm_sound", True):
        return
    try:
        import winsound
        for _ in range(int(cfg.get("alarm_beeps", 8))):
            winsound.Beep(1000, 300)
            winsound.Beep(1400, 300)
    except Exception as e:
        log(f"Alarm sound failed: {e}")


def tg_detect_chat_id(token):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=15
        ).json()
        for u in reversed(r.get("result", [])):
            msg = u.get("message") or u.get("channel_post")
            if msg and msg.get("chat"):
                return str(msg["chat"]["id"])
    except Exception as e:
        log(f"Telegram getUpdates failed: {e}")
    return None


def send_telegram(cfg, text):
    token = (cfg.get("telegram_token") or "").strip()
    chat_id = (cfg.get("telegram_chat_id") or "").strip()
    if not token:
        return
    if not chat_id:
        chat_id = tg_detect_chat_id(token)
        if chat_id:
            cfg["telegram_chat_id"] = chat_id
            save_config(cfg)
            log(f"Telegram chat_id detected & saved: {chat_id}")
        else:
            log("Telegram token set but no chat_id yet. "
                "Open your bot in Telegram and send it any message once.")
            return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if not r.ok:
            log(f"Telegram send failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log(f"Telegram send error: {e}")


# ------------------------------- browser ------------------------------------

def is_login_page(page):
    try:
        if page.query_selector("#txtSifre"):
            return True
    except Exception:
        pass
    return "uyegiris" in (page.url or "")


def do_login(page, cfg):
    log("Logging in...")
    page.goto(cfg["login_url"], wait_until="domcontentloaded", timeout=60000)
    # dismiss cookie banner if present
    for label in ("Tamam", "Kabul", "Kapat"):
        try:
            page.get_by_role("button", name=label).first.click(timeout=2000)
            break
        except Exception:
            pass
    page.fill("#txtTCPasaport", str(cfg["tc"]))
    page.fill("#txtSifre", str(cfg["password"]))
    page.click("#btnGirisYap")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    if is_login_page(page):
        raise RuntimeError(
            "Login appears to have failed (still on login page). "
            "Check TC/password in config.json."
        )
    log("Login OK.")


# JS to locate the green "Seans Seç (Rezervasyon Yap)" button on the
# Seanslarım page. Returns its ASP.NET __doPostBack target, or null.
FIND_BUTTON_JS = r"""
(kw) => {
  function norm(s){
    return (s || '')
      .replace(/[İıI]/g, 'I').replace(/[şŞ]/g, 'S').replace(/[ğĞ]/g, 'G')
      .replace(/[üÜ]/g, 'U').replace(/[öÖ]/g, 'O').replace(/[çÇ]/g, 'C')
      .toUpperCase();
  }
  const links = [...document.querySelectorAll('a')].filter(a => {
    const t = (a.getAttribute('data-bs-original-title') || '') + ' ' + (a.textContent || '');
    const isSeans = /SEANS SE|REZERVASYON YAP/.test(norm(t));
    const href = a.getAttribute('href') || '';
    const isPostback = /__doPostBack/.test(href) && /seanssec/i.test(href);
    const isBtn = (a.className || '').includes('btn-success');
    return isSeans && (isPostback || isBtn);
  });
  if (!links.length) return null;
  let chosen = links[0];
  const k = norm(kw);
  if (k) {
    for (const a of links) {
      const row = a.closest('tr');
      if (row && norm(row.innerText).includes(k)) { chosen = a; break; }
    }
  }
  const href = chosen.getAttribute('href') || '';
  const m = href.match(/__doPostBack\('([^']+)','([^']*)'\)/);
  return { id: chosen.id, target: m ? m[1] : null, arg: m ? m[2] : '' };
}
"""


def go_to_grid(page, cfg):
    """From the Seanslarım page, open the weekly session grid by clicking
    the green 'Seans Seç (Rezervasyon Yap)' button."""
    info = page.evaluate(FIND_BUTTON_JS, cfg.get("membership_keyword", "") or "")
    if not info:
        raise RuntimeError(
            "Could not find the 'Seans Seç (Rezervasyon Yap)' button on the "
            "Seanslarım page. (No bookable membership with remaining rights?)"
        )
    if info.get("target"):
        page.evaluate("([t, a]) => __doPostBack(t, a)", [info["target"], info["arg"]])
    elif info.get("id"):
        page.click(f"#{info['id']}")
    else:
        raise RuntimeError("Found the button but could not trigger it.")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass


def open_sessions(page, cfg):
    # Direct navigation to /uyeseanssecim errors out; we must enter through
    # the Seanslarim page and click the green "Seans Sec" button.
    page.goto(cfg["seanslarim_url"], wait_until="domcontentloaded", timeout=60000)
    if is_login_page(page):
        do_login(page, cfg)
        page.goto(cfg["seanslarim_url"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1000)
    go_to_grid(page, cfg)
    # give client-side rendering a moment
    page.wait_for_timeout(2500)


def check_once(page, cfg):
    open_sessions(page, cfg)
    cards = page.evaluate(DETECT_JS)
    greens = [c for c in cards if c.get("category") == "green"]
    return cards, greens


# ------------------------------- runners ------------------------------------

def slot_label(g):
    parts = [p for p in (g.get("day", ""), g.get("name", ""), g.get("time", "")) if p]
    label = " | ".join(parts) if parts else "seans"
    if g.get("count") is not None:
        label += f"  ({g['count']} yer)"
    return label


def process_greens(greens, cfg, state):
    """Alert on new / cooldown-expired green (bookable) slots."""
    cooldown = int(cfg.get("renotify_cooldown_minutes", 15)) * 60
    ts = time.time()
    to_alert = []
    for g in greens:
        key = f"{g.get('day','')}|{g.get('name','')}|{g.get('time','')}"
        last = state.get(key, 0)
        if ts - last >= cooldown:
            to_alert.append(g)
            state[key] = ts
    if not to_alert:
        return
    lines = ["🟢 Rezervasyona açık seans var! Spor İstanbul"]
    for g in to_alert:
        lines.append("• " + slot_label(g))
    lines.append(cfg.get("seanslarim_url", cfg.get("session_url", "")))
    text = "\n".join(lines)
    log("GREEN SLOT(S) FOUND -> alerting")
    for ln in lines:
        log("   " + ln)
    play_alarm(cfg)
    send_telegram(cfg, text)


def run_debug():
    cfg = load_config()
    cfg["headless"] = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(user_agent=UA, locale="tr-TR")
        page = ctx.new_page()
        do_login(page, cfg)
        cards, greens = check_once(page, cfg)
        try:
            DEBUG_HTML.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(DEBUG_PNG), full_page=True)
        except Exception as e:
            log(f"debug dump failed: {e}")
        log(f"Found {len(cards)} session card(s):")
        for c in cards:
            log(f"  [{c['category']:<6}] {str(c['color']):<16} "
                f"count={str(c['count']):<4} {c['day']} {c['name']} {c['time']}")
        log("---- breakdown ----")
        for cat, n in summarize(cards).items():
            log(f"  {CATEGORY_LABEL.get(cat, cat)} : {n}")
        log(f"=> {len(greens)} available (green) slot(s).")
        log(f"Saved: {DEBUG_HTML.name} , {DEBUG_PNG.name}")
        if greens:
            process_greens(greens, cfg, {})
        input("Press Enter to close the browser...")
        browser.close()


def run_once():
    cfg = load_config()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.get("headless", True))
        ctx = browser.new_context(user_agent=UA, locale="tr-TR")
        page = ctx.new_page()
        try:
            do_login(page, cfg)
            cards, greens = check_once(page, cfg)
            log("check: " + summary_line(cards))
            if greens:
                process_greens(greens, cfg, {})
            elif cfg.get("heartbeat"):
                counts = summarize(cards)
                brk = " | ".join(
                    f"{CATEGORY_LABEL.get(k, k)}: {counts.get(k, 0)}"
                    for k in ["green", "blue", "pink", "gray", "yellow"]
                )
                send_telegram(cfg, f"⏱️ {now()}\nİzleniyor — açık seans yok.\n{brk}")
            else:
                log("No available (green) slots right now.")
        except Exception as e:
            log(f"ERROR during check: {e}")
            # dump what the browser saw, so we can debug from CI artifacts
            try:
                page.screenshot(path=str(DEBUG_PNG), full_page=True)
                DEBUG_HTML.write_text(page.content(), encoding="utf-8")
                log(f"Saved debug snapshot: {DEBUG_PNG.name}, {DEBUG_HTML.name}")
                log(f"Current URL: {page.url}")
            except Exception as e2:
                log(f"debug dump failed: {e2}")
            raise
        finally:
            browser.close()


def run_forever():
    cfg = load_config()
    interval = int(cfg.get("check_interval_minutes", 7)) * 60
    state = {}
    log("=== Spor Istanbul monitor started ===")
    log(f"Interval: {cfg.get('check_interval_minutes', 7)} min | "
        f"headless={cfg.get('headless', True)} | "
        f"telegram={'on' if cfg.get('telegram_token') else 'off'}")
    first_check = True
    while True:  # outer loop: relaunch browser on fatal errors
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=cfg.get("headless", True))
                ctx = browser.new_context(user_agent=UA, locale="tr-TR")
                page = ctx.new_page()
                do_login(page, cfg)
                while True:  # inner loop: periodic checks
                    try:
                        cards, greens = check_once(page, cfg)
                        log("check: " + summary_line(cards))
                        if first_check:
                            first_check = False
                            counts = summarize(cards)
                            brk = " | ".join(
                                f"{CATEGORY_LABEL.get(k, k)}: {counts.get(k, 0)}"
                                for k in ["green", "blue", "pink", "gray", "yellow"]
                            )
                            send_telegram(
                                cfg,
                                "✅ İzleme başladı (her "
                                f"{cfg.get('check_interval_minutes', 7)} dakikada bir).\n"
                                f"Şu anki durum: {brk}\n"
                                "Bir seans 🟢 açık (rezervasyona uygun) olunca "
                                "hemen haber vereceğim.",
                            )
                        if greens:
                            process_greens(greens, cfg, state)
                        elif cfg.get("heartbeat"):
                            # periodic status ping so you know it's alive
                            counts = summarize(cards)
                            brk = " | ".join(
                                f"{CATEGORY_LABEL.get(k, k)}: {counts.get(k, 0)}"
                                for k in ["green", "blue", "pink", "gray", "yellow"]
                            )
                            send_telegram(
                                cfg,
                                f"⏱️ {now()}\nİzleniyor — açık seans yok.\n{brk}",
                            )
                    except Exception as e:
                        log(f"check error: {e}")
                        # a transient error: try to recover on next cycle;
                        # if the page/browser is dead, break to relaunch.
                        if "Target closed" in str(e) or "has been closed" in str(e):
                            raise
                    time.sleep(interval)
        except KeyboardInterrupt:
            log("Stopped by user.")
            return
        except Exception as e:
            log(f"FATAL: {e}\n{traceback.format_exc()}")
            log("Relaunching browser in 60s...")
            time.sleep(60)


def main():
    args = set(sys.argv[1:])
    if "--debug" in args:
        run_debug()
    elif "--once" in args:
        run_once()
    else:
        run_forever()


if __name__ == "__main__":
    main()
