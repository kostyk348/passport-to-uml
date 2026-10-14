# passport-to-uml

**Extract functional UML component diagrams from technical passport PDFs.**

Parses technical documentation (ГОСТ, ТУ, паспорта изделий), extracts
components, connections, and control logic, then renders a colored
UML-style diagram via Graphviz and writes a component/connection table.

---

## Status: v1.2 — rules are still a proof of concept, the pipeline is checkable

Разбор по-прежнему основан на правилах (регулярные выражения + словарь
терминов), и на чужом документе он даст неполный результат — это ограничение
самого подхода, см. «Известные ограничения». Но конвейер вокруг разбора теперь
проверяемый: юнит-тесты без внешних зависимостей, документированный CLI-контракт,
CI и прогон по трём паспортам разных производителей (`examples/passports/`).

Что добавлено в v1.2 (срез «тесты + CLI-контракт + три паспорта»):

- граф связей собирается в DOT **средствами стандартной библиотеки**
  (`render_dot`) и пишется всегда; PNG/PDF — необязательный шаг поверх него;
- **таблица состава** `<stem>.spec.md` / `<stem>.spec.csv` / `<stem>.links.csv`;
- отброшенные связи больше не исчезают молча: `SystemModel.dropped_relations`;
- CLI: вход `.pdf` / `.txt` / `.html`, коды возврата 0–4, `--outdir`,
  `--no-render`, `--quiet`;
- `tests/` — 75 тестов на stdlib (`unittest`), CI в `.github/workflows/tests.yml`;
- `check_passports.py` — замена `run_all.py` (тот привязан к Windows и локальным
  путям автора: `os.environ['USERPROFILE']` падает на Linux ещё при импорте).

**v2 goal (не в этом срезе):** заменить хрупкий pattern matching на LLM-агента,
который читает текст семантически и отдаёт структурированную модель рендереру.

---

## How It Works

```
Input: passport PDF (ГОСТ / ТУ) — или .txt / .html с тем же текстом
  │
  ▼ passport_to_uml.sources: pdfplumber (PDF) / stdlib (txt, html)
Extract text + sectionize by numbered headers
  │
  ▼ pattern matching + dictionary of terms
Extract components, connections, control flow
  │
  ▼ render_dot (stdlib) → <stem>.dot        ← граф связей, пишется всегда
  │        └── Graphviz (если установлен) → <stem>.png + <stem>.pdf
  │
  ▼ write_spec_table (stdlib)
Таблица состава: <stem>.spec.md, <stem>.spec.csv, <stem>.links.csv
```

### Diagram features
- Color-coded categories (airflow, hydronic, control, electrical, etc.)
- Logical grouping by subsystem (clusters with dashed borders)
- Labeled connections with flow direction
- Legend
- Russian labels, Arial font

---

## Installation

```bash
git clone https://github.com/kostyk348/passport-to-uml.git
cd passport-to-uml
pip install -e .

# Для PDF нужен pdfplumber (идёт в зависимостях), для PNG/PDF-диаграммы —
# системный Graphviz:
#   Windows: winget install Graphviz.Graphviz
#   Linux:   apt install graphviz
#   macOS:   brew install graphviz
```

Граф DOT и таблица состава строятся **без** Graphviz — он нужен только
для рендера PNG/PDF.

---

## CLI contract

```bash
# Паспорт → граф связей + таблица состава (+ диаграмма, если есть Graphviz)
python -m passport_to_uml input.pdf [output_prefix] [--outdir DIR]
                                             [--no-render] [-v] [-q]
```

(Тот же CLI доступен как `python -m passport_to_uml.engine ...` и как консольная
команда `passport-to-uml` после `pip install -e .`.)

| Что | Значение |
|-----|----------|
| `input` | паспорт: `.pdf` (нужен pdfplumber), `.txt` / `.asc` / `.md`, `.html` |
| `output` | префикс выходных файлов без расширения; по умолчанию — имя входа |
| `--outdir` | каталог для результатов; по умолчанию — текущий каталог |
| `--no-render` | не вызывать Graphviz: только DOT и таблица состава |
| `--verbose` / `-v` | подробный лог разбора |
| `--quiet` / `-q` | не печатать сводку (файлы всё равно пишутся) |

Выходные файлы:

| Файл | Содержимое |
|------|------------|
| `<stem>.dot` | граф связей, Graphviz DOT (пишется всегда, без внешних зависимостей) |
| `<stem>.spec.md` | таблица состава + таблица связей (markdown) |
| `<stem>.spec.csv` | таблица состава (CSV, UTF-8 с BOM, разделитель `;`) |
| `<stem>.links.csv` | связи, включая отброшенные (статус + причина) |
| `<stem>.png`, `<stem>.pdf` | диаграмма (только если Graphviz доступен и рендер прошёл) |

Коды возврата (они же — в `--help`):

| Код | Когда |
|-----|-------|
| `0` | успех: DOT + таблица состава (+ PNG/PDF, если рендер прошёл или задан `--no-render`) |
| `1` | входной файл не найден или недоступен для чтения |
| `2` | ошибка в аргументах командной строки (это код argparse) |
| `3` | текст из паспорта не извлечён: нет текстового слоя (скан), битый файл, нет pdfplumber, либо ни одного компонента не найдено |
| `4` | рендер PNG/PDF не выполнен (нет `dot`/модуля graphviz) — DOT и таблица состава записаны |

Пример:

```bash
$ python -m passport_to_uml passport.pdf --outdir out
passport-to-uml 1.2.0
Вход: passport.pdf (1 стр., 1031 символов)
Компонентов: 16 | связей: 2 (отброшено: 0) | групп: 3
Граф (DOT): out/passport.dot
Таблица состава: out/passport.spec.md (CSV: out/passport.spec.csv, out/passport.links.csv)
Диаграмма: не построена — Graphviz недоступен или упал; DOT сохранён в out/passport.dot
```

### Python API

```python
from passport_to_uml import parse_passport, build_diagram, write_spec_table, render_dot

model = parse_passport("document.pdf")       # .pdf / .txt / .html
print(model.title, len(model.components), len(model.relations))

open("diagram.dot", "w").write(render_dot(model))     # граф без Graphviz
write_spec_table(model, "diagram")                    # .spec.md / .spec.csv / .links.csv
png, pdf = build_diagram(model, "diagram")            # (None, None), если нет Graphviz
```

Для проверки правил без файлов: `parse_passport_text([(1, text)], "stem")`.

---

## Таблица состава

`<stem>.spec.md` — две таблицы: компоненты (№, ID, наименование, категория,
группа, раздел(ы) паспорта, число связей, описание) и связи (откуда, куда,
метка, статус, причина). Порядок строк — порядок появления компонента в
документе, поэтому файл воспроизводим побайтово на одном и том же входе.

Компонент с `связей = 0` — это сигнал: в паспорте он есть, а связь к нему
либо не упомянута, либо не распознана правилами.

---

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

75 тестов, только стандартная библиотека (pdfplumber и Graphviz не нужны).
Покрытие: правила извлечения (секции, классификация, списки, терминальные
связи), модель и поведение связей, DOT-граф + таблица состава, CLI-контракт,
разбор трёх паспортов разных производителей.

---

## Проверка на трёх паспортах разных производителей

`examples/passports/` — три паспорта с разной вёрсткой и терминологией:
нумерованные пункты ГОСТ (ЗАО «Тепломаш»), ТУ-стиль со списком «– Название;»
и словом «клеммник» (ООО «Вент-Сервис»), евро-стиль с пунктами «•»
и словом «контроллер» (ООО «Климат-Про»).

```bash
# вариант 1: прямо по текстовым фикстурам (без pdfplumber)
python check_passports.py examples/passports/*.txt --outdir out

# вариант 2: как с настоящими документами — через PDF
python examples/build_passport_pdfs.py                 # нужен LibreOffice
python check_passports.py examples/passports/pdf/*.pdf --outdir out   # нужен pdfplumber
```

Фактический результат (одинаковый для .txt и для PDF-версии):

| паспорт | компонентов | связей | отброшено | групп |
|---------|------------:|-------:|----------:|------:|
| `vendor_a_teplomash_blok-e_gost` | 16 | 2 | 0 | 3 |
| `vendor_b_vent-servis_shu-2_tu` | 11 | 2 | 0 | 4 |
| `vendor_c_klimat-pro_suz-3_tu` | 16 | 2 | 0 | 4 |

`check_passports.py` — замена `run_all.py`: тот берёт 8 конкретных PDF по
абсолютным путям `%USERPROFILE%\Downloads`, подставляет заранее описанные seed'ы
и не запускается вне Windows.

---

## Случай «в паспорте нет данных для ребра»

Что делает система, если связь ссылается на узел, которого нет в модели:

- **API модели** (`SystemModel.relate`): ребро не добавляется, `relate` возвращает
  `False`, событие уходит в лог (`WARNING`) и в `model.dropped_relations`, а затем
  в `<stem>.links.csv` со статусом «отброшена» и причиной. Молча ребро больше
  не теряется — это закреплено тестами `tests/test_model.py` и
  `tests/test_three_manufacturers.py::DroppedRelationsTest`.
- **Разбор паспорта**: если формулировка связи не совпала с шаблоном, ребра нет
  вовсе — ни ошибки, ни пометки. Косвенный сигнал остаётся в таблице состава:
  компонент виден со `связей = 0` (например, «Клеммник X2» и «Термостат Т2»).
  Примеры — в `tests/test_three_manufacturers.py` (`known_gap_*`).

---

## Известные ограничения (найдено и закреплено тестами в этом срезе)

Правила v1.2 — PoC, и тесты `known_gap_*` / `known_defect_*` фиксируют текущее
поведение, а не желаемое. Когда правила починят, эти тесты упадут и напомнят
обновить README.

1. **Цифры в обозначении ломают связь.** «Пульт IR03 должен быть подключен к
   клеммной колодке X1» и «Термостат Т2 …» — рёбра не извлекаются: в шаблонах
   для имени устройства нет цифр.
2. **Порядок слов.** «Насос циркуляционный должен быть подключен …» не
   распознаётся: перечисленные в шаблоне слова («насос», «датчик», …) должны
   стоять в конце имени.
3. **Синонимы терминов.** «Клеммник X2» в модели есть, но связь к нему строится
   как к выдуманному узлу «Клеммная колодка X2», а имя устройства-источника
   превращается в мусорную строку («Терморегулятор ТР-1 должен быть»).
   «Магнитный пускатель КМ2» отбрасывается как неклассифицируемый, зато
   появляется выдуманный «Контактор КМ2».
4. **Выдуманные компоненты.** Правила добавляют то, чего в паспорте нет:
   «Завеса 1…6» (жёсткий дефолт), «Воздух из помещения», а «Клапан К1»
   порождает «Реле К1» (правило `К\d+`).
5. **Заголовок страницы.** Если в обозначении изделия есть цифры
   («ШКАФ УПРАВЛЕНИЯ ЩУ-2 Паспорт»), заголовок не извлекается; если начинается
   с «БЛОК»/«МОДУЛЬ»/«ПУЛЬТ» — в модель попадает склеенный заголовок страницы
   («…БЛОК-Е\nПаспорт\nРедакция»).
6. **Нумерация пунктов.** Номер пункта перед фразой о подключении («4.1 …»)
   может попасть в имя устройства (шаблон допускает цифры).
7. **Метаданные пакета.** `pyproject.toml` содержал `license = MIT` при
   Apache-2.0 в `LICENSE` и README (исправлено в v1.2); Pillow используется
   в `build_functional_diagram`, но не был объявлен в зависимостях (добавлен).
8. **`run_all.py`** не запускается вне Windows и не проверяется тестами;
   сохранён как есть — это путь автора с заранее описанными seed'ами.

---

## CI

`.github/workflows/tests.yml`: Python 3.9 / 3.12 / 3.13, `unittest`,
`compileall`, прогон CLI с `--no-render` и проверка трёх паспортов через PDF
(Graphviz и LibreOffice ставятся в раннере).

---

## Provenance

Идея и аудит — «Музей потерянных идей», дайджест
[«Портфель kostyk348»](https://kostyk348.github.io/lost-tech-museum/digests/portfolio-review/),
запись `passport-to-uml`: модуль конвейера инженерной документации
«паспорт → граф связей → диаграмма и таблица состава». Аудит отмечал, что
тестов и проверок на разных производителях в проекте нет — этот срез закрывает
именно это, не меняя архитектуру правил v1.

---

## License

Apache 2.0

## See Also

- [pdf-spec-parser](https://github.com/kostyk348/pdf-spec-parser) — procurement spec table parser & obfuscator
