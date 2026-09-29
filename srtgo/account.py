import inquirer
import keyring

from .ktx import Korail, KorailError, generate_device_id
from .settings import RAIL_TYPE
from .ui import prompt


def set_login(debug=False):
    credentials = {
        "id": keyring.get_password(RAIL_TYPE, "id") or "",
        "pass": keyring.get_password(RAIL_TYPE, "pass") or "",
    }

    login_info = prompt(
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
    if not (device_id := keyring.get_password(RAIL_TYPE, "device_id")):
        device_id = generate_device_id()
        keyring.set_password(RAIL_TYPE, "device_id", device_id)
    return device_id
