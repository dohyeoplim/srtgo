from termcolor import colored


from .account import login
from .card import pay_card
from .slack import notify
from .ui import confirm, list_input, list_message


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

        choice = list_input(message=list_message("예매 내역"), choices=choices)

        if choice in (None, -1):
            return

        if choice == -2:
            out = []
            if all_reservations:
                out.append("[ 예매 내역 ]")
                for reservation in all_reservations:
                    out.append(f"🚅{reservation}")

            if out:
                notify("\n".join(out))
            return

        if (
            not all_reservations[choice].is_ticket
            and not all_reservations[choice].is_waiting
        ):
            answer = list_input(
                message=f"결제 대기 승차권: {all_reservations[choice]}",
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

        if confirm(
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
