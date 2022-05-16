import sqlite3
from datetime import timedelta
from typing import TypeAlias, Callable
import arrow
from result import Result, Err, Ok

from . import db, model
from .model import (
    Config,
    AppConfig,
    Task,
    MultiText,
    Event,
    EventStatus,
    OK,
    UnknownReturn,
)

Conn: TypeAlias = sqlite3.Connection


def show_cfg_cn(app_cfg: AppConfig, cfg: Config):
    print()
    print(f"         语言: {app_cfg['lang']}")
    print(f"   数据库文件: {app_cfg['db_path']}")
    print(f" 工作时间下限: {cfg['split_min']} 分钟")
    print(f" 休息时间下限: {cfg['pause_min']} 分钟")
    print(f" 休息时间上限: {cfg['pause_max']} 分钟")
    print()
    print("* 使用命令 'tt help min' 或 'tt help max' 可查看关于时间上下限的说明。\n")


def show_cfg_en(app_cfg: AppConfig, cfg: Config):
    print(f"  [language] {app_cfg['lang']}")
    print(f"  [database] {app_cfg['db_path']}")
    print(f" [split min] {cfg['split_min']} minutes")
    print(f" [pause min] {cfg['pause_min']} minutes")
    print(f" [pause max] {cfg['pause_max']} minutes")
    print()
    print(
        "* Try 'tt help min' or 'tt help max' to read more about time limits."
        "\n"
    )


def show_cfg(conn: Conn, app_cfg: AppConfig, cfg: Config | None = None):
    if not cfg:
        cfg = db.get_cfg(conn).unwrap()

    if app_cfg["lang"] == "cn":
        show_cfg_cn(app_cfg, cfg)
    else:
        show_cfg_en(app_cfg, cfg)


def show_tasks(tasks: list[Task], lang: str) -> None:
    no_task = MultiText(
        cn="尚未添加任何任务类型，可使用 'tt add NAME' 添加任务类型。",
        en="There is no any task type. Use 'tt add NAME' to add a task.",
    )
    header = MultiText(cn="\n[任务类型列表]\n", en="\n[Task types]\n")
    if not tasks:
        print(no_task[lang])  # type: ignore
        return

    print(header[lang])  # type: ignore
    for task in tasks:
        print(f"* {task}")
    print()


def check_last_event_stopped(conn: Conn) -> Result[str, MultiText]:
    """确保上一个事件已结束。"""
    r = db.get_last_event(conn)
    if r.is_err():
        return OK  # 唯一的错误是数据库中无事件

    event = r.unwrap()
    if event.status is not EventStatus.Stopped:
        err = MultiText(
            cn="不可启动新事件，因为上一个事件未结束 (可使用 'tt status' 查看状态)",
            en="Cannot make a new event. Try 'tt status' to get more information.",
        )
        return Err(err)

    return OK


def format_date(t: int) -> str:
    return arrow.get(t).format("YYYY-MM-DD")


def format_time(t: int) -> str:
    return arrow.get(t).format("HH:mm:ss")


def format_time_len(s: int) -> str:
    return str(timedelta(s))


def event_start(conn: Conn, name: str) -> MultiText:
    err = check_last_event_stopped(conn).err()
    if err is not None:
        return err

    r = db.get_task_by_name(conn, name)
    if r.is_err():
        return MultiText(
            cn=f"不存在任务类型: {name}, 可使用 'tt add {name}' 添加此任务类型。",
            en=f"Not Found: {name}. Try 'tt add {name}' to add it as a task type.",
        )

    task = r.unwrap()
    event = Event({"task_id": task.id})
    db.insert_event(conn, event)
    started = format_time(event.started)

    if task.alias:
        return MultiText(
            cn=f"事件: {event.id}, 任务: {task.name} ({task.alias}), 开始: {started}",
            en=f"Event: {event.id}, Task: {task.name} ({task.alias}), Started from {started}",
        )
    else:
        return MultiText(
            cn=f"事件: {event.id}, 任务: {task.name}, 开始: {started}",
            en=f"Event: {event.id}, Task: {task.name}, Started from {started}",
        )


def get_last_event(conn: Conn) -> Result[Event, MultiText]:
    match db.get_last_event(conn):
        case Err(err):
            return Err(err)
        case Ok(event):
            if event.status is EventStatus.Stopped:
                err = MultiText(
                    cn="当前无正在计时的事件，可使用 'tt start TASK' 启动一个事件。",
                    en="No running event. Try 'tt start Task' to make an event.",
                )
                return Err(err)
            else:
                return Ok(event)
        case _:
            raise UnknownReturn


def event_split(conn: Conn, cfg: Config, lang: str) -> None:
    r = get_last_event(conn)
    if r.is_err():
        print(r.err()[lang])  # type: ignore
        return

    event: Event = r.unwrap()
    event.split(cfg)
    db.update_laps(conn, event)
    show_status(conn, lang)


def event_stop(conn: Conn, cfg: Config, lang: str) -> None:
    r = get_last_event(conn)
    if r.is_err():
        print(r.err()[lang])  # type: ignore
        return

    event: Event = r.unwrap()
    event.stop(cfg)
    db.update_laps(conn, event)

    if event.work <= cfg["split_min"]:
        info = MultiText(
            cn="以下所示事件，由于总工作时长小于下限，已自动删除。\n"
            + "可使用命令 'tt help min' 查看关于时长下限的说明。\n",
            en="The event below is automatically deleted.\n"
            + "Run 'tt help min' to get more information.\n",
        )
        print(info[lang])  # type: ignore
        show_running_status(conn, event, None, lang)
        db.delete_event(conn, event.id)
    else:
        show_running_status(conn, event, None, lang)


def show_stopped_status(lang: str) -> None:
    info = MultiText(
        cn="当前无正在计时的任务，可使用 'tt list -e' 查看最近的事件。",
        en="No event running. Try 'tt list -e' to list out recent events.",
    )
    print(info[lang])  # type: ignore


def show_running_status(
    conn: Conn, event: Event, task: Task | None, lang: str
) -> None:
    if task is None:
        task = db.get_task_by_id(conn, event.task_id).unwrap()
    date = format_date(event.started)
    status = f"(id:{event.id}) {date} **{event.status.name.lower()}**"
    start = format_time(event.started)
    now = format_time(model.now())
    work = format_time_len(event.work)

    header = MultiText(
        cn=f"任务 | {task}\n事件 | {status}", en=f"Task | {task}\nEvent| {status}"
    )
    total = MultiText(
        cn=f"合计  {start} -> {now} [{work}]",
        en=f"total  {start} -> {now} [{work}]",
    )
    print(f"{header[lang]}\n\n{total[lang]}\n--------------------------------------")  # type: ignore

    for lap in event.laps:
        print(
            f"{lap[0]}  {format_time(lap[1])} -> {format_time(lap[2])} [{format_time_len(lap[3])}]"
        )

    footer_running = MultiText(
        cn="可接受命令: pause/split/stop", en="Waiting for pause/split/stop"
    )
    footer_pausing = MultiText(
        cn="可接受命令: resume/stop", en="Waiting for resume/stop"
    )
    footer_stopped = MultiText(
        cn="该事件已结束。", en="The event above has stopped."
    )
    match event.status:
        case EventStatus.Running:
            print(footer_running[lang])  # type: ignore
        case EventStatus.Pausing:
            print(footer_pausing[lang])  # type: ignore
        case EventStatus.Stopped:
            print(footer_stopped[lang])  # type: ignore
    print()


def show_status(conn: Conn, lang: str) -> None:
    match db.get_last_event(conn):
        case Err(err):
            print(err[lang])  # type: ignore
        case Ok(event):
            task = db.get_task_by_id(conn, event.task_id).unwrap()
            if event.status is EventStatus.Stopped:
                show_stopped_status(lang)
            else:
                show_running_status(conn, event, task, lang)
