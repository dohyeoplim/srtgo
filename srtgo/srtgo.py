import click

from .account import set_login
from .card import set_card
from .reservations import check_reservation
from .reserve import reserve
from .settings import edit_station, set_options, set_station
from .slack import set_slack
from .ui import list_input


@click.command()
@click.option("--debug", is_flag=True, help="Debug mode")
def srtgo(debug=False):
    MENU_CHOICES = [
        ("예매 시작", 1),
        ("예매 확인/결제/취소", 2),
        ("로그인 설정", 3),
        ("슬랙 설정", 4),
        ("카드 설정", 5),
        ("역 설정", 6),
        ("역 직접 수정", 7),
        ("예매 옵션 설정", 8),
        ("나가기", -1),
    ]

    ACTIONS = {
        1: lambda: reserve(debug),
        2: lambda: check_reservation(debug),
        3: lambda: set_login(debug),
        4: set_slack,
        5: set_card,
        6: set_station,
        7: edit_station,
        8: set_options,
    }

    while True:
        choice = list_input(
            message="메뉴 선택 (↕:이동, Enter: 선택)", choices=MENU_CHOICES
        )

        if choice == -1:
            break

        action = ACTIONS.get(choice)
        if action:
            action()


if __name__ == "__main__":
    srtgo()
