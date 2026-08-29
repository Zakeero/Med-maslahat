from __future__ import annotations

import asyncio
import html
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message, WebAppInfo,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .content import ContentService
from .database import Database


logging.basicConfig(level=logging.INFO)
settings = load_settings()
tz = ZoneInfo(settings.timezone)
db = Database(settings.database_path)
content = ContentService(settings.openai_api_key, settings.text_model, settings.image_model)
bot = Bot(settings.bot_token)
dispatcher = Dispatcher()
telegram_router = Router()
dispatcher.include_router(telegram_router)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def minute_key(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


async def notify_admin(text: str) -> None:
    link = f"\n{settings.public_url}/dashboard" if settings.public_url else ""
    try:
        await bot.send_message(settings.admin_user_id, text + link)
    except Exception:
        logging.exception("Admin notification failed")


async def create_weekly_plan() -> None:
    now = datetime.now(tz)
    days_ahead = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_ahead)).date()
    raw_items = await content.generate_weekly_plan()
    items = []
    for item in raw_items:
        hour, minute = map(int, item["time"].split(":"))
        scheduled = datetime.combine(
            monday + timedelta(days=int(item["day"])),
            datetime.min.time(),
            tzinfo=tz,
        ).replace(hour=hour, minute=minute)
        items.append({
            "scheduled_at": minute_key(scheduled),
            "topic": item["topic"].strip(),
            "angle": item["angle"].strip(),
        })
    await db.create_weekly_plan(monday.isoformat(), items)
    await notify_admin("📅 Kelgusi hafta uchun 14 ta mavzu rejasi tayyor. Web-panelda tekshirib tasdiqlang:")


async def prepare_upcoming_post() -> None:
    target = datetime.now(tz).replace(second=0, microsecond=0) + timedelta(hours=1)
    item = await db.item_due_for_preparation(minute_key(target))
    if not item:
        return
    generated = await content.generate(await db.recent_titles(), f'{item["topic"]}. Yondashuv: {item["angle"]}')
    post_id = await db.create_scheduled_post(
        item["id"], item["scheduled_at"], generated["title"], generated["post"],
        generated["image"], generated["sources"],
    )
    await send_post_review(post_id, "scheduled")


async def publish_content(post: dict) -> None:
    await bot.send_photo(
        settings.channel_id,
        BufferedInputFile(post["image"], filename=f'med-maslahat-{post["id"]}.png'),
    )
    text = f'<b>{html.escape(post["title"])}</b>\n\n{html.escape(post["text"])}'
    await bot.send_message(settings.channel_id, text, parse_mode="HTML")


async def publish_due_post() -> None:
    now = datetime.now(tz).replace(second=0, microsecond=0)
    post = await db.approved_post_due(minute_key(now))
    if not post:
        return
    await publish_content(post)
    await db.mark_scheduled_published(post["id"])


def panel_keyboard() -> InlineKeyboardMarkup | None:
    if not settings.public_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Web-panelni ochish", web_app=WebAppInfo(url=settings.public_url))
    ]])


def review_keyboard(post_id: int, kind: str) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"review:{kind}:approve:{post_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"review:{kind}:reject:{post_id}"),
    ]]
    if settings.public_url:
        rows.append([
            InlineKeyboardButton(
                text="✏️ Panelda ko‘rish",
                web_app=WebAppInfo(url=f"{settings.public_url}/dashboard"),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_post_review(post_id: int, kind: str) -> None:
    post = await (db.manual_post(post_id) if kind == "manual" else db.scheduled_post(post_id))
    if not post:
        return
    await bot.send_photo(
        settings.admin_user_id,
        BufferedInputFile(post["image"], filename=f"review-{kind}-{post_id}.png"),
    )
    timing = "Tasdiqlasangiz darhol chiqadi" if kind == "manual" else (
        f"Rejalashtirilgan vaqt: {post['scheduled_at'][0:10]} · {post['scheduled_at'][11:16]}"
    )
    review_text = (
        f"📝 <b>{html.escape(post['title'])}</b>\n\n"
        f"{html.escape(post['text'])}\n\n"
        f"🕒 {html.escape(timing)}"
    )
    await bot.send_message(
        settings.admin_user_id,
        review_text,
        parse_mode="HTML",
        reply_markup=review_keyboard(post_id, kind),
    )


def admin_message(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.admin_user_id)


async def create_manual_draft(topic: str) -> None:
    try:
        generated = await content.generate(await db.recent_titles(), topic)
        post_id = await db.create_manual_post(
            topic, generated["title"], generated["post"], generated["image"], generated["sources"]
        )
        await send_post_review(post_id, "manual")
    except Exception as exc:
        logging.exception("Manual post generation failed")
        await notify_admin(f"⚠️ Post yaratilmadi: {exc}")


@telegram_router.message(Command("start", "panel"))
async def telegram_start(message: Message) -> None:
    if not admin_message(message):
        return
    await message.answer(
        "Med Maslahat AI ishlayapti. Reja va postlarni web-panelda boshqaring.",
        reply_markup=panel_keyboard(),
    )


@telegram_router.message(Command("id"))
async def telegram_id(message: Message) -> None:
    await message.answer(f"Sizning Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


@telegram_router.message(Command("queue"))
async def telegram_queue(message: Message) -> None:
    if not admin_message(message):
        return
    count = await db.review_count()
    await message.answer(f"Tekshiruv va tasdiq kutayotgan postlar: {count} ta", reply_markup=panel_keyboard())


@telegram_router.message(Command("new"))
async def telegram_new(message: Message) -> None:
    if not admin_message(message):
        return
    await message.answer("⏳ Navbatdan tashqari post tayyorlanyapti…")
    asyncio.create_task(create_manual_draft("Mavzuni o'zingiz tanlang"))


@telegram_router.message(Command("topic"))
async def telegram_topic(message: Message) -> None:
    if not admin_message(message):
        return
    topic = (message.text or "").partition(" ")[2].strip()
    if not topic:
        await message.answer("Masalan: <code>/topic uyqu sifati</code>", parse_mode="HTML")
        return
    await message.answer(f"⏳ “{html.escape(topic)}” mavzusida post tayyorlanyapti…")
    asyncio.create_task(create_manual_draft(topic))


@telegram_router.callback_query(F.data.startswith("review:"))
async def telegram_review(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.admin_user_id or not callback.data:
        return
    _, kind, action, raw_id = callback.data.split(":", maxsplit=3)
    post_id = int(raw_id)
    if kind == "scheduled":
        await db.set_post_status(post_id, "approved" if action == "approve" else "rejected")
        result = "Tasdiqlandi — belgilangan vaqtda chiqadi ✅" if action == "approve" else "Post rad etildi."
    elif kind == "manual":
        if action == "approve":
            post = await db.manual_post(post_id)
            if post:
                await publish_content(post)
                await db.mark_manual_published(post_id)
            result = "Tasdiqlandi va kanalga chiqarildi ✅"
        else:
            await db.reject_manual_post(post_id)
            result = "Post rad etildi."
    else:
        await callback.answer("Noto‘g‘ri so‘rov", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(result, show_alert=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.initialize()
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(create_weekly_plan, "cron", day_of_week="sun", hour=20, minute=0, id="weekly-plan")
    scheduler.add_job(prepare_upcoming_post, "cron", hour="9,13", minute=0, id="prepare-posts")
    scheduler.add_job(publish_due_post, "cron", hour="10,14", minute=0, id="publish-posts")
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="new", description="Yangi post tayyorlash"),
        BotCommand(command="topic", description="Berilgan mavzuda post"),
        BotCommand(command="queue", description="Tasdiq kutayotgan postlar"),
        BotCommand(command="panel", description="Web-panelni ochish"),
        BotCommand(command="id", description="Telegram ID"),
    ])
    polling_task = asyncio.create_task(
        dispatcher.start_polling(bot, handle_signals=False, close_bot_session=False)
    )
    yield
    polling_task.cancel()
    scheduler.shutdown(wait=False)
    await bot.session.close()


app = FastAPI(title="Med Maslahat Kontent Paneli", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=True)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def logged_in(request: Request) -> bool:
    return request.session.get("admin") is True


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse("/dashboard" if logged_in(request) else "/login", status_code=303)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    if password != settings.admin_password:
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": "Parol noto‘g‘ri"}, status_code=401
        )
    request.session["admin"] = True
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    plan, items = await db.latest_plan()
    posts = await db.review_posts()
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "plan": plan, "items": items, "posts": posts, "timezone": settings.timezone,
        "flash": flash,
    })


@app.post("/plans/generate")
async def generate_plan(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    try:
        await create_weekly_plan()
        request.session["flash"] = {"kind": "success", "text": "14 mavzuli haftalik reja tayyor."}
    except Exception as exc:
        logging.exception("Weekly plan generation failed")
        request.session["flash"] = {"kind": "error", "text": f"Reja yaratilmadi: {exc}"}
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/plans/{plan_id}/approve")
async def approve_plan(request: Request, plan_id: int):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    await db.approve_plan(plan_id)
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/items/{item_id}/edit")
async def edit_item(request: Request, item_id: int, topic: str = Form(...), angle: str = Form(...)):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    await db.update_plan_item(item_id, topic.strip(), angle.strip())
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/posts/{post_id}/image")
async def post_image(request: Request, post_id: int, kind: str = "scheduled"):
    if not logged_in(request):
        return Response(status_code=401)
    image = await db.scheduled_post_image(post_id, kind)
    return Response(image or b"", media_type="image/png")


@app.post("/posts/{post_id}/{action}")
async def review_post(request: Request, post_id: int, action: str, kind: str = "scheduled"):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    if action not in {"approve", "reject"}:
        return Response(status_code=400)
    if kind == "manual":
        if action == "approve":
            post = await db.manual_post(post_id)
            if post:
                await publish_content(post)
                await db.mark_manual_published(post_id)
        else:
            await db.reject_manual_post(post_id)
    else:
        await db.set_post_status(post_id, "approved" if action == "approve" else "rejected")
    return RedirectResponse("/dashboard", status_code=303)
