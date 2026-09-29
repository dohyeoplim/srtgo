try:
    from curl_cffi.requests.exceptions import ConnectionError
except ImportError:
    from requests.exceptions import ConnectionError

from datetime import datetime, timedelta
from json.decoder import JSONDecodeError
from random import gammavariate
from termcolor import colored
from typing import Union

import click
import inquirer
import keyring
import time

from .ktx import (
    Korail,
    KorailError,
    MacroError,
    ReserveOption,
    TrainType,
    AdultPassenger,
    ChildPassenger,
    SeniorPassenger,
    Disability1To3Passenger,
    Disability4To6Passenger,
    generate_device_id,
)
from .card import pay_card, set_card
from .settings import (
    RAIL_TYPE,
    edit_station,
    get_options,
    get_station,
    set_options,
    set_station,
)
from .slack import notify, set_slack


# 예약 간격 (평균 간격 (초) = SHAPE * SCALE): gamma distribution (1.25 +/- 0.25 s)
RESERVE_INTERVAL_SHAPE = 4
RESERVE_INTERVAL_SCALE = 0.25
RESERVE_INTERVAL_MIN = 0.25

WAITING_BAR = ["|", "/", "-", "\\"]

RESUME_DELAY = 600

ChoiceType = Union[int, None]


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
        choice = inquirer.list_input(
            message="메뉴 선택 (↕:이동, Enter: 선택)", choices=MENU_CHOICES
        )

        if choice == -1:
            break

        action = ACTIONS.get(choice)
        if action:
            action()


def set_login(debug=False):
    credentials = {
        "id": keyring.get_password(RAIL_TYPE, "id") or "",
        "pass": keyring.get_password(RAIL_TYPE, "pass") or "",
    }

    login_info = inquirer.prompt(
        [
            inquirer.Text(
                "id",
                message="코레일 계정 아이디 (멤버십 번호, 이메일, 전화번호)",
                default=credentials["id"],
            ),
            inquirer.Password(
                "pass",
                message="코레일 계정 패스워드",
                default=credentials["pass"],
            ),
        ]
    )
    if not login_info:
        return False

    try:
        korail = Korail(
            login_info["id"],
            login_info["pass"],
            verbose=debug,
            device_id=get_device_id(),
        )
        if not korail.is_login:
            raise KorailError("로그인에 실패했습니다")

        keyring.set_password(RAIL_TYPE, "id", login_info["id"])
        keyring.set_password(RAIL_TYPE, "pass", login_info["pass"])
        keyring.set_password(RAIL_TYPE, "ok", "1")
        return True
    except KorailError as err:
        print(err)
        if keyring.get_password(RAIL_TYPE, "ok"):
            keyring.delete_password(RAIL_TYPE, "ok")
        return False


def login(debug=False):
    if (
        keyring.get_password(RAIL_TYPE, "id") is None
        or keyring.get_password(RAIL_TYPE, "pass") is None
    ):
        set_login(debug)

    user_id = keyring.get_password(RAIL_TYPE, "id")
    password = keyring.get_password(RAIL_TYPE, "pass")
    return Korail(user_id, password, verbose=debug, device_id=get_device_id())


def get_device_id():
    # Korail's macro detection fingerprints the device id, so it has to be unique
    # per install yet stable across runs.
    if not (device_id := keyring.get_password(RAIL_TYPE, "device_id")):
        device_id = generate_device_id()
        keyring.set_password(RAIL_TYPE, "device_id", device_id)
    return device_id


def reserve(debug=False):
    rail = login(debug=debug)

    # Get date, time, stations, and passenger info
    now = datetime.now() + timedelta(minutes=10)
    today = now.strftime("%Y%m%d")
    this_time = now.strftime("%H%M%S")

    defaults = {
        "departure": keyring.get_password(RAIL_TYPE, "departure") or "서울",
        "arrival": keyring.get_password(RAIL_TYPE, "arrival") or "동대구",
        "date": keyring.get_password(RAIL_TYPE, "date") or today,
        "time": keyring.get_password(RAIL_TYPE, "time") or "120000",
        "adult": int(keyring.get_password(RAIL_TYPE, "adult") or 1),
        "child": int(keyring.get_password(RAIL_TYPE, "child") or 0),
        "senior": int(keyring.get_password(RAIL_TYPE, "senior") or 0),
        "disability1to3": int(keyring.get_password(RAIL_TYPE, "disability1to3") or 0),
        "disability4to6": int(keyring.get_password(RAIL_TYPE, "disability4to6") or 0),
    }

    # Set default stations if departure equals arrival
    if defaults["departure"] == defaults["arrival"]:
        defaults["arrival"] = (
            "동대구" if defaults["departure"] in ("수서", "서울") else None
        )
        defaults["departure"] = defaults["departure"] if defaults["arrival"] else "서울"

    stations, station_key = get_station()
    options = get_options()

    # Booking opens D-31 at 07:00
    max_days = 31 if now.hour >= 7 else 30

    # Generate date choices within the window
    date_choices = [
        (
            (now + timedelta(days=i)).strftime("%Y/%m/%d %a"),
            (now + timedelta(days=i)).strftime("%Y%m%d"),
        )
        for i in range(max_days + 1)
    ]
    time_choices = [(f"{h:02d}", f"{h:02d}0000") for h in range(24)]

    # Build inquirer questions
    q_info = [
        inquirer.List(
            "departure",
            message="출발역 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=station_key,
            default=defaults["departure"],
        ),
        inquirer.List(
            "arrival",
            message="도착역 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=station_key,
            default=defaults["arrival"],
        ),
        inquirer.List(
            "date",
            message="출발 날짜 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=date_choices,
            default=defaults["date"],
        ),
        inquirer.List(
            "time",
            message="출발 시각 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=time_choices,
            default=defaults["time"],
        ),
        inquirer.List(
            "adult",
            message="성인 승객수 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=range(10),
            default=defaults["adult"],
        ),
    ]

    passenger_types = {
        "child": "어린이",
        "senior": "경로우대",
        "disability1to3": "1~3급 장애인",
        "disability4to6": "4~6급 장애인",
    }

    passenger_classes = {
        "adult": AdultPassenger,
        "child": ChildPassenger,
        "senior": SeniorPassenger,
        "disability1to3": Disability1To3Passenger,
        "disability4to6": Disability4To6Passenger,
    }

    PASSENGER_TYPE = {
        passenger_classes["adult"]: "어른/청소년",
        passenger_classes["child"]: "어린이",
        passenger_classes["senior"]: "경로우대",
        passenger_classes["disability1to3"]: "1~3급 장애인",
        passenger_classes["disability4to6"]: "4~6급 장애인",
    }

    # Add passenger type questions if enabled in options
    for key, label in passenger_types.items():
        if key in options:
            q_info.append(
                inquirer.List(
                    key,
                    message=f"{label} 승객수 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
                    choices=range(10),
                    default=defaults[key],
                )
            )

    info = inquirer.prompt(q_info)

    # Validate input info
    if not info:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    if info["departure"] == info["arrival"]:
        print(colored("출발역과 도착역이 같습니다", "green", "on_red") + "\n")
        return

    # Save preferences
    for key, value in info.items():
        keyring.set_password(RAIL_TYPE, key, str(value))

    # Adjust time if needed
    if info["date"] == today and int(info["time"]) < int(this_time):
        info["time"] = this_time

    # Build passenger list
    passengers = []
    total_count = 0
    for key, cls in passenger_classes.items():
        if key in info and info[key] > 0:
            passengers.append(cls(info[key]))
            total_count += info[key]

    # Validate passenger count
    if not passengers:
        print(colored("승객수는 0이 될 수 없습니다", "green", "on_red") + "\n")
        return

    if total_count >= 10:
        print(colored("승객수는 10명을 초과할 수 없습니다", "green", "on_red") + "\n")
        return

    msg_passengers = [
        f"{PASSENGER_TYPE[type(passenger)]} {passenger.count}명"
        for passenger in passengers
    ]
    print(*msg_passengers)

    # Search for trains
    params = {
        "dep": info["departure"],
        "arr": info["arrival"],
        "date": info["date"],
        "time": info["time"],
        "passengers": [AdultPassenger(total_count)],
        "include_no_seats": True,
        **({"train_type": TrainType.KTX} if "ktx" in options else {}),
    }

    trains = rail.search_train(**params)

    def train_decorator(train):
        return repr(train).replace("가능", colored("가능", "green"))

    if not trains:
        print(colored("예약 가능한 열차가 없습니다", "green", "on_red") + "\n")
        return

    # Get train selection
    q_choice = [
        inquirer.Checkbox(
            "trains",
            message="예약할 열차 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
            choices=[(train_decorator(train), i) for i, train in enumerate(trains)],
            default=None,
        ),
    ]

    choice = inquirer.prompt(q_choice)
    if choice is None or not choice["trains"]:
        print(colored("선택한 열차가 없습니다!", "green", "on_red") + "\n")
        return

    n_trains = len(choice["trains"])

    # Get seat type preference
    q_options = [
        inquirer.List(
            "type",
            message="선택 유형",
            choices=[
                ("일반실 우선", ReserveOption.GENERAL_FIRST),
                ("일반실만", ReserveOption.GENERAL_ONLY),
                ("특실 우선", ReserveOption.SPECIAL_FIRST),
                ("특실만", ReserveOption.SPECIAL_ONLY),
            ],
        ),
        inquirer.Confirm("pay", message="예매 시 카드 결제", default=False),
    ]

    options = inquirer.prompt(q_options)
    if options is None:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    # Reserve function
    def _reserve(train):
        reserve = rail.reserve(train, passengers=passengers, option=options["type"])
        msg = f"{reserve}"
        if hasattr(reserve, "tickets") and reserve.tickets:
            msg += "\n" + "\n".join(map(str, reserve.tickets))

        print(colored(f"\n\n🎫 🎉 예매 성공!!! 🎉 🎫\n{msg}\n", "red", "on_green"))

        # The seat is already held, so later failures must not re-enter the reservation loop
        try:
            if options["pay"] and not reserve.is_waiting and pay_card(rail, reserve):
                print(
                    colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"), end=""
                )
                msg += "\n결제 완료"
        except Exception as ex:
            print(f"결제 실패: {ex}")
            msg += f"\n결제 실패: {ex}"

        notify(msg)

    # Reservation loop
    i_try = 0
    start_time = time.time()
    need_login = False
    while True:
        try:
            if need_login:
                rail = login(debug=debug)
                if not rail.is_login:
                    _wait_and_resume("로그인에 실패했습니다")
                    continue
                need_login = False

            i_try += 1
            elapsed_time = time.time() - start_time
            hours, remainder = divmod(int(elapsed_time), 3600)
            minutes, seconds = divmod(remainder, 60)
            print(
                f"\r예매 대기 중... {WAITING_BAR[i_try & 3]} {i_try:4d} ({hours:02d}:{minutes:02d}:{seconds:02d}) ",
                end="",
                flush=True,
            )

            trains = rail.search_train(**params)
            for i in choice["trains"]:
                if _is_seat_available(trains[i], options["type"]):
                    _reserve(trains[i])
                    return
            _sleep()

        except KorailError as ex:
            msg = ex.msg
            if isinstance(ex, MacroError):
                if debug:
                    print(f"\nException: {ex}\nType: {type(ex)}\nArgs: {ex.args}\nMessage: {msg}")
                need_login = True
            elif "Need to Login" in msg:
                need_login = True
            elif not any(
                err in msg
                for err in ("Sold out", "잔여석없음", "예약대기자한도수초과")
            ):
                _wait_and_resume(_error_message(ex))
                need_login = True
            _sleep()

        except JSONDecodeError as ex:
            if debug:
                print(
                    f"\nException: {ex}\nType: {type(ex)}\nArgs: {ex.args}\nMessage: {ex.msg}"
                )
            _sleep()
            need_login = True

        except ConnectionError:
            _wait_and_resume("연결이 끊겼습니다")
            need_login = True

        except Exception as ex:
            if debug:
                print("\nUndefined exception")
            _wait_and_resume(_error_message(ex))
            need_login = True


def _sleep():
    time.sleep(
        gammavariate(RESERVE_INTERVAL_SHAPE, RESERVE_INTERVAL_SCALE)
        + RESERVE_INTERVAL_MIN
    )


def _error_message(ex):
    return f"Exception: {ex}, Type: {type(ex)}, Message: {getattr(ex, 'msg', 'No message attribute')}"


def _wait_and_resume(msg):
    msg = f"{msg}\n{RESUME_DELAY // 60}분 후 자동으로 예매를 재개합니다"
    print(f"\n{msg}")
    notify(msg)

    resume_at = time.time() + RESUME_DELAY
    while (remaining := int(resume_at - time.time())) > 0:
        minutes, seconds = divmod(remaining, 60)
        print(f"\r재개 대기 중... {minutes:02d}:{seconds:02d} (Ctrl-C: 중단) ", end="", flush=True)
        time.sleep(1)
    print()


def _is_seat_available(train, seat_type):
    if not train.has_seat():
        return train.has_waiting_list()
    if seat_type in [ReserveOption.GENERAL_FIRST, ReserveOption.SPECIAL_FIRST]:
        return train.has_seat()
    if seat_type == ReserveOption.GENERAL_ONLY:
        return train.has_general_seat()
    return train.has_special_seat()


def check_reservation(debug=False):
    rail = login(debug=debug)

    while True:
        reservations = rail.reservations()
        tickets = rail.tickets()

        all_reservations = []
        for t in tickets:
            t.is_ticket = True
            all_reservations.append(t)
        for r in reservations:
            if hasattr(r, "paid") and r.paid:
                r.is_ticket = True
            else:
                r.is_ticket = False
            all_reservations.append(r)

        if not reservations and not tickets:
            print(colored("예약 내역이 없습니다", "green", "on_red") + "\n")
            return

        choices = [
            (str(reservation), i) for i, reservation in enumerate(all_reservations)
        ] + [("슬랙으로 예매 정보 전송", -2), ("돌아가기", -1)]

        choice = inquirer.list_input(message="예약 취소 (Enter: 결정)", choices=choices)

        # No choice or go back
        if choice in (None, -1):
            return

        # Send reservation info to Slack
        if choice == -2:
            out = []
            if all_reservations:
                out.append("[ 예매 내역 ]")
                for reservation in all_reservations:
                    out.append(f"🚅{reservation}")

            if out:
                notify("\n".join(out))
            return

        # If choice is an unpaid reservation, ask to pay or cancel
        if (
            not all_reservations[choice].is_ticket
            and not all_reservations[choice].is_waiting
        ):
            answer = inquirer.list_input(
                message=f"결재 대기 승차권: {all_reservations[choice]}",
                choices=[("결제하기", 1), ("취소하기", 2)],
            )

            if answer == 1:
                if pay_card(rail, all_reservations[choice]):
                    print(
                        colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"),
                        end="",
                    )
            elif answer == 2:
                rail.cancel(all_reservations[choice])
            return

        # Else
        if inquirer.confirm(
            message=colored("정말 취소하시겠습니까", "green", "on_red")
        ):
            try:
                if all_reservations[choice].is_ticket:
                    rail.refund(all_reservations[choice])
                else:
                    rail.cancel(all_reservations[choice])
            except Exception as err:
                raise err
            return


if __name__ == "__main__":
    srtgo()
