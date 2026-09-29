import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Callable, List, Literal, Optional, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, model_validator
from typing_extensions import TypedDict

from srtgo.card import CARD_KEYS, pay_card
from srtgo.ktx import (
    AdultPassenger,
    Korail,
    KorailError,
    MacroError,
    NeedToLoginError,
    NoResultsError,
    Reservation,
    ReserveOption,
    TrainType,
    generate_device_id,
)
from srtgo.reserve import PASSENGER_TYPES, RESUME_DELAY, SKIPPABLE_ERRORS, _interval, _is_seat_available
from srtgo.slack import send_slack


# Each watch holds its own Korail session, and parallel polling raises the chance of macro detection.
MAX_WATCHES = 3

Date = Annotated[str, Field(pattern=r"^\d{8}$", description="Departure date as YYYYMMDD")]
Time = Annotated[str, Field(pattern=r"^\d{6}$", description="Earliest departure time as HHMMSS")]
SeatType = Literal["general_first", "general_only", "special_first", "special_only"]

SEAT_OPTIONS = {
    "general_first": ReserveOption.GENERAL_FIRST,
    "general_only": ReserveOption.GENERAL_ONLY,
    "special_first": ReserveOption.SPECIAL_FIRST,
    "special_only": ReserveOption.SPECIAL_ONLY,
}

T = TypeVar("T")


class Passengers(BaseModel):
    adult: int = Field(1, ge=0, le=9)
    child: int = Field(0, ge=0, le=9)
    senior: int = Field(0, ge=0, le=9)
    disability1to3: int = Field(0, ge=0, le=9)
    disability4to6: int = Field(0, ge=0, le=9)

    @model_validator(mode="after")
    def check_total(self) -> "Passengers":
        if not 1 <= self.total() <= 9:
            raise ValueError("total passengers must be between 1 and 9")
        return self

    def total(self) -> int:
        return sum(self.model_dump().values())

    def build(self) -> list:
        return [cls(count) for key, (_, cls) in PASSENGER_TYPES.items() if (count := getattr(self, key)) > 0]


class TrainInfo(TypedDict):
    train_no: str
    train_type: str
    departure: str
    arrival: str
    date: str
    departure_time: str
    arrival_time: str
    general_seat: bool
    special_seat: bool
    waiting_list: bool


class ReservationInfo(TypedDict):
    reservation_id: Optional[str]
    summary: str
    paid: bool
    waiting: bool
    price: int
    payment_error: Optional[str]


class WatchInfo(TypedDict):
    watch_id: str
    status: str
    trip: str
    train_nos: List[str]
    attempts: int
    started_at: str
    last_error: Optional[str]
    reservation: Optional[ReservationInfo]


@dataclass
class Trip:
    departure: str
    arrival: str
    date: str
    time: str
    passengers: Passengers
    ktx_only: bool = False

    def search_params(self) -> dict:
        return {
            "dep": self.departure,
            "arr": self.arrival,
            "date": self.date,
            "time": self.time,
            "passengers": [AdultPassenger(self.passengers.total())],
            "include_no_seats": True,
            **({"train_type": TrainType.KTX} if self.ktx_only else {}),
        }

    def label(self) -> str:
        return f"{self.departure}~{self.arrival} {self.date} {self.time}"


@dataclass
class Watch:
    trip: Trip
    train_nos: List[str]
    seat_type: SeatType
    pay: bool = False
    watch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: Literal["running", "reserved", "stopped"] = "running"
    attempts: int = 0
    started_at: float = field(default_factory=time.time)
    last_error: Optional[str] = None
    reservation: Optional[ReservationInfo] = None
    stop: threading.Event = field(default_factory=threading.Event)

    def info(self) -> WatchInfo:
        return {
            "watch_id": self.watch_id,
            "status": self.status,
            "trip": self.trip.label(),
            "train_nos": self.train_nos,
            "attempts": self.attempts,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)),
            "last_error": self.last_error,
            "reservation": self.reservation,
        }


DEVICE_ID = os.environ.get("KORAIL_DEVICE_ID") or generate_device_id()


def _card() -> dict:
    return {key: os.environ.get(f"CARD_{key.upper()}") for key in CARD_KEYS}


def notify(msg: str) -> None:
    if not (webhook_url := os.environ.get("SLACK_WEBHOOK_URL")):
        return
    try:
        send_slack(msg, webhook_url)
    except Exception as ex:
        print(f"Slack notification failed: {ex}")


def _login() -> Korail:
    user_id = os.environ.get("KORAIL_ID")
    password = os.environ.get("KORAIL_PASSWORD")
    if not (user_id and password):
        raise ToolError("KORAIL_ID and KORAIL_PASSWORD are not set")

    rail = Korail(user_id, password, device_id=DEVICE_ID)
    if not rail.is_login:
        raise ToolError("Korail login failed")
    return rail


class RailSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rail: Optional[Korail] = None

    def call(self, fn: Callable[[Korail], T]) -> T:
        with self._lock:
            try:
                return self._call(fn)
            except KorailError as ex:
                raise ToolError(str(ex)) from ex

    def _call(self, fn: Callable[[Korail], T]) -> T:
        if self._rail is None or not self._rail.is_login:
            self._rail = _login()
        try:
            return fn(self._rail)
        except (NeedToLoginError, MacroError):
            self._rail = _login()
            return fn(self._rail)


def train_info(train) -> TrainInfo:
    return {
        "train_no": train.train_no,
        "train_type": train.train_type_name,
        "departure": train.dep_name,
        "arrival": train.arr_name,
        "date": train.dep_date,
        "departure_time": train.dep_time,
        "arrival_time": train.arr_time,
        "general_seat": train.has_general_seat(),
        "special_seat": train.has_special_seat(),
        "waiting_list": train.has_general_waiting_list(),
    }


def reservation_info(item) -> ReservationInfo:
    is_reservation = isinstance(item, Reservation)
    return {
        "reservation_id": item.rsv_id if is_reservation else item.pnr_no,
        "summary": str(item),
        "paid": not is_reservation or bool(getattr(item, "paid", False)),
        "waiting": is_reservation and item.is_waiting,
        "price": item.price,
        "payment_error": None,
    }


def checkout(rail: Korail, reservation: Reservation) -> ReservationInfo:
    info = reservation_info(reservation)
    if reservation.is_waiting:
        info["payment_error"] = "waiting list reservations cannot be paid"
        return info
    # Payment must never raise, or a reserved seat would look like a failed attempt and get reserved again.
    try:
        if pay_card(rail, reservation, _card()):
            info["paid"] = True
        else:
            info["payment_error"] = "CARD_* environment variables are not set"
    except Exception as ex:
        info["payment_error"] = str(ex)
    return info


def find_reservation(rail: Korail, reservation_id: str) -> Reservation:
    reservation = rail.reservations(reservation_id)
    if not isinstance(reservation, Reservation):
        raise ToolError(f"unknown reservation {reservation_id}")
    return reservation


def find_ticket(rail: Korail, ticket_id: str):
    if not (ticket := next((t for t in rail.tickets() or [] if t.pnr_no == ticket_id), None)):
        raise ToolError(f"unknown ticket {ticket_id}")
    return ticket


def _same_train(train, train_no: str) -> bool:
    return train.train_no.lstrip("0") == train_no.lstrip("0")


def search(rail: Korail, trip: Trip) -> list:
    try:
        return rail.search_train(**trip.search_params())
    except NoResultsError:
        return []


def reserve_available(rail: Korail, trip: Trip, train_nos: List[str], seat_type: SeatType):
    option = SEAT_OPTIONS[seat_type]
    for train in search(rail, trip):
        if any(_same_train(train, no) for no in train_nos) and _is_seat_available(train, option):
            return rail.reserve(train, passengers=trip.passengers.build(), option=option)
    return None


class Watcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watches: dict[str, Watch] = {}

    def start(self, watch: Watch) -> Watch:
        with self._lock:
            running = sum(w.status == "running" for w in self._watches.values())
            if running >= MAX_WATCHES:
                raise ToolError(f"at most {MAX_WATCHES} watches can run at once")
            self._watches[watch.watch_id] = watch
        threading.Thread(target=self._run, args=(watch,), daemon=True).start()
        return watch

    def get(self, watch_id: str) -> Watch:
        if not (watch := self._watches.get(watch_id)):
            raise ToolError(f"unknown watch {watch_id}")
        return watch

    def all(self) -> List[Watch]:
        return list(self._watches.values())

    def _run(self, watch: Watch) -> None:
        rail: Optional[Korail] = None
        while not watch.stop.is_set():
            delay = _interval()
            try:
                rail = rail or _login()
                watch.attempts += 1
                if reservation := reserve_available(rail, watch.trip, watch.train_nos, watch.seat_type):
                    watch.reservation = checkout(rail, reservation) if watch.pay else reservation_info(reservation)
                    watch.status = "reserved"
                    notify(_reserved_message(reservation, watch.reservation))
                    return
            except (NeedToLoginError, MacroError):
                rail = None
            except KorailError as ex:
                if not any(err in ex.msg for err in SKIPPABLE_ERRORS):
                    watch.last_error, rail, delay = str(ex), None, RESUME_DELAY
            except Exception as ex:
                watch.last_error, rail, delay = str(ex), None, RESUME_DELAY
            watch.stop.wait(delay)


def _reserved_message(reservation: Reservation, info: ReservationInfo) -> str:
    if info["paid"]:
        return f"{reservation}\n결제 완료"
    if info["payment_error"]:
        return f"{reservation}\n결제 실패: {info['payment_error']}"
    return f"{reservation}\n결제 기한 내 결제가 필요합니다"
