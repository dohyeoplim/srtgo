from .config import env


CARD_ENV = {
    "number": "CARD_NUMBER",
    "password": "CARD_PASSWORD_FIRST_2",
    "birthday": "CARD_BIRTHDATE_YYMMDD",
    "expire": "CARD_EXPIRY_YYMM",
}


def pay_card(rail, reservation) -> bool:
    card = {key: env(name) for key, name in CARD_ENV.items()}
    if not all(card.values()):
        return False
    return rail.pay_with_card(
        reservation,
        card["number"],
        card["password"],
        card["birthday"],
        card["expire"],
        0,
        "J" if len(card["birthday"]) == 6 else "S",
    )
