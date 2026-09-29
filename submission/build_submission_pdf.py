"""Prepend the case-required technical access sheet to the product deck.

The public submission contains no credentials. The hosted showcase needs only
a MAX account; the local Docker default intentionally uses simulated MAX.
"""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "submission" / "DomPuls_MAX_hackathon_v2.pdf"
OUTPUT = ROOT / "output" / "pdf" / "DomPuls_MAX_hackathon_submission.pdf"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def build_access_page() -> BytesIO:
    pdfmetrics.registerFont(TTFont("ArialRU", FONT))
    pdfmetrics.registerFont(TTFont("ArialRUBold", FONT_BOLD))
    source = PdfReader(SOURCE)
    width = float(source.pages[0].mediabox.width)
    height = float(source.pages[0].mediabox.height)
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=(width, height))
    dark, muted, accent = HexColor("#17212b"), HexColor("#5e6a74"), HexColor("#348fb6")

    def line(label: str, value: str, y: float, *, link: str | None = None) -> float:
        page.setFont("ArialRUBold", 11)
        page.setFillColor(muted)
        page.drawString(52, y, label)
        page.setFont("ArialRU", 13)
        page.setFillColor(accent if link else dark)
        page.drawString(232, y, value)
        if link:
            page.linkURL(link, (230, y - 3, min(width - 45, 232 + pdfmetrics.stringWidth(value, "ArialRU", 13)), y + 15), relative=0)
        return y - 31

    page.setFillColor(dark)
    page.setFont("ArialRUBold", 25)
    page.drawString(52, height - 60, "ДомПульс: доступ для проверки")
    page.setFont("ArialRU", 11)
    page.setFillColor(muted)
    page.drawString(52, height - 80, "Служебный слайд. Не входит в продуктовую часть презентации.")

    y = height - 122
    y = line("Бот MAX", "@t312_hakaton_max_bot", y, link="https://max.ru/t312_hakaton_max_bot")
    y = line("Мини-приложение", "apaww.github.io/dom.sreda.io", y, link="https://apaww.github.io/dom.sreda.io/")
    y = line("API / проверка", "104.252.77.141.nip.io/health", y, link="https://104.252.77.141.nip.io/health")
    y = line("Архив исходников", "DomPuls-source-e871283.zip", y)
    y = line("Версия исходников", "e871283", y)
    y = line("Версия mini-app", "dc86116", y)

    page.setFont("ArialRUBold", 13)
    page.setFillColor(dark)
    page.drawString(52, y - 5, "Как пройти основной сценарий")
    page.setFont("ArialRU", 11)
    steps = [
        "1. В MAX открыть бота, отправить /start и выбрать роль «Житель».",
        "2. Сообщить о лифте №2; открыть карточку через кнопку мини-приложения.",
        "3. В режиме показа сменить роли: домоуправляющий, УК, исполнитель.",
        "4. Передать, принять, назначить, приложить фото, завершить работу.",
        "5. Вернуться к роли жителя и подтвердить результат; открыть историю лифта.",
    ]
    for index, step in enumerate(steps):
        page.drawString(52, y - 29 - index * 19, step)

    page.setFillColor(muted)
    page.setFont("ArialRU", 9)
    page.drawString(52, 85, "SHA-256 архива: 356069b086555eb6faa8276edae879d27acac4a57ea14c9f6e9d179df135d20d")
    page.drawString(52, 70, "Доступ: обычный аккаунт MAX. Логин и пароль для демо не требуются; рабочие токены в Git не публикуются.")
    page.drawString(52, 55, "Локально: cp .env.example .env; docker compose up --build. По умолчанию MAX симулируется.")
    page.drawString(52, 40, "Передача в УК модельная; официальный канал УК/ГИС ЖКХ не подключён.")
    page.showPage()
    page.save()
    buffer.seek(0)
    return buffer


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.append(PdfReader(build_access_page()))
    writer.append(PdfReader(SOURCE))
    with OUTPUT.open("wb") as stream:
        writer.write(stream)
    print(OUTPUT)


if __name__ == "__main__":
    main()
