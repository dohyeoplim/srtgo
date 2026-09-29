from typing import Optional

import inquirer
import keyring
import requests

from .ui import prompt


SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/"


def set_slack() -> bool:
    slack_info = prompt(
        [
            inquirer.Text(
                "webhook_url",
                message="Slack Incoming Webhook URL",
                default=keyring.get_password("slack", "webhook_url") or "",
            ),
        ]
    )
    if not slack_info:
        return False

    webhook_url = slack_info["webhook_url"].strip()
    if not webhook_url.startswith(SLACK_WEBHOOK_PREFIX):
        print(f"Webhook URL은 {SLACK_WEBHOOK_PREFIX}로 시작해야 합니다")
        return False

    try:
        send_slack("[SRTGO] 슬랙 설정 완료", webhook_url)
    except requests.RequestException as err:
        print(err)
        return False

    keyring.set_password("slack", "webhook_url", webhook_url)
    return True


def escape_slack(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_slack(text: str, webhook_url: Optional[str] = None) -> None:
    if not (webhook_url := webhook_url or keyring.get_password("slack", "webhook_url")):
        return

    payload = {"text": escape_slack(text), "mrkdwn": False}
    requests.post(webhook_url, json=payload, timeout=10).raise_for_status()


def notify(msg):
    try:
        send_slack(msg)
    except Exception as ex:
        print(f"\n슬랙 전송 실패: {ex}")
