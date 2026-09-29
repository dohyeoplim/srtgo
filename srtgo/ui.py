from functools import cache

import inquirer
from inquirer.render.console import ConsoleRender


ELLIPSIS = "..."
HEADER_MARK_WIDTH = len("[?] ")
VALUE_SEPARATOR = ": "

LIST_KEYS = "Enter: 선택, Ctrl-C: 취소"
CHECKBOX_KEYS = "Space: 선택, Ctrl-A: 전체, Ctrl-R: 해제, Enter: 완료"


def list_message(title):
    return f"{title} ({LIST_KEYS})"


def checkbox_message(title):
    return f"{title} ({CHECKBOX_KEYS})"


def strip_keys(message):
    for keys in (LIST_KEYS, CHECKBOX_KEYS):
        message = message.removesuffix(f" ({keys})")
    return message


def answer_label(render):
    choices = render.question.choices
    if hasattr(render, "selection"):
        return ", ".join(str(choices[i]) for i in sorted(render.selection)) or "선택 없음"
    return str(choices[render.current])


def fit_end(term, text, width):
    if term.length(text) <= width:
        return text
    return term.truncate(text, max(width - len(ELLIPSIS), 0)) + term.normal + ELLIPSIS


def fit_start(term, text, width):
    if term.length(text) <= width:
        return text
    while text and term.length(text) > width - len(ELLIPSIS):
        text = text[1:]
    return ELLIPSIS + text


class FittedRender(ConsoleRender):
    def render(self, question, answers=None):
        try:
            return super().render(question, answers)
        finally:
            self._position = 0

    def _print_header(self, render):
        term = self.terminal
        theme = self._theme.Question
        room = self.width - 1 - HEADER_MARK_WIDTH - len(VALUE_SEPARATOR)

        header = render.get_header()
        value = str(render.get_current_value())
        move_left = term.move_left or ""
        cursor_offset = value.count(move_left) if move_left else 0
        plain_value = value.replace(move_left, "") if move_left else value

        value_width = term.length(plain_value)
        header_room = max(room - value_width, min(term.length(header), room // 2))
        header = fit_end(term, header, header_room)
        plain_value = fit_start(term, plain_value, room - term.length(header))
        value = plain_value + move_left * min(cursor_offset, len(plain_value))

        self.print_str(
            "\n{t.move_up}{t.clear_eol}{tq.brackets_color}[{tq.mark_color}?{tq.brackets_color}]{t.normal} "
            "{msg}{t.normal}" + VALUE_SEPARATOR + "{value}",
            msg=header,
            value=value,
            lf=not render.title_inline,
            tq=theme,
        )

    def _go_to_end(self, render):
        if render.title_inline:
            return super()._go_to_end(render)

        term = self.terminal
        print(term.move_up * self._position + "\r" + term.clear_eos, end="")
        self._position = 0

        room = self.width - 1 - HEADER_MARK_WIDTH - len(VALUE_SEPARATOR)
        title = fit_end(term, strip_keys(render.get_header()), room // 2)
        answer = fit_end(term, answer_label(render), room - term.length(title))
        self.print_str(
            "{tq.brackets_color}[{tq.mark_color}?{tq.brackets_color}]{t.normal} "
            "{msg}" + VALUE_SEPARATOR + "{color}{value}{t.normal}",
            msg=title,
            value=answer,
            color=self._theme.List.selection_color,
            tq=self._theme.Question,
        )

    def _print_options(self, render):
        term = self.terminal
        for message, symbol, color in render.get_options():
            room = self.width - 1 - term.length(f" {symbol} ")
            self.print_line(
                " {color}{s} {m}{t.normal}",
                m=fit_end(term, str(message), room),
                color=color,
                s=symbol,
            )


def status(text):
    print(f"\r{text}\x1b[K", end="", flush=True)


@cache
def _console():
    return FittedRender()


def _cancellable(ask):
    try:
        return ask()
    except KeyboardInterrupt:
        print()
        return None


def prompt(questions):
    return _cancellable(lambda: inquirer.prompt(questions, render=_console(), raise_keyboard_interrupt=True))


def list_input(message, **kwargs):
    return _cancellable(lambda: inquirer.list_input(message, render=_console(), **kwargs))


def confirm(message, **kwargs):
    return _cancellable(lambda: inquirer.confirm(message, render=_console(), **kwargs))
