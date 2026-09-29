from typing import List, Tuple

import inquirer
import keyring
import re

from .ui import prompt


RAIL_TYPE = "KTX"

STATIONS = [
    "서울",
    "용산",
    "영등포",
    "광명",
    "수원",
    "수서",
    "동탄",
    "평택지제",
    "천안아산",
    "오송",
    "대전",
    "서대전",
    "공주",
    "김천구미",
    "서대구",
    "동대구",
    "경산",
    "경주",
    "포항",
    "밀양",
    "구포",
    "부산",
    "울산(통도사)",
    "진영",
    "창원중앙",
    "창원",
    "마산",
    "진주",
    "논산",
    "익산",
    "전주",
    "정읍",
    "광주송정",
    "나주",
    "목포",
    "남원",
    "곡성",
    "구례구",
    "순천",
    "여천",
    "여수EXPO",
    "청량리",
    "강릉",
    "행신",
    "정동진",
]
DEFAULT_STATIONS = ["서울", "수서", "대전", "동대구", "부산"]


def set_station() -> bool:
    stations, default_station_key = get_station()

    if not (
        station_info := prompt(
            [
                inquirer.Checkbox(
                    "stations",
                    message="역 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
                    choices=stations,
                    default=default_station_key,
                )
            ]
        )
    ):
        return False

    if not (selected := station_info["stations"]):
        print("선택된 역이 없습니다.")
        return False

    keyring.set_password(
        RAIL_TYPE, "station", (selected_stations := ",".join(selected))
    )
    print(f"선택된 역: {selected_stations}")
    return True


def edit_station() -> bool:
    stations, default_station_key = get_station()
    station_info = prompt(
        [
            inquirer.Text(
                "stations",
                message="역 수정 (예: 수서,대전,동대구)",
                default=keyring.get_password(RAIL_TYPE, "station") or "",
            )
        ]
    )
    if not station_info:
        return False

    if not (selected := station_info["stations"]):
        print("선택된 역이 없습니다.")
        return False

    selected = [s.strip() for s in selected.split(",")]

    hangul = re.compile("[가-힣]+")
    for station in selected:
        if not hangul.search(station):
            print(f"'{station}'는 잘못된 입력입니다. 기본 역으로 설정합니다.")
            selected = DEFAULT_STATIONS
            break

    keyring.set_password(
        RAIL_TYPE, "station", (selected_stations := ",".join(selected))
    )
    print(f"선택된 역: {selected_stations}")
    return True


def get_station() -> Tuple[List[str], List[str]]:
    station_key = keyring.get_password(RAIL_TYPE, "station")

    if not station_key:
        return STATIONS, DEFAULT_STATIONS

    return STATIONS, station_key.split(",")


def set_options():
    default_options = get_options()
    choices = prompt(
        [
            inquirer.Checkbox(
                "options",
                message="예매 옵션 선택 (Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
                choices=[
                    ("어린이", "child"),
                    ("경로우대", "senior"),
                    ("중증장애인", "disability1to3"),
                    ("경증장애인", "disability4to6"),
                    ("KTX만", "ktx"),
                ],
                default=default_options,
            )
        ]
    )

    if choices is None:
        return

    options = choices.get("options", [])
    keyring.set_password("SRT", "options", ",".join(options))


def get_options():
    options = keyring.get_password("SRT", "options") or ""
    return options.split(",") if options else []
