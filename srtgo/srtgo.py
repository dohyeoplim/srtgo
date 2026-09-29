import click
from termcolor import colored

from .config import load_env
from .reservations import check_reservation
from .reserve import reserve
from .settings import edit_station, set_options, set_station
from .ui import list_input, list_message


@click.command()
@click.option("--debug", is_flag=True, help="Debug mode")
def srtgo(debug=False):
    load_env()

    MENU_CHOICES = [
        ("예매 시작", 1),
        ("예매 확인/결제/취소", 2),
        ("역 설정", 3),
        ("역 직접 수정", 4),
        ("예매 옵션 설정", 5),
        ("나가기", -1),
    ]

    ACTIONS = {
        1: lambda: reserve(debug),
        2: lambda: check_reservation(debug),
        3: set_station,
        4: edit_station,
        5: set_options,
    }

    while True:
        choice = list_input(message=list_message("메뉴 선택"), choices=MENU_CHOICES)

        if choice in (-1, None):
            break

        action = ACTIONS.get(choice)
        if not action:
            continue

        try:
            action()
        except KeyboardInterrupt:
            print(colored("\n작업을 중단했습니다", "green", "on_red") + "\n")


if __name__ == "__main__":
    srtgo()
