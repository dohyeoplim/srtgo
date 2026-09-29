try:
    from curl_cffi.requests.exceptions import ConnectionError
except ImportError:
    from requests.exceptions import ConnectionError

from datetime import datetime, timedelta
from json.decoder import JSONDecodeError
from random import gammavariate
from termcolor import colored

import inquirer
import keyring
import time

from .account import login
from .card import pay_card
from .ktx import (
    KorailError,
    MacroError,
    ReserveOption,
    TrainType,
    AdultPassenger,
    ChildPassenger,
    SeniorPassenger,
    Disability1To3Passenger,
    Disability4To6Passenger,
)
from .settings import RAIL_TYPE, get_options, get_station
from .slack import notify


RESERVE_INTERVAL_SHAPE = 4
RESERVE_INTERVAL_SCALE = 0.25
RESERVE_INTERVAL_MIN = 0.25

WAITING_BAR = ["|", "/", "-", "\\"]

RESUME_DELAY = 600


def reserve(debug=False):
    rail = login(debug=debug)

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

    if defaults["departure"] == defaults["arrival"]:
        defaults["arrival"] = (
            "동대구" if defaults["departure"] in ("수서", "서울") else None
        )
        defaults["departure"] = defaults["departure"] if defaults["arrival"] else "서울"

    stations, station_key = get_station()
    options = get_options()

    max_days = 31 if now.hour >= 7 else 30

    date_choices = [
        (
            (now + timedelta(days=i)).strftime("%Y/%m/%d %a"),
            (now + timedelta(days=i)).strftime("%Y%m%d"),
        )
        for i in range(max_days + 1)
    ]
    time_choices = [(f"{h:02d}", f"{h:02d}0000") for h in range(24)]

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

    if not info:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    if info["departure"] == info["arrival"]:
        print(colored("출발역과 도착역이 같습니다", "green", "on_red") + "\n")
        return

    for key, value in info.items():
        keyring.set_password(RAIL_TYPE, key, str(value))

    if info["date"] == today and int(info["time"]) < int(this_time):
        info["time"] = this_time

    passengers = []
    total_count = 0
    for key, cls in passenger_classes.items():
        if key in info and info[key] > 0:
            passengers.append(cls(info[key]))
            total_count += info[key]

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

    def _reserve(train):
        reserve = rail.reserve(train, passengers=passengers, option=options["type"])
        msg = f"{reserve}"
        if hasattr(reserve, "tickets") and reserve.tickets:
            msg += "\n" + "\n".join(map(str, reserve.tickets))

        print(colored(f"\n\n🎫 🎉 예매 성공!!! 🎉 🎫\n{msg}\n", "red", "on_green"))

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
