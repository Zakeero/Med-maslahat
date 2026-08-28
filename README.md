# Med Maslahat AI agent

`@Med_Maslahat` uchun rasmli post tayyorlaydigan va faqat admin tasdig‘idan
keyin kanalga chiqaradigan Telegram bot.

## Nimalar ishlaydi?

- Har kuni `10:00` va `14:00` da yangi draft yaratish
- Ishonchli tibbiy manbalarni web orqali qidirish
- Rasm yaratish va shaxsiy botga preview yuborish
- Tasdiqlash, rad etish, qayta yozish va matnni qo‘lda tahrirlash
- Takroriy mavzularni kamaytirish va draftlar tarixini saqlash
- Xavfli mutlaq tibbiy da’volarni avtomatik bloklash

## 1. Telegram bot yaratish

1. Telegram’da `@BotFather`ni oching.
2. `/newbot` buyrug‘ini yuboring va bot nomini tanlang.
3. Berilgan tokenni saqlang. Uni hech kimga yubormang.
4. Telegram’da `@userinfobot` orqali raqamli ID’ingizni oling va uni
   `ADMIN_USER_ID`ga kiriting. Ishga tushgach yangi botning `/id` buyrug‘i ham
   shu ID’ni ko‘rsatadi.
5. Botni `@Med_Maslahat` kanaliga administrator qilib qo‘shing va unga
   `Post Messages` huquqini bering.

Telegram Bot API kanalga username orqali post yuborishni va inline tugmalarni
qo‘llab-quvvatlaydi: https://core.telegram.org/bots/api

## 2. OpenAI kaliti

1. https://platform.openai.com/api-keys sahifasida API kalit yarating.
2. Billing uchun oylik limitni `$20` qilib belgilang.
3. Kalitni faqat hostingdagi `OPENAI_API_KEY` o‘zgaruvchisiga kiriting.

Agent eski Assistants API emas, amaldagi Responses API’dan foydalanadi.

## 3. Lokal ishga tushirish

Python 3.11+ kerak.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` ichiga tokenlar va Telegram ID’ni kiriting, so‘ng:

```bash
python -m app.main
```

## 4. Railway’da doimiy ishlatish

1. Loyihani GitHub repozitoriysiga yuklang.
2. Railway’da `New Project → Deploy from GitHub Repo`ni tanlang.
3. `Variables` bo‘limiga `.env.example`dagi o‘zgaruvchilarni kiriting.
4. `DATABASE_PATH=/data/agent.db` belgilang.
5. Railway Volume yarating va `/data` manziliga ulang.
6. Deploy qiling. `Procfile` worker’ni avtomatik ishga tushiradi.

## Bot buyruqlari

- `/new` — mavzuni AI tanlaydi
- `/topic mavzu` — siz bergan mavzuda post yaratadi
- `/queue` — tasdiq kutayotgan postlar
- `/id` — Telegram user ID
- `/help` — yordam

## Muhim cheklov

Bu agent shifokorni almashtirmaydi. Har bir post inson tasdig‘idan o‘tadi.
Kanal shifokor yoki malakali tibbiy muharrir bilan hamkorlik qilsa, klinik
tekshiruv sifati ancha oshadi.
