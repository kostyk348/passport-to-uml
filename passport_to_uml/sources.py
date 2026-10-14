"""Источники входных данных: PDF, plain text, HTML → страницы текста.

Модуль намеренно не тянет pdfplumber на уровне импорта: он нужен только
для ветки ``.pdf``, поэтому чистые текстовые источники (``.txt``, ``.html``)
обрабатываются одним stdlib и работают в тестах и в CI без зависимостей.

Ошибки разделены по коду возврата CLI:

* :class:`InputNotFound`      — файла нет / нет доступа (код 1);
* :class:`TextExtractionError` — файл есть, но текста из него не достать (код 3).

Публичная функция: :func:`read_passport_source` → ``[(номер_страницы, текст), ...]``.
"""

import os
import html as _html
from html.parser import HTMLParser

__all__ = [
    "PassportSourceError",
    "InputNotFound",
    "TextExtractionError",
    "read_passport_source",
    "SUPPORTED_SUFFIXES",
]

#: Расширения, которые CLI принимает на вход.
SUPPORTED_SUFFIXES = (".pdf", ".txt", ".text", ".asc", ".md", ".html", ".htm", ".xhtml")

_HTML_SUFFIXES = (".html", ".htm", ".xhtml")
_PAGE_BREAK = "\f"

_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")


class PassportSourceError(Exception):
    """Базовая ошибка чтения паспорта."""


class InputNotFound(PassportSourceError):
    """Входной файл не найден или недоступен для чтения (exit code 1)."""


class TextExtractionError(PassportSourceError):
    """Из входного файла не удалось получить текст (exit code 3)."""


def read_passport_source(path):
    """Вернуть страницы паспорта: список ``(номер_страницы, текст)``.

    Поддерживаются ``.pdf`` (нужен pdfplumber), ``.html``/``.htm`` и
    любые текстовые файлы (``.txt``, ``.asc``, ``.md``).
    """
    path = os.fspath(path)
    if not os.path.exists(path):
        raise InputNotFound(f"входной файл не найден: {path}")
    if os.path.isdir(path):
        raise InputNotFound(f"входной путь — каталог, а не файл: {path}")
    if not os.access(path, os.R_OK):
        raise InputNotFound(f"нет прав на чтение файла: {path}")

    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in _HTML_SUFFIXES:
        return _read_html(path)
    return _read_text(path)


def _read_pdf(path):
    try:
        import pdfplumber  # noqa: F401  (тяжёлая зависимость, только для PDF)
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise TextExtractionError(
            "не удалось прочитать PDF: не установлен pdfplumber "
            "(pip install pdfplumber)"
        ) from exc

    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for number, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    pages.append((number, text))
    except Exception as exc:  # pdfplumber/miner кидают разные типы на битых файлах
        raise TextExtractionError(
            f"не удалось прочитать PDF {path}: {type(exc).__name__}: {exc}"
        ) from exc

    if not pages:
        raise TextExtractionError(
            f"в PDF нет текстового слоя (скан без OCR?): {path}"
        )
    return pages


def _decode(raw, path):
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TextExtractionError(
        f"не удалось определить кодировку файла {path} "
        f"(пробовали: {', '.join(_TEXT_ENCODINGS)})"
    )


def _read_text(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise InputNotFound(f"не удалось прочитать файл {path}: {exc}") from exc

    if not raw.strip():
        raise TextExtractionError(f"файл пустой: {path}")

    text = _decode(raw, path)
    pages = text.split(_PAGE_BREAK)
    result = []
    for number, chunk in enumerate(pages, 1):
        chunk = chunk.strip("\n")
        if chunk.strip():
            result.append((number, chunk))
    if not result:
        raise TextExtractionError(f"в файле нет текста: {path}")
    return result


class _TextCollector(HTMLParser):
    """Достаточно грубый HTML→text: блочные теги дают перевод строки."""

    _BLOCK = {
        "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4",
        "h5", "h6", "table", "ul", "ol", "section", "article", "header",
        "footer", "pre", "blockquote", "hr",
    }
    _SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def text(self):
        raw = "".join(self.parts)
        lines = []
        for line in raw.splitlines():
            line = " ".join(line.split())
            if line:
                lines.append(line)
        return "\n".join(lines)


def _read_html(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise InputNotFound(f"не удалось прочитать файл {path}: {exc}") from exc

    text = _decode(raw, path)
    parser = _TextCollector()
    parser.feed(text)
    parser.close()
    text = parser.text().strip()
    if not text:
        raise TextExtractionError(f"в HTML не нашлось текста: {path}")
    return [(1, text)]


# ``html`` импортируется для convert_charrefs-совместимости при отключённом
# авто-разборе сущностей; удерживаем имя, чтобы линтер не ругался на импорт.
_ = _html.unescape
