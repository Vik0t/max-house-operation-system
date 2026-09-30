"""Add technical access and two criterion-focused slides to the team's PDF.

The original team deck stays in submission/DomSreda_MAX_hackathon.pdf.
The PDF under output/pdf is the submission artifact.
"""

from io import BytesIO
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "submission" / "DomSreda_MAX_hackathon.pdf"
OUTPUT = ROOT / "output" / "pdf" / "DomSreda_MAX_hackathon_submission.pdf"
SOURCE_COMMIT = "5fa67b79b438fc8ae7c240a40115654474e606f9"
WIDTH, HEIGHT = 720, 405
BLUE = HexColor("#0878ed")
INK = HexColor("#111111")
MUTED = HexColor("#525252")


def register_fonts() -> None:
    options = []
    if os.environ.get("VK_SANS_FONT"):
        options.append(Path(os.environ["VK_SANS_FONT"]))
    options.extend(
        [
            Path.home() / "Library/Fonts/VKSansDisplay-DemiBold.ttf",
            Path.home() / "Downloads/VKSansDisplay-DemiBold.ttf",
        ]
    )
    for font_path in options:
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("DeckRegular", str(font_path)))
            pdfmetrics.registerFont(TTFont("DeckBold", str(font_path)))
            return
    raise RuntimeError("Set VK_SANS_FONT to the VK Sans Display DemiBold TTF file")


def text(page: canvas.Canvas, value: str, x: float, y: float, size: float, *, bold: bool = False, color=INK) -> None:
    page.setFont("DeckBold" if bold else "DeckRegular", size)
    page.setFillColor(color)
    page.drawString(x, y, value)


def wrapped(page: canvas.Canvas, value: str, x: float, y: float, size: float, max_width: float, *, leading: float = 21) -> float:
    words = value.split()
    line = ""
    for word in words:
        candidate = f"{line} {word}" if line else word
        if line and pdfmetrics.stringWidth(candidate, "DeckRegular", size) > max_width:
            text(page, line, x, y, size)
            y -= leading
            line = word
        else:
            line = candidate
    if line:
        text(page, line, x, y, size)
        y -= leading
    return y


def pdf_page(draw) -> PdfReader:
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=(WIDTH, HEIGHT))
    draw(page)
    page.showPage()
    page.save()
    buffer.seek(0)
    return PdfReader(buffer)


def access_slide(page: canvas.Canvas) -> None:
    text(page, "Техническая информация", 40, 354, 30, color=BLUE)
    rows = [
        ("Бот MAX", "https://max.ru/t312_hakaton_max_bot", "https://max.ru/t312_hakaton_max_bot"),
        ("Мини-приложение", "https://apaww.github.io/dom.sreda.io/", "https://apaww.github.io/dom.sreda.io/"),
        ("Репозиторий", "https://github.com/Vik0t/max-house-operation-system", "https://github.com/Vik0t/max-house-operation-system"),
        ("Commit hash", SOURCE_COMMIT, None),
        ("API", "https://104.252.77.141.nip.io", "https://104.252.77.141.nip.io"),
    ]
    for number, (label, value, link) in enumerate(rows):
        y = 321 - number * 21
        text(page, label + ":", 44, y, 11, bold=True)
        text(page, value, 185, y, 11, color=BLUE if link else INK)
        if link:
            page.linkURL(link, (183, y - 2, 685, y + 13), relative=0)
    text(page, "Доступ: обычный аккаунт MAX; роли в боте переключаются в режиме показа.", 44, 202, 10.5)
    text(page, "Локально: cp .env.example .env; docker compose up --build. Пароли не нужны.", 44, 184, 10.5)
    text(page, "Основной сценарий", 44, 153, 17, bold=True)
    steps = [
        "1. Открыть бота в MAX, отправить /start, выбрать дом и роль жителя.",
        "2. Сообщить о лифте №2 в группе; соседи подтверждают общую карточку.",
        "3. Домоуправляющий передаёт; УК принимает; исполнитель завершает с фото.",
        "4. Житель подтверждает исправление; история лифта обновляется.",
        "5. Открыть инициативу и второй дом в мини-приложении.",
    ]
    for number, step in enumerate(steps):
        text(page, step, 44, 130 - number * 21, 11.3)
    text(page, "MAX и вход по MAX ID реальные. Официальная передача в УК в MVP модельная.", 44, 18, 10, color=MUTED)


def architecture_slide(page: canvas.Canvas) -> None:
    text(page, "Архитектура и интеграции", 40, 338, 31, color=BLUE)
    text(page, "MAX", 44, 279, 19, bold=True, color=BLUE)
    wrapped(page, "Личный и групповой чат, мини-приложение, вход по MAX ID.", 44, 251, 16.5, 630)
    text(page, "Сервер", 44, 213, 19, bold=True, color=BLUE)
    wrapped(page, "FastAPI связывает сигналы, модель классификации, роли и работы.", 44, 185, 16.5, 630)
    text(page, "Память дома", 44, 147, 19, bold=True, color=BLUE)
    wrapped(page, "PostgreSQL хранит проблему, работу, подтверждение и историю объекта.", 44, 119, 16.5, 630)
    text(page, "Реально: MAX Bot API и MAX Bridge.", 44, 66, 12.5, bold=True)
    text(page, "Модельно: передача в УК; часть демонстрационной истории синтетическая.", 44, 46, 12.5, color=MUTED)
    text(page, "Источник: README.md, docs/architecture.md, docs/max_setup.md", 44, 21, 9.5, color=MUTED)


def impact_slide(page: canvas.Canvas) -> None:
    text(page, "Эффект и тиражирование", 40, 338, 31, color=BLUE)
    text(page, "Пилот в Кольцово", 44, 282, 19, bold=True, color=BLUE)
    wrapped(page, "Житель видит одну проблему по лифту, ответственного и подтверждённый итог работы.", 44, 254, 16, 630)
    text(page, "Как измерим пользу", 44, 212, 19, bold=True, color=BLUE)
    wrapped(page, "Время от сигнала до назначения; доля объединённых повторов; доля работ с проверкой жителя.", 44, 184, 16, 630)
    text(page, "Переход к другому дому", 44, 121, 19, bold=True, color=BLUE)
    wrapped(page, "Дом Б работает с другим набором объектов, УК, маршрутов и порогов без правки ядра.", 44, 93, 16, 630)
    text(page, "Для пилота нужны проверенные данные дома, роли MAX и согласованный канал УК.", 44, 46, 12.3)
    text(page, "Эффект пока гипотеза, а не измеренный результат. Источник: README.md, configs/", 44, 24, 10.4, color=MUTED)


def main() -> None:
    register_fonts()
    source = PdfReader(SOURCE)
    if len(source.pages) != 17:
        raise RuntimeError(f"Expected the original 17-slide team PDF, got {len(source.pages)} pages")
    if any((float(p.mediabox.width), float(p.mediabox.height)) != (WIDTH, HEIGHT) for p in source.pages):
        raise RuntimeError("The source deck slide size changed")

    writer = PdfWriter()
    access = pdf_page(access_slide).pages[0]
    architecture = pdf_page(architecture_slide).pages[0]
    impact = pdf_page(impact_slide).pages[0]
    for index, page in enumerate(source.pages):
        if index == 0:
            writer.add_page(access)
        else:
            writer.add_page(page)
        if index == 9:
            writer.add_page(architecture)
        if index == 15:
            writer.add_page(impact)
    writer.add_metadata({"/Title": "Дом.Среда — презентация решения для хакатона MAX", "/Author": "Команда ПИИво"})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)
    print(f"{OUTPUT}: {len(writer.pages)} pages")


if __name__ == "__main__":
    main()
