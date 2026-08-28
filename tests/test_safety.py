from app.safety import find_safety_issue
from app.content import clean_post_text


def test_safe_post():
    assert find_safety_issue("Suv ehtiyoji odamga qarab farq qiladi. @Med_Maslahat") is None


def test_blocks_cure_claim():
    assert find_safety_issue("Bu usul saratonni yo'q qiladi. @Med_Maslahat") is not None


def test_requires_signature():
    assert find_safety_issue("Sog'lom uyqu muhim.") == "Kanal imzosi yo'q"


def test_removes_inline_citations():
    text = "Uyqu muhim. ([cdc.gov](https://cdc.gov/sleep/index.html))\n@Med_Maslahat"
    assert clean_post_text(text) == "Uyqu muhim.\n@Med_Maslahat"
