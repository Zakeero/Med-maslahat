from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass
class Draft:
    id: int
    title: str
    text: str
    image: bytes
    sources: list[dict[str, str]]
    status: str


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image BLOB NOT NULL,
                    sources_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    telegram_message_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT
                )
            """)
            await db.commit()

    async def create(self, title: str, text: str, image: bytes, sources: list[dict[str, str]]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO drafts(title,text,image,sources_json) VALUES(?,?,?,?)",
                (title, text, image, json.dumps(sources, ensure_ascii=False)),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def get(self, draft_id: int) -> Draft | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,))).fetchone()
        if not row:
            return None
        return Draft(row["id"], row["title"], row["text"], row["image"], json.loads(row["sources_json"]), row["status"])

    async def recent_titles(self, limit: int = 20) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                "SELECT title FROM drafts ORDER BY id DESC LIMIT ?", (limit,)
            )).fetchall()
        return [row[0] for row in rows]

    async def update_text(self, draft_id: int, text: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE drafts SET text=? WHERE id=? AND status='pending'", (text, draft_id))
            await db.commit()

    async def mark(self, draft_id: int, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            published = ", published_at=CURRENT_TIMESTAMP" if status == "published" else ""
            await db.execute(f"UPDATE drafts SET status=?{published} WHERE id=?", (status, draft_id))
            await db.commit()

    async def pending(self) -> list[tuple[int, str]]:
        async with aiosqlite.connect(self.path) as db:
            return await (await db.execute(
                "SELECT id,title FROM drafts WHERE status='pending' ORDER BY id DESC LIMIT 20"
            )).fetchall()

