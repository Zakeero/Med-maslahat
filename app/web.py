from __future__ import annotations

import asyncio
import html
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile
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
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def minute_key(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


async def notify_admin(text: str) -> None:
    link = f"\n{settings.public_url}/dashboard" if settings.public_url else ""
    await bot.send_message(settings.admin_user_id, text + link)


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
    await db.create_scheduled_post(
        item["id"], item["scheduled_at"], generated["title"], generated["post"],
        generated["image"], generated["sources"],
    )
    await notify_admin("🔍 Bir soatdan keyin chiqadigan post tayyor. Web-panelda tekshirib tasdiqlang:")


async def publish_due_post() -> None:
    now = datetime.now(tz).replace(second=0, microsecond=0)
    post = await db.approved_post_due(minute_key(now))
    if not post:
        return
    await bot.send_photo(
        settings.channel_id,
        BufferedInputFile(post["image"], filename=f'med-maslahat-{post["id"]}.png'),
    )
    text = f'<b>{html.escape(post["title"])}</b>\n\n{html.escape(post["text"])}'
    await bot.send_message(settings.channel_id, text, parse_mode="HTML")
    await db.mark_scheduled_published(post["id"])


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.initialize()
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(create_weekly_plan, "cron", day_of_week="sun", hour=20, minute=0, id="weekly-plan")
    scheduler.add_job(prepare_upcoming_post, "cron", hour="9,13", minute=0, id="prepare-posts")
    scheduler.add_job(publish_due_post, "cron", hour="10,14", minute=0, id="publish-posts")
    scheduler.start()
    yield
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
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "plan": plan, "items": items, "posts": posts, "timezone": settings.timezone,
    })


@app.post("/plans/generate")
async def generate_plan(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    asyncio.create_task(create_weekly_plan())
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
async def post_image(request: Request, post_id: int):
    if not logged_in(request):
        return Response(status_code=401)
    image = await db.scheduled_post_image(post_id)
    return Response(image or b"", media_type="image/png")


@app.post("/posts/{post_id}/{action}")
async def review_post(request: Request, post_id: int, action: str):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    if action not in {"approve", "reject"}:
        return Response(status_code=400)
    await db.set_post_status(post_id, "approved" if action == "approve" else "rejected")
    return RedirectResponse("/dashboard", status_code=303)
