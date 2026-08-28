from __future__ import annotations

import base64
import json
import re

from openai import AsyncOpenAI

from .prompts import EDITORIAL_PROMPT, WEEKLY_PLAN_PROMPT, topic_request
from .safety import find_safety_issue


class ContentError(RuntimeError):
    pass


class ContentService:
    def __init__(self, api_key: str, text_model: str, image_model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.text_model = text_model
        self.image_model = image_model

    async def generate(self, previous_titles: list[str], topic: str | None = None) -> dict:
        response = await self.client.responses.create(
            model=self.text_model,
            instructions=EDITORIAL_PROMPT,
            input=topic_request(previous_titles, topic),
            tools=[{"type": "web_search"}],
        )
        raw = response.output_text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContentError("Model JSON formatida javob bermadi") from exc

        for key in ("title", "post", "image_prompt", "sources"):
            if key not in data:
                raise ContentError(f"Javobda {key} maydoni yo'q")
        if len(data["sources"]) < 2:
            raise ContentError("Kamida 2 ta manba kerak")
        data["post"] = clean_post_text(data["post"])
        issue = find_safety_issue(data["post"])
        if issue:
            raise ContentError(issue)

        image_response = await self.client.images.generate(
            model=self.image_model,
            prompt=(
                data["image_prompt"]
                + ". Distinctive vibrant healthcare editorial illustration, bright coral, "
                  "turquoise, cobalt blue and warm yellow accents, strong focal subject, "
                  "modern premium composition, soft dimensional lighting, no words, "
                  "no letters, no watermark, no logo, square composition."
            ),
            size="1024x1024",
            quality="low",
        )
        image_b64 = image_response.data[0].b64_json
        if not image_b64:
            raise ContentError("Rasm yaratilmadi")
        data["image"] = base64.b64decode(image_b64)
        return data

    async def generate_weekly_plan(self) -> list[dict]:
        response = await self.client.responses.create(
            model=self.text_model,
            instructions="Siz o'zbek tilidagi tibbiy kontent strategisiz.",
            input=WEEKLY_PLAN_PROMPT,
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.output_text.strip(), flags=re.I)
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContentError("Haftalik reja JSON formatida emas") from exc
        if not isinstance(items, list) or len(items) != 14:
            raise ContentError("Haftalik reja aynan 14 ta mavzudan iborat bo'lishi kerak")
        for item in items:
            if not all(key in item for key in ("day", "time", "topic", "angle")):
                raise ContentError("Haftalik reja maydonlari to'liq emas")
        return items


def clean_post_text(text: str) -> str:
    """Remove web-search citation markup while preserving readable copy."""
    text = re.sub(r"\s*\(\[[^\]]+\]\(https?://[^)]+\)\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()
