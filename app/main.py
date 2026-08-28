from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings, load_settings
from .content import ContentError, ContentService
from .database import Database
from .keyboards import review_keyboard
from .safety import find_safety_issue


logging.basicConfig(level=logging.INFO)
router = Router()
settings: Settings
db: Database
content: ContentService
bot: Bot


class EditDraft(StatesGroup):
    waiting_text = State()


def is_admin(user_id: int | None) -> bool:
    return user_id == settings.admin_user_id


def source_block(sources: list[dict[str, str]]) -> str:
    links = [f'<a href="{html.escape(s["url"], quote=True)}">{html.escape(s["name"])}</a>' for s in sources[:3]]
    return "\n\n🔎 Manbalar: " + " · ".join(links)


async def send_preview(draft_id: int) -> None:
    draft = await db.get(draft_id)
    if not draft:
        return
    caption = f"📝 <b>{html.escape(draft.title)}</b>\n\n{html.escape(draft.text)}"
    if len(caption) <= 1000:
        await bot.send_photo(
            settings.admin_user_id,
            BufferedInputFile(draft.image, filename=f"draft-{draft.id}.png"),
            caption=caption,
            reply_markup=review_keyboard(draft.id),
        )
    else:
        await bot.send_photo(settings.admin_user_id, BufferedInputFile(draft.image, filename=f"draft-{draft.id}.png"))
        await bot.send_message(settings.admin_user_id, caption, reply_markup=review_keyboard(draft.id))


async def create_draft(topic: str | None = None) -> None:
    await bot.send_message(settings.admin_user_id, "⏳ Yangi rasmli post tayyorlanyapti…")
    try:
        item = await content.generate(await db.recent_titles(), topic)
        draft_id = await db.create(item["title"], item["post"], item["image"], item["sources"])
        await send_preview(draft_id)
    except Exception as exc:
        logging.exception("Draft generation failed")
        await bot.send_message(settings.admin_user_id, f"⚠️ Post yaratilmadi: {html.escape(str(exc))}")


@router.message(Command("start", "help"))
async def start(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        "Med Maslahat AI muharriri ishga tayyor.\n\n"
        "/new — mavzuni AI tanlaydi\n"
        "/topic uyqu sifati — berilgan mavzuda post\n"
        "/queue — tasdiq kutayotgan postlar\n"
        "/id — Telegram ID ni ko‘rsatadi"
    )


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    await message.answer(f"Sizning Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("new"))
async def new_post(message: Message) -> None:
    if is_admin(message.from_user.id if message.from_user else None):
        asyncio.create_task(create_draft())


@router.message(Command("topic"))
async def topic_post(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    topic = message.text.partition(" ")[2].strip()
    if not topic:
        await message.answer("Masalan: <code>/topic yozda suvsizlanishdan saqlanish</code>")
        return
    asyncio.create_task(create_draft(topic))


@router.message(Command("queue"))
async def queue(message: Message) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    rows = await db.pending()
    text = "\n".join(f"#{row[0]} — {html.escape(row[1])}" for row in rows) or "Navbat bo‘sh."
    await message.answer(text)


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    draft_id = int(callback.data.split(":")[1])
    draft = await db.get(draft_id)
    if not draft or draft.status != "pending":
        await callback.answer("Bu post allaqachon ko‘rib chiqilgan.", show_alert=True)
        return
    final_text = html.escape(draft.text) + source_block(draft.sources)
    photo = BufferedInputFile(draft.image, filename=f"med-maslahat-{draft.id}.png")
    if len(final_text) <= 1000:
        await bot.send_photo(settings.channel_id, photo, caption=final_text)
    else:
        await bot.send_photo(settings.channel_id, photo)
        await bot.send_message(settings.channel_id, final_text, disable_web_page_preview=True)
    await db.mark(draft_id, "published")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Kanalga joylandi ✅", show_alert=True)


@router.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    draft_id = int(callback.data.split(":")[1])
    await db.mark(draft_id, "rejected")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Post rad etildi.")


@router.callback_query(F.data.startswith("regenerate:"))
async def regenerate(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    old_id = int(callback.data.split(":")[1])
    await db.mark(old_id, "rejected")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Yangi variant tayyorlanadi.")
    asyncio.create_task(create_draft())


@router.callback_query(F.data.startswith("edit:"))
async def edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    draft_id = int(callback.data.split(":")[1])
    await state.set_state(EditDraft.waiting_text)
    await state.update_data(draft_id=draft_id)
    await callback.answer()
    await callback.message.answer("Yangi matnni bitta xabar qilib yuboring. /cancel — bekor qilish.")


@router.message(EditDraft.waiting_text, Command("cancel"))
async def cancel_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Tahrirlash bekor qilindi.")


@router.message(EditDraft.waiting_text)
async def save_edit(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id if message.from_user else None) or not message.text:
        return
    issue = find_safety_issue(message.text)
    if issue:
        await message.answer(f"⚠️ Saqlanmadi: {html.escape(issue)}")
        return
    data = await state.get_data()
    await db.update_text(int(data["draft_id"]), message.text)
    await state.clear()
    await message.answer("Matn saqlandi. Yangilangan preview:")
    await send_preview(int(data["draft_id"]))


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))
    for index, value in enumerate(settings.daily_times):
        hour, minute = map(int, value.split(":"))
        scheduler.add_job(create_draft, "cron", hour=hour, minute=minute, id=f"daily-{index}", max_instances=1)
    return scheduler


async def main() -> None:
    global settings, db, content, bot
    settings = load_settings()
    db = Database(settings.database_path)
    await db.initialize()
    content = ContentService(settings.openai_api_key, settings.text_model, settings.image_model)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    scheduler = setup_scheduler()
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
