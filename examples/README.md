# Examples

## CLI

```bash
# паспорт → граф связей (DOT) + таблица состава (+ PNG/PDF, если есть Graphviz)
python -m passport_to_uml "document.pdf" "diagram" --outdir out

# без Graphviz: только DOT и таблицы
python -m passport_to_uml "document.pdf" --outdir out --no-render
```

Коды возврата и состав выходных файлов — в README, раздел «CLI contract».

## Python API

```python
from passport_to_uml import (parse_passport, render_dot, write_spec_table, build_diagram)

model = parse_passport("document.pdf")          # .pdf / .txt / .html

print(f"Заголовок: {model.title}")
print(f"Компонентов: {len(model.components)}")
print(f"Связей: {len(model.relations)} (отброшено: {len(model.dropped_relations)})")

for r in model.relations:
    frm = model.components[r.from_id].name
    to = model.components[r.to_id].name
    print(f"  {frm} → {to} [{r.label}]")

open("diagram.dot", "w", encoding="utf-8").write(render_dot(model))  # без Graphviz
write_spec_table(model, "diagram")           # .spec.md / .spec.csv / .links.csv
png, pdf = build_diagram(model, "diagram")   # (None, None), если Graphviz недоступен
```

Правила можно проверять и без файлов:

```python
from passport_to_uml import parse_passport_text

model = parse_passport_text([(1, "3.1 Состав изделия\n1 - Контактор КМ1;\n")], "mini")
```

> Прежний пример `parse_passport("document.pdf", verbose=True)` не работал:
> у функции нет параметра `verbose` (флаг есть только у CLI).

## Три паспорта разных производителей

`passports/` — три фикстуры-паспорта с разной вёрсткой и терминологией
(ГОСТ-стиль «1 - Название;», ТУ-стиль «– Название;» + «клеммник»,
евро-стиль «• Название;» + «контроллер»).

```bash
# прогон сразу по всем текстовым фикстурам
python check_passports.py passports/*.txt --outdir out

# или как с настоящими документами: фикстуры → PDF (LibreOffice) → pdfplumber
python build_passport_pdfs.py
python check_passports.py passports/pdf/*.pdf --outdir out
```

Ожидаемые цифры и найденные ограничения правил — в README
(«Проверка на трёх паспортах», «Известные ограничения») и в
`tests/test_three_manufacturers.py`.
