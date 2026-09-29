from typing import List, Tuple

import inquirer
import re

from .config import load_settings, save_settings
from .ui import checkbox_message, prompt


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
                    message=checkbox_message("역 선택"),
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

    save_settings(stations=selected)
    print(f"선택된 역: {','.join(selected)}")
    return True


def edit_station() -> bool:
    stations, default_station_key = get_station()
    station_info = prompt(
        [
            inquirer.Text(
                "stations",
                message="역 수정 (예: 수서,대전,동대구)",
                default=",".join(load_settings().get("stations", [])),
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

    save_settings(stations=selected)
    print(f"선택된 역: {','.join(selected)}")
    return True


def get_station() -> Tuple[List[str], List[str]]:
    return STATIONS, load_settings().get("stations") or DEFAULT_STATIONS


def set_options():
    default_options = get_options()
    choices = prompt(
        [
            inquirer.Checkbox(
                "options",
                message=checkbox_message("예매 옵션"),
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
    save_settings(options=options)


def get_options():
    return load_settings().get("options", [])
