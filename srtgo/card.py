import inquirer
import keyring

from .ui import prompt


def set_card() -> None:
    card_info = {
        "number": keyring.get_password("card", "number") or "",
        "password": keyring.get_password("card", "password") or "",
        "birthday": keyring.get_password("card", "birthday") or "",
        "expire": keyring.get_password("card", "expire") or "",
    }

    card_info = prompt(
        [
            inquirer.Password(
                "number",
                message="신용카드 번호 (하이픈 제외)",
                default=card_info["number"],
            ),
            inquirer.Password(
                "password",
                message="카드 비밀번호 앞 2자리",
                default=card_info["password"],
            ),
            inquirer.Password(
                "birthday",
                message="생년월일 (YYMMDD) 또는 사업자등록번호",
                default=card_info["birthday"],
            ),
            inquirer.Password(
                "expire",
                message="카드 유효기간 (YYMM)",
                default=card_info["expire"],
            ),
        ]
    )
    if card_info:
        for key, value in card_info.items():
            keyring.set_password("card", key, value)
        keyring.set_password("card", "ok", "1")


def pay_card(rail, reservation) -> bool:
    if keyring.get_password("card", "ok"):
        birthday = keyring.get_password("card", "birthday")
        return rail.pay_with_card(
            reservation,
            keyring.get_password("card", "number"),
            keyring.get_password("card", "password"),
            birthday,
            keyring.get_password("card", "expire"),
            0,
            "J" if len(birthday) == 6 else "S",
        )
    return False
