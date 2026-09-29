import secrets
from typing import Annotated, List, Optional

import click
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from srtgo.config import load_env
from srtgo.ktx import Korail

from .rail import (
    Date,
    Passengers,
    RailSession,
    ReservationInfo,
    SeatType,
    Time,
    TrainInfo,
    Trip,
    Watch,
    WatchInfo,
    Watcher,
    checkout,
    find_reservation,
    find_ticket,
    reservation_info,
    reserve_available,
    search,
    train_info,
)


session = RailSession()
watcher = Watcher()

mcp = MCPServer(
    "srtgo",
    instructions=(
        "Korail train reservation tools. Station names are Korean, such as 서울 or 부산. "
        "Unpaid reservations expire at their payment deadline. Payment uses the configured card."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)


@mcp.tool(description="Search trains between two stations.", annotations=READ_ONLY)
def search_trains(
    departure: str,
    arrival: str,
    date: Date,
    time: Time = "000000",
    passengers: Optional[Passengers] = None,
    ktx_only: bool = False,
) -> List[TrainInfo]:
    trip = Trip(departure, arrival, date, time, passengers or Passengers(), ktx_only)
    return [train_info(train) for train in session.call(lambda rail: search(rail, trip))]


@mcp.tool(
    description="Reserve one train once if a seat or waiting list is available. Pays with the card when pay is true.",
    annotations=DESTRUCTIVE,
)
def reserve_train(
    departure: str,
    arrival: str,
    date: Date,
    train_no: str,
    time: Time = "000000",
    seat_type: SeatType = "general_first",
    passengers: Optional[Passengers] = None,
    pay: bool = False,
) -> ReservationInfo:
    trip = Trip(departure, arrival, date, time, passengers or Passengers())

    def reserve(rail: Korail) -> ReservationInfo:
        if not (reservation := reserve_available(rail, trip, [train_no], seat_type)):
            raise ToolError(f"no available seat on train {train_no}")
        return checkout(rail, reservation) if pay else reservation_info(reservation)

    return session.call(reserve)


@mcp.tool(
    description=(
        "Keep retrying in the background until one of the trains is reserved. "
        "Pays with the card when pay is true. Sends a Slack alert on success."
    ),
    annotations=DESTRUCTIVE,
)
def start_watch(
    departure: str,
    arrival: str,
    date: Date,
    train_nos: Annotated[List[str], Field(min_length=1)],
    time: Time = "000000",
    seat_type: SeatType = "general_first",
    passengers: Optional[Passengers] = None,
    pay: bool = False,
) -> WatchInfo:
    trip = Trip(departure, arrival, date, time, passengers or Passengers())
    return watcher.start(Watch(trip, train_nos, seat_type, pay)).info()


@mcp.tool(description="List background reservation watches.", annotations=READ_ONLY)
def list_watches() -> List[WatchInfo]:
    return [watch.info() for watch in watcher.all()]


@mcp.tool(description="Stop a background reservation watch.", annotations=WRITE)
def stop_watch(watch_id: str) -> WatchInfo:
    watch = watcher.get(watch_id)
    if watch.status == "running":
        watch.stop.set()
        watch.status = "stopped"
    return watch.info()


@mcp.tool(description="List reservations and paid tickets.", annotations=READ_ONLY)
def list_reservations() -> List[ReservationInfo]:
    def fetch(rail: Korail) -> list:
        return [*(rail.tickets() or []), *(rail.reservations() or [])]

    return [reservation_info(item) for item in session.call(fetch)]


@mcp.tool(description="Pay an unpaid reservation with the configured card.", annotations=DESTRUCTIVE)
def pay_reservation(reservation_id: str) -> ReservationInfo:
    def pay(rail: Korail) -> ReservationInfo:
        info = checkout(rail, find_reservation(rail, reservation_id))
        if info["payment_error"]:
            raise ToolError(info["payment_error"])
        return info

    return session.call(pay)


@mcp.tool(description="Cancel an unpaid reservation.", annotations=DESTRUCTIVE)
def cancel_reservation(reservation_id: str) -> ReservationInfo:
    def cancel(rail: Korail) -> ReservationInfo:
        reservation = find_reservation(rail, reservation_id)
        rail.cancel(reservation)
        return reservation_info(reservation)

    return session.call(cancel)


@mcp.tool(description="Refund a paid ticket.", annotations=DESTRUCTIVE)
def refund_ticket(ticket_id: str) -> ReservationInfo:
    def refund(rail: Korail) -> ReservationInfo:
        ticket = find_ticket(rail, ticket_id)
        rail.refund(ticket)
        return reservation_info(ticket)

    return session.call(refund)


class BearerAuth:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization", b"")
            if not secrets.compare_digest(header, self.expected):
                await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


@click.command()
@click.option("--transport", type=click.Choice(["stdio", "http"]), default="stdio", envvar="MCP_TRANSPORT")
@click.option("--host", default="127.0.0.1", envvar="MCP_HOST")
@click.option("--port", type=int, default=8000, envvar="MCP_PORT")
@click.option("--token", envvar="MCP_AUTH_TOKEN", help="Bearer token required for HTTP")
def serve(transport: str, host: str, port: int, token: Optional[str]) -> None:
    if transport == "stdio":
        mcp.run()
        return

    if not token:
        raise click.UsageError("MCP_AUTH_TOKEN is required for HTTP transport")
    uvicorn.run(BearerAuth(mcp.streamable_http_app(host=host), token), host=host, port=port)


def main() -> None:
    load_env()
    serve()


if __name__ == "__main__":
    main()
