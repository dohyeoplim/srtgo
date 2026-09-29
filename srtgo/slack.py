from typing import Optional

import requests

from .config import env


def escape_slack(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_slack(text: str, webhook_url: Optional[str] = None) -> None:
    if not (webhook_url := webhook_url or env("SLACK_WEBHOOK_URL")):
        return

    payload = {"text": escape_slack(text), "mrkdwn": False}
    requests.post(webhook_url, json=payload, timeout=10).raise_for_status()


def notify(msg):
    try:
        send_slack(msg)
    except Exception as ex:
        print(f"\n슬랙 전송 실패: {ex}")
