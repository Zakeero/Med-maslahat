from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve:{draft_id}"),
         InlineKeyboardButton(text="♻️ Qayta yozish", callback_data=f"regenerate:{draft_id}")],
        [InlineKeyboardButton(text="✏️ Matnni tahrirlash", callback_data=f"edit:{draft_id}"),
         InlineKeyboardButton(text="🗑 Rad etish", callback_data=f"reject:{draft_id}")],
    ])

