"""Bot settings from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Keys of the fictional students. One shared prefix so that "this is demo" is
# decided by the key itself, not by a list someone forgets to extend.
DEMO_PREFIX = "demo-"


def _admin_ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _flag(raw: str) -> bool:
    """Only an explicit "no" counts as off.

    Forgetting the variable must be safe, so an empty value, a typo and any
    unknown word all mean the catch is on.
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
    # Sandbox: messages never reach real students. ON by default — released only
    # through the environment and a restart; there is deliberately no button.
    safe_mode: bool = True
    # Who else may be written to in the sandbox besides admins.
    sandbox_chat_ids: frozenset[int] = frozenset()
    # Directory of fictional students used to walk the screens.
    demo_root: Path = Path("demo")
    # Where grading reports live. Defaults to `data_root/out`; a separate field
    # so tests can substitute the synthetic stream without touching the directory
    # that holds the checker itself and the course materials.
    out_root: Path | None = None
    # Where the bot writes its own output: out/ is mounted read-only.
    export_dir: Path = Path("/state/export")
    # Notion. `repr=False` is mandatory: a frozen dataclass prints itself whole in
    # any traceback, and the token would reach the log on the first error.
    notion_token: str = field(default="", repr=False)
    notion_db: str = field(default="", repr=False)
    # GitHub: without a token 60 requests an hour — not enough for two hundred students.
    github_token: str = field(default="", repr=False)
    # Season 3 tracks; empty means the file shipped with the package.
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
        """Admin rights by id or by username.

        Username is a way to grant rights when the numeric id is not known in
        advance. It is weaker: a username can be released and then claimed by
        anyone. That is why the panel shows your id — move it into ADMIN_IDS.
        """
        if user_id in self.admin_ids:
            return True
        return bool(username) and username.lstrip("@").lower() in self.admin_usernames


def load(env: dict[str, str] | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    token = env.get("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set — get one from @BotFather")
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
