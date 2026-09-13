"""Настройки бота из окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Ключи вымышленных студентов. Один общий префикс — чтобы «это демо»
# определялось по самому ключу, а не по списку, который забудут пополнить.
DEMO_PREFIX = "demo-"


def _admin_ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _flag(raw: str) -> bool:
    """Выключенным считается только явное «нет».

    Забыть переменную должно быть безопасно, поэтому пустое значение,
    опечатка и любое неизвестное слово означают «предохранитель включён».
    """
    return raw.strip().lower() not in {"0", "false", "no", "off", "нет"}


def _admin_usernames(raw: str) -> frozenset[str]:
    return frozenset(
        x.lstrip("@").lower() for x in raw.replace(" ", "").split(",") if x.strip("@")
    )


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]
    admin_usernames: frozenset[str]
    support_username: str
    data_root: Path
    db_path: Path
    # Песочница: сообщения настоящим студентам не уходят. По умолчанию ВКЛЮЧЕНА —
    # выключается только переменной окружения и перезапуском, кнопки в админке нет.
    safe_mode: bool = True
    # Кому в песочнице писать можно помимо администраторов.
    sandbox_chat_ids: frozenset[int] = frozenset()
    # Каталог вымышленных студентов для проверки экранов.
    demo_root: Path = Path("demo")
    # Где лежат отчёты проверки. По умолчанию — `data_root/out`; отдельным
    # полем, чтобы тесты могли подставить синтетический поток, не трогая
    # каталог, где лежат сам checker и материалы.
    out_root: Path | None = None
    # Куда бот пишет сам: out/ смонтирован только на чтение.
    export_dir: Path = Path("/state/export")
    # Notion. `repr=False` обязателен: frozen-датакласс печатает себя целиком
    # в любом трейсбеке, и токен уехал бы в лог при первой же ошибке.
    notion_token: str = field(default="", repr=False)
    notion_db: str = field(default="", repr=False)
    # GitHub: без токена 60 запросов в час — на поток в двести человек не хватит.
    github_token: str = field(default="", repr=False)
    # Направления третьего сезона; пусто — берём файл из пакета.
    tracks_path: Path | None = None

    @property
    def findings_dir(self) -> Path:
        return self.out_dir / "findings"

    @property
    def out_dir(self) -> Path:
        return self.out_root or self.data_root / "out"

    @property
    def checker_dir(self) -> Path:
        return self.data_root / "checker"

    @property
    def materials_dir(self) -> Path:
        return self.data_root / "materials"

    @property
    def notion_ready(self) -> bool:
        return bool(self.notion_token and self.notion_db)

    @property
    def support_url(self) -> str:
        return f"https://t.me/{self.support_username}"

    @property
    def demo_findings(self) -> Path:
        return self.demo_root / "findings"

    def is_admin(self, user_id: int, username: str | None = None) -> bool:
        """Права администратора по id либо по username.

        Username — способ выдать права тому, чей numeric id заранее неизвестен.
        Он слабее: username можно освободить, и тогда его займёт кто угодно.
        Поэтому админка показывает свой id — его стоит перенести в ADMIN_IDS.
        """
        if user_id in self.admin_ids:
            return True
        return bool(username) and username.lstrip("@").lower() in self.admin_usernames


def load(env: dict[str, str] | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    token = env.get("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("не задан BOT_TOKEN — возьмите его у @BotFather")
    root = Path(env.get("DATA_ROOT", ".")).resolve()
    return Config(
        token=token,
        admin_ids=_admin_ids(env.get("ADMIN_IDS", "")),
        admin_usernames=_admin_usernames(env.get("ADMIN_USERNAMES", "")),
        support_username=env.get("SUPPORT_USERNAME", "").lstrip("@").strip(),
        data_root=root,
        db_path=Path(env.get("DB_PATH", root / "bot" / "mlbot.sqlite3")),
        safe_mode=_flag(env.get("SAFE_MODE", "1")),
        sandbox_chat_ids=_admin_ids(env.get("SANDBOX_CHAT_IDS", "")),
        demo_root=Path(env.get("DEMO_ROOT", Path(__file__).resolve().parents[2] / "demo")),
        out_root=Path(env["OUT_DIR"]) if env.get("OUT_DIR") else None,
        export_dir=Path(env.get("EXPORT_DIR", "/state/export")),
        notion_token=env.get("NOTION_TOKEN", "").strip(),
        notion_db=env.get("NOTION_DB", "").strip(),
        github_token=env.get("GITHUB_TOKEN", "").strip(),
        tracks_path=Path(env["TRACKS_PATH"]) if env.get("TRACKS_PATH") else None,
    )
