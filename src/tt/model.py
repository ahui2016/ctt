import re
import arrow
from typing import Final, TypedDict
from result import Err, Ok, Result
from dataclasses import dataclass
from enum import Enum, auto
from random import randrange
import msgpack


OK: Final = Ok("OK")
# UnknownReturn: Final = Exception("Unknown-return")

DateFormat: Final = "YYYY-MM-DD"
TimeFormat: Final = "HH:mm:ss"

ConfigName: Final = "meta-config"

NameForbidPattern: Final = re.compile(r"[^_0-9a-zA-Z\-]")
"""只允许使用 -, _, 0-9, a-z, A-Z"""


def now() -> int:
    return arrow.now().int_timestamp


def date_id() -> str:
    """时间戳转base36"""
    return base_repr(now(), 36)


def rand_id() -> str:
    """只有 4 个字符的随机字符串"""
    n_min = int("1000", 36)
    n_max = int("zzzz", 36)
    n_rand = randrange(n_min, n_max + 1)
    return base_repr(n_rand, 36)


class AppConfig(TypedDict):
    """最基本的设定，比如语言、数据库文件的位置。"""

    lang: str  # 'cn' or 'en'
    db_path: str


class Config(TypedDict):
    split_min: int  # 单位：分钟，小于该值自动忽略
    pause_min: int  # 单位：分钟，小于该值自动忽略
    pause_max: int  # 单位：分钟，大于该值自动忽略


def default_cfg() -> Config:
    return Config(split_min=5, pause_min=5, pause_max=60)


def pack(obj) -> bytes:
    return msgpack.packb(obj)


def unpack(data: bytes):
    return msgpack.unpackb(data, use_list=False)


class MultiText(TypedDict):
    cn: str
    en: str


class EventStatus(Enum):
    Running = auto()
    Pausing = auto()
    Stopped = auto()


class LapName(Enum):
    Split = auto()
    Pause = auto()


Lap = tuple[str, int, int, int]
"""(name, start, end, length) : (LapName, timestamp, timestamp, seconds)"""


def check_name(name: str) -> Result[str, MultiText]:
    if NameForbidPattern.search(name) is None:
        return OK
    else:
        err = MultiText(
            cn="名称只允许由 0-9a-zA-Z 以及下划线、短横线组成",
            en="The name may only contain -, _, 0-9, a-z, A-Z",
        )
        return Err(err)


@dataclass
class Task:
    """请勿直接使用 Task(), 请使用 NewTask(dict)"""

    id: str  # rand_id
    name: str
    alias: str

    def __str__(self):
        if self.alias:
            return f"{self.name} ({self.alias})"
        return f"{self.name}"


def new_task(d: dict) -> Result[Task, MultiText]:
    t_id = d.get("id", rand_id())
    name = d["name"]
    alias = d.get("alias", "")
    task = Task(id=t_id, name=name, alias=alias)
    err = check_name(name).err()
    if err is None:
        return Ok(task)
    else:
        return Err(err)


@dataclass
class Event:
    id: str  # date_id
    task_id: str
    status: EventStatus  # 状态
    laps: tuple[Lap]  # 过程
    work: int  # 有效工作时间合计：秒

    def __init__(self, d: dict) -> None:
        self.id = d.get("id", date_id())
        self.task_id = d["task_id"]
        status = d.get("status", "Running")
        self.status = EventStatus[status]
        lap = (LapName.Split.name, now(), 0, 0)
        self.laps = unpack(d["laps"]) if d.get("laps", False) else (lap,)
        self.work = d.get("work", 0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "status": self.status.name,
            "laps": pack(self.laps),
            "work": 0,
        }


# https://github.com/numpy/numpy/blob/main/numpy/core/numeric.py
def base_repr(number: int, base: int = 10, padding: int = 0) -> str:
    """
    Return a string representation of a number in the given base system.
    """
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if base > len(digits):
        raise ValueError("Bases greater than 36 not handled in base_repr.")
    elif base < 2:
        raise ValueError("Bases less than 2 not handled in base_repr.")

    num = abs(number)
    res = []
    while num:
        res.append(digits[num % base])
        num //= base
    if padding:
        res.append("0" * padding)
    if number < 0:
        res.append("-")
    return "".join(reversed(res or "0"))
