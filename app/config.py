from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    openai_api_key: str
    admin_user_id: int
    channel_id: str
    timezone: str
    daily_times: tuple[str, ...]
    text_model: str
    image_model: str
    database_path: Path
    admin_password: str
    session_secret: str
    public_url: str


def load_settings() -> Settings:
    required = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "").strip(),
        "ADMIN_USER_ID": os.getenv("ADMIN_USER_ID", "").strip(),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD", "").strip(),
        "SESSION_SECRET": os.getenv("SESSION_SECRET", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError("Yetishmayotgan sozlamalar: " + ", ".join(missing))

    times = tuple(
        item.strip() for item in os.getenv("DAILY_TIMES", "10:00,14:00").split(",")
        if item.strip()
    )
    for item in times:
        hour, minute = item.split(":", maxsplit=1)
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise RuntimeError(f"Noto'g'ri vaqt: {item}")

    db_path = Path(os.getenv("DATABASE_PATH", "data/agent.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=required["TELEGRAM_BOT_TOKEN"],
        openai_api_key=required["OPENAI_API_KEY"],
        admin_user_id=int(required["ADMIN_USER_ID"]),
        channel_id=os.getenv("CHANNEL_ID", "@Med_Maslahat").strip(),
        timezone=os.getenv("TIMEZONE", "Asia/Tashkent").strip(),
        daily_times=times,
        text_model=os.getenv("TEXT_MODEL", "gpt-5-mini").strip(),
        image_model=os.getenv("IMAGE_MODEL", "gpt-image-1-mini").strip(),
        database_path=db_path,
        admin_password=required["ADMIN_PASSWORD"],
        session_secret=required["SESSION_SECRET"],
        public_url=os.getenv("PUBLIC_URL", "").strip().rstrip("/"),
    )
