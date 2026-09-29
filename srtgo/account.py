from termcolor import colored

from .config import device_id, env
from .ktx import Korail


def login(debug=False):
    user_id, password = env("KORAIL_LOGIN_ID"), env("KORAIL_PASSWORD")
    if not (user_id and password):
        print(colored("KORAIL_LOGIN_ID와 KORAIL_PASSWORD를 설정해 주세요", "green", "on_red") + "\n")
        return None
    return Korail(user_id, password, verbose=debug, device_id=device_id())
