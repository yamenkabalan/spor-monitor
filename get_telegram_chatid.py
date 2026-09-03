# -*- coding: utf-8 -*-
"""
Helper: find your Telegram chat_id and save it into config.json.

Steps:
  1) In Telegram, message @BotFather -> /newbot -> copy the token it gives you.
  2) Put that token into config.json  ->  "telegram_token": "PASTE_HERE"
  3) Open YOUR new bot in Telegram and send it any message (e.g. "hi").
  4) Run:  py get_telegram_chatid.py
"""
import json
from pathlib import Path
import requests

CONFIG = Path(__file__).resolve().parent / "config.json"

def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    token = (cfg.get("telegram_token") or "").strip()
    if not token:
        print("!! Put your bot token in config.json (telegram_token) first.")
        return
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
    if not r.get("ok"):
        print("Telegram error:", r)
        return
    results = r.get("result", [])
    if not results:
        print("No messages found. Open your bot in Telegram and send it any message, "
              "then run this again.")
        return
    for u in reversed(results):
        msg = u.get("message") or u.get("channel_post")
        if msg and msg.get("chat"):
            chat_id = str(msg["chat"]["id"])
            cfg["telegram_chat_id"] = chat_id
            CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"OK! chat_id = {chat_id}  (saved to config.json)")
            # send a confirmation
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat_id, "text": "✅ Telegram متصل بنجاح."}, timeout=15)
            return
    print("Could not find a chat id. Send your bot a message and retry.")

if __name__ == "__main__":
    main()
