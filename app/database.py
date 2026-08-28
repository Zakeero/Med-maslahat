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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS weekly_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_start TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    approved_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS plan_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    scheduled_at TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    angle TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    FOREIGN KEY(plan_id) REFERENCES weekly_plans(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_item_id INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image BLOB NOT NULL,
                    sources_json TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'review',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT,
                    FOREIGN KEY(plan_item_id) REFERENCES plan_items(id)
                )
            """)
            await db.commit()

    async def create_weekly_plan(self, week_start: str, items: list[dict[str, str]]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO weekly_plans(week_start) VALUES(?)", (week_start,)
            )
            if not cursor.lastrowid:
                row = await (await db.execute(
                    "SELECT id FROM weekly_plans WHERE week_start=?", (week_start,)
                )).fetchone()
                return int(row[0])
            plan_id = int(cursor.lastrowid)
            await db.executemany(
                "INSERT INTO plan_items(plan_id,scheduled_at,topic,angle) VALUES(?,?,?,?)",
                [(plan_id, item["scheduled_at"], item["topic"], item["angle"]) for item in items],
            )
            await db.commit()
            return plan_id

    async def latest_plan(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            plan = await (await db.execute(
                "SELECT * FROM weekly_plans ORDER BY week_start DESC LIMIT 1"
            )).fetchone()
            if not plan:
                return None, []
            items = await (await db.execute(
                "SELECT * FROM plan_items WHERE plan_id=? ORDER BY scheduled_at", (plan["id"],)
            )).fetchall()
            return dict(plan), [dict(row) for row in items]

    async def approve_plan(self, plan_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE weekly_plans SET status='approved',approved_at=CURRENT_TIMESTAMP WHERE id=?",
                (plan_id,),
            )
            await db.commit()

    async def update_plan_item(self, item_id: int, topic: str, angle: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE plan_items SET topic=?,angle=? WHERE id=?", (topic, angle, item_id)
            )
            await db.commit()

    async def item_due_for_preparation(self, scheduled_at: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("""
                SELECT pi.* FROM plan_items pi
                JOIN weekly_plans wp ON wp.id=pi.plan_id
                LEFT JOIN scheduled_posts sp ON sp.plan_item_id=pi.id
                WHERE wp.status='approved' AND pi.scheduled_at=? AND sp.id IS NULL
            """, (scheduled_at,))).fetchone()
            return dict(row) if row else None

    async def create_scheduled_post(self, item_id: int, scheduled_at: str, title: str,
                                    text: str, image: bytes, sources: list[dict[str, str]]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                INSERT INTO scheduled_posts(plan_item_id,title,text,image,sources_json,scheduled_at)
                VALUES(?,?,?,?,?,?)
            """, (item_id, title, text, image, json.dumps(sources, ensure_ascii=False), scheduled_at))
            await db.execute("UPDATE plan_items SET status='prepared' WHERE id=?", (item_id,))
            await db.commit()
            return int(cursor.lastrowid)

    async def review_posts(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("""
                SELECT sp.*,pi.topic,pi.angle FROM scheduled_posts sp
                JOIN plan_items pi ON pi.id=sp.plan_item_id
                WHERE sp.status IN ('review','approved') ORDER BY sp.scheduled_at
            """)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["sources"] = json.loads(item.pop("sources_json"))
                item.pop("image", None)
                result.append(item)
            return result

    async def scheduled_post_image(self, post_id: int) -> bytes | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT image FROM scheduled_posts WHERE id=?", (post_id,)
            )).fetchone()
            return row[0] if row else None

    async def set_post_status(self, post_id: int, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE scheduled_posts SET status=? WHERE id=?", (status, post_id))
            await db.commit()

    async def approved_post_due(self, scheduled_at: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM scheduled_posts WHERE scheduled_at=? AND status='approved'", (scheduled_at,)
            )).fetchone()
            if not row:
                return None
            item = dict(row)
            item["sources"] = json.loads(item.pop("sources_json"))
            return item

    async def mark_scheduled_published(self, post_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE scheduled_posts SET status='published',published_at=CURRENT_TIMESTAMP WHERE id=?",
                (post_id,),
            )
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
