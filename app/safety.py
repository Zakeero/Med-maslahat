from __future__ import annotations


BLOCKED_PHRASES = (
    "100% davolaydi",
    "saratonni yo'q qiladi",
    "saraton tayoqchalarini",
    "jigarni tozalash",
    "toksinlarni chiqarib",
    "kasallikka barham beradi",
    "kariesni davolaydi",
    "shifokorsiz",
)


def find_safety_issue(text: str) -> str | None:
    normalized = " ".join(text.lower().split())
    for phrase in BLOCKED_PHRASES:
        if phrase in normalized:
            return f"Xavfli yoki isbotsiz ibora topildi: {phrase}"
    if "@med_maslahat" not in normalized:
        return "Kanal imzosi yo'q"
    return None

