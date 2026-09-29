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
from .ui import prompt


RESERVE_INTERVAL_SHAPE = 4
RESERVE_INTERVAL_SCALE = 0.25
RESERVE_INTERVAL_MIN = 0.25

WAITING_BAR = ["|", "/", "-", "\\"]

RESUME_DELAY = 600


PASSENGER_TYPES = {
    "adult": ("어른/청소년", AdultPassenger),
    "child": ("어린이", ChildPassenger),
    "senior": ("경로우대", SeniorPassenger),
    "disability1to3": ("1~3급 장애인", Disability1To3Passenger),
    "disability4to6": ("4~6급 장애인", Disability4To6Passenger),
}

SKIPPABLE_ERRORS = ("Sold out", "잔여석없음", "예약대기자한도수초과")


def reserve(debug=False):
    rail = login(debug=debug)

    now = datetime.now() + timedelta(minutes=10)
    preferences = get_options()

    info = _ask_trip(_load_defaults(now), now, preferences)
    if not info:
        _alert("예매 정보 입력 중 취소되었습니다")
        return

    if info["departure"] == info["arrival"]:
        _alert("출발역과 도착역이 같습니다")
        return

    for key, value in info.items():
        keyring.set_password(RAIL_TYPE, key, str(value))

    today, this_time = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
    if info["date"] == today and int(info["time"]) < int(this_time):
        info["time"] = this_time

    passengers = _build_passengers(info)
    total_count = sum(passenger.count for passenger in passengers)

    if not passengers:
        _alert("승객수는 0이 될 수 없습니다")
        return

    if total_count >= 10:
        _alert("승객수는 10명을 초과할 수 없습니다")
        return

    print(*_describe_passengers(passengers))

    params = _search_params(info, total_count, preferences)
    trains = rail.search_train(**params)
    if not trains:
        _alert("예약 가능한 열차가 없습니다")
        return

    selected = _ask_trains(trains)
    if not selected:
        _alert("선택한 열차가 없습니다!")
        return

    seat_options = _ask_seat_options()
    if seat_options is None:
        _alert("예매 정보 입력 중 취소되었습니다")
        return

    _reserve_loop(rail, params, selected, passengers, seat_options, debug)


def _alert(msg):
    print(colored(msg, "green", "on_red") + "\n")


def _load_defaults(now):
    def saved(key, fallback):
        return keyring.get_password(RAIL_TYPE, key) or fallback

    defaults = {
        "departure": saved("departure", "서울"),
        "arrival": saved("arrival", "동대구"),
        "date": saved("date", now.strftime("%Y%m%d")),
        "time": saved("time", "120000"),
        **{key: int(saved(key, 1 if key == "adult" else 0)) for key in PASSENGER_TYPES},
    }

    if defaults["departure"] == defaults["arrival"]:
        defaults["arrival"] = (
            "동대구" if defaults["departure"] in ("수서", "서울") else None
        )
        defaults["departure"] = defaults["departure"] if defaults["arrival"] else "서울"

    return defaults


def _date_choices(now):
    max_days = 31 if now.hour >= 7 else 30
    days = [now + timedelta(days=i) for i in range(max_days + 1)]
    return [(day.strftime("%Y/%m/%d %a"), day.strftime("%Y%m%d")) for day in days]


def _ask_trip(defaults, now, preferences):
    _, station_key = get_station()
    time_choices = [(f"{h:02d}", f"{h:02d}0000") for h in range(24)]

    questions = [
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
            choices=_date_choices(now),
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

    questions += [
        inquirer.List(
            key,
            message=f"{label} 승객수 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=range(10),
            default=defaults[key],
        )
        for key, (label, _) in PASSENGER_TYPES.items()
        if key != "adult" and key in preferences
    ]

    return prompt(questions)


def _build_passengers(info):
    return [
        cls(info[key])
        for key, (_, cls) in PASSENGER_TYPES.items()
        if info.get(key, 0) > 0
    ]


def _describe_passengers(passengers):
    labels = {cls: label for label, cls in PASSENGER_TYPES.values()}
    return [f"{labels[type(passenger)]} {passenger.count}명" for passenger in passengers]


def _search_params(info, total_count, preferences):
    return {
        "dep": info["departure"],
        "arr": info["arrival"],
        "date": info["date"],
        "time": info["time"],
        "passengers": [AdultPassenger(total_count)],
        "include_no_seats": True,
        **({"train_type": TrainType.KTX} if "ktx" in preferences else {}),
    }


def _train_label(train):
    return repr(train).replace("가능", colored("가능", "green"))


def _ask_trains(trains):
    choice = prompt(
        [
            inquirer.Checkbox(
                "trains",
                message="예약할 열차 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
                choices=[(_train_label(train), i) for i, train in enumerate(trains)],
                default=None,
            ),
        ]
    )
    return choice["trains"] if choice else None


def _ask_seat_options():
    return prompt(
        [
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
    )


def _complete_reservation(rail, train, passengers, seat_options):
    reservation = rail.reserve(train, passengers=passengers, option=seat_options["type"])
    msg = f"{reservation}"
    if hasattr(reservation, "tickets") and reservation.tickets:
        msg += "\n" + "\n".join(map(str, reservation.tickets))

    print(colored(f"\n\n🎫 🎉 예매 성공!!! 🎉 🎫\n{msg}\n", "red", "on_green"))

    try:
        if seat_options["pay"] and not reservation.is_waiting and pay_card(rail, reservation):
            print(
                colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"), end=""
            )
            msg += "\n결제 완료"
    except Exception as ex:
        print(f"결제 실패: {ex}")
        msg += f"\n결제 실패: {ex}"

    notify(msg)


def _print_progress(i_try, start_time):
    hours, remainder = divmod(int(time.time() - start_time), 3600)
    minutes, seconds = divmod(remainder, 60)
    print(
        f"\r예매 대기 중... {WAITING_BAR[i_try & 3]} {i_try:4d} ({hours:02d}:{minutes:02d}:{seconds:02d}) ",
        end="",
        flush=True,
    )


def _reserve_loop(rail, params, selected, passengers, seat_options, debug):
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
            _print_progress(i_try, start_time)

            trains = rail.search_train(**params)
            for i in selected:
                if _is_seat_available(trains[i], seat_options["type"]):
                    _complete_reservation(rail, trains[i], passengers, seat_options)
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
            elif not any(err in msg for err in SKIPPABLE_ERRORS):
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
