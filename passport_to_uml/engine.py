#!/usr/bin/env python3
"""
passport-to-uml engine v1.2 — generic electrical/control equipment parser.

Pipeline:
  1. Extract text from PDF / text / HTML (passport_to_uml.sources)
  2. Sectionize — split by numbered headers
  3. Extract components — pattern match names from lists and descriptions
  4. Extract relations — connections from terminal assignments and flow text
  5. Group by subsystem
  6. Build graph → Graphviz DOT (stdlib) → PNG + PDF (Graphviz, если есть)
  7. Таблица состава: <stem>.spec.md / <stem>.spec.csv / <stem>.links.csv
"""

import sys
import os
import re
import json
import logging
from collections import defaultdict, OrderedDict
from pathlib import Path

__version__ = '1.2.0'

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# PDF TEXT EXTRACTOR
# ──────────────────────────────────────────────────────────────────────

def decode_with_pdfplumber(pdf_path):
    import pdfplumber
    blocks = []
    with pdfplumber.open(pdf_path) as pdf:
        for pn, page in enumerate(pdf.pages, 1):
            txt = page.extract_text()
            if txt:
                blocks.append((pn, txt))
    return blocks


def extract_text_all(pdf_path):
    """Return list of (page_num, full_text)."""
    return decode_with_pdfplumber(pdf_path)


# ──────────────────────────────────────────────────────────────────────
# SECTIONIZE — split text into logical sections
# ──────────────────────────────────────────────────────────────────────

SECTION_RE = re.compile(
    r'^(?:Рисунок\s+\d+|Таблица\s+\d+)?\s*'
    r'((?:\d+\.)*\d+)\s+'
    r'([А-ЯA-Z][А-Яа-яA-Za-z\s\-/]+)',
    re.MULTILINE
)


def sectionize(text_blocks):
    """Split concatenated text into named sections.

    Returns list of [(section_id, section_title, text), ...]
    """
    all_text = '\n'.join(t for _, t in text_blocks)
    lines = all_text.split('\n')

    sections = []
    current_id = 'preamble'
    current_title = 'Введение'
    current_lines = []

    for line in lines:
        m = SECTION_RE.match(line.strip())
        if m:
            if current_lines:
                sections.append((current_id, current_title, '\n'.join(current_lines)))
            current_id = m.group(1).strip()
            current_title = m.group(2).strip()
            current_lines = [line.strip()]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_id, current_title, '\n'.join(current_lines)))

    return sections


# ──────────────────────────────────────────────────────────────────────
# COMPONENT CATEGORIES — broader set for electrical/control equipment
# ──────────────────────────────────────────────────────────────────────

CATEGORY_STYLES = {
    'structural':     {'color': '#8B8B8B', 'fill': '#E0E0E0', 'label': 'Конструкция'},
    'airflow':        {'color': '#2E86C1', 'fill': '#D4E6F1', 'label': 'Воздушный тракт'},
    'hydronic':       {'color': '#C0392B', 'fill': '#FADBD8', 'label': 'Гидравлика'},
    'control':        {'color': '#27AE60', 'fill': '#D5F5E3', 'label': 'Управление'},
    'electrical':     {'color': '#8E44AD', 'fill': '#E8DAEF', 'label': 'Электрика'},
    'thermal':        {'color': '#D35400', 'fill': '#FDEBD0', 'label': 'Терморегуляция'},
    'accessory':      {'color': '#5D6D7E', 'fill': '#EBF5FB', 'label': 'Аксессуары'},
    'external':       {'color': '#1B2631', 'fill': '#F2F4F4', 'label': 'Внешние устройства'},
    'protection':     {'color': '#E74C3C', 'fill': '#FADBD8', 'label': 'Защита'},
    'power':          {'color': '#F39C12', 'fill': '#FDEBD0', 'label': 'Питание'},
}

CATEGORY_KEYWORDS = {
    # Electrical
    'контактор': 'electrical',
    'реле': 'electrical',
    'автоматический выключатель': 'electrical',
    'автомат': 'electrical',
    'клемм': 'electrical',
    'колодк': 'electrical',
    'гермоввод': 'electrical',
    'кабель': 'electrical',
    'провод': 'electrical',
    'зажим': 'electrical',
    'шина': 'electrical',
    'перемычк': 'electrical',
    'предохранитель': 'electrical',
    'рубильник': 'electrical',
    'разъем': 'electrical',
    'соединитель': 'electrical',
    'кнопк': 'control',
    'переключатель': 'control',
    'тумблер': 'control',
    'дисплей': 'control',
    'индикатор': 'control',
    'контроллер': 'control',
    'пульт': 'control',
    'модуль': 'control',
    'блок': 'control',
    'щит': 'control',
    'шкаф': 'control',
    'датчик': 'control',
    'термостат': 'control',
    'терморегул': 'thermal',
    'трехходовой': 'hydronic',
    'клапан': 'hydronic',
    'насос': 'hydronic',
    'фильтр': 'hydronic',
    'кран': 'hydronic',
    'патрубок': 'hydronic',
    'теплообменник': 'thermal',
    'нагреватель': 'thermal',
    'калорифер': 'thermal',
    'вентилятор': 'airflow',
    'сопло': 'airflow',
    'воздух': 'airflow',
    'завес': 'airflow',
    'корпус': 'structural',
    'кронштейн': 'structural',
    'крышка': 'structural',
    'рама': 'structural',
    'шасси': 'structural',
    'уплотнени': 'accessory',
    'прокладк': 'accessory',
    'замок': 'accessory',
    # External / protection
    'пожарн': 'protection',
    'пкп': 'protection',
    'сигнализация': 'protection',
    'защита': 'protection',
    'тзз': 'protection',
    'концевой выключатель': 'control',
    # Power
    'питание': 'power',
    'трансформатор': 'power',
    'источник': 'power',
}

# Connection verbs
CONNECTION_VERBS = {
    'подключается', 'подключен', 'подключены',
    'соединяется', 'соединен', 'соединены',
    'присоединяется', 'присоединен',
    'устанавливается', 'установлен',
    'крепится', 'закреплен',
    'входит в', 'встроен в',
    'расположен', 'расположена', 'расположено',
}


def classify_component(name):
    """Return category key for a component name."""
    nl = name.lower()
    for kw, cat in CATEGORY_KEYWORDS.items():
        if kw in nl:
            return cat
    return 'accessory'


# ──────────────────────────────────────────────────────────────────────
# EXTRACTION FUNCTIONS
# ──────────────────────────────────────────────────────────────────────

def extract_list_items(text):
    """Extract items from numbered/bullet lists.

    Patterns:
      "1 - Name;"
      "– Name;"
      "1. Name"
      "* Name"
      "• Name"
    """
    items = []

    # Figure parts: "1 - Name; 2 - Name;"
    for m in re.finditer(r'(?:^|\n)\s*(\d+)\s*[-–]\s*([^;]+);', text, re.MULTILINE):
        items.append({
            'ref': m.group(1),
            'name': m.group(2).strip(),
            'source': 'figure_list',
        })

    # Bullet list items: "– Name description;"
    for m in re.finditer(r'(?:^|\n)\s*[–\-*•]\s*([^;]+);', text, re.MULTILINE):
        name = m.group(1).strip()
        if name and len(name) > 3:
            # Skip instruction-like items (starting with verb)
            if re.match(
                r'^(проверить|закрыть|открыть|убедиться|снять|очистить|'
                r'установить|открутить|заполнить|провести|выполнить|'
                r'проверка|очистка|осмотр|допускается|запрещается|'
                r'при|для|рекомендуется)\b',
                name, re.IGNORECASE):
                continue
            items.append({
                'ref': '',
                'name': name,
                'source': 'bullet',
            })

    return items


def extract_terminal_connections(text):
    """Extract connections from terminal assignment patterns.

    Patterns:
      "X должен быть подключен к клеммной колодке Х5 на клеммы N-FM"
      "подключен к клеммной колодке Х1 на клеммы НРТ1"
      "завесы подключены к клеммам Х2/1"
    """
    connections = []

    # Pattern: device → terminal block: "X должен быть подключен к клеммной колодке ХN"
    for m in re.finditer(
            r'([А-Яа-яA-Za-z\s\-]+(?:термостат|выключатель|сигнализация|насос|клапан|привод|'
            r'устройство|датчик|завес|пульт))\s+должен\s+быть\s+подключен\s+к\s+'
            r'клеммной\s+колодке\s+([ХX]\w+)',
            text, re.IGNORECASE):
        device = m.group(1).strip()
        terminal = m.group(2).strip()
        if len(device) > 3:
            connections.append((device, terminal, 'подключен'))

    # Pattern: "X подключен к Y"
    for m in re.finditer(
            r'([А-Яа-яA-Za-z0-9\-\s]+)\s+(?:подключен|подключается)\s+(?:к|на)\s+'
            r'(клемм[а-я]+\s+)?([ХX]\w+)',
            text, re.IGNORECASE):
        device = m.group(1).strip()
        terminal = m.group(3).strip()
        if len(device) > 2 and len(terminal) > 1:
            connections.append((device, terminal, 'подключен'))

    return connections


def extract_component_from_section4(text):
    """Find main components described in Устройство section.

    Looks for: "В X установлены: – компонент1; – компонент2;"
    and similar patterns.
    """
    components = []
    # Patterns like "В X установлены:" followed by bullet list
    for m in re.finditer(r'(?:установлены|расположены|входят|комплектуется|состоит)\s*:'
                         r'\s*([^.]*(?:;\s*[^.]*)*)',
                         text, re.IGNORECASE):
        content = m.group(1)
        # Extract individual items separated by ;
        for item in re.finditer(r'[–\-]\s*([^;]+)', content):
            name = item.group(1).strip()
            if not name or len(name) < 4 or len(name) > 50:
                continue
            # Must start with uppercase
            if name[0].islower():
                continue
            # Filter descriptive text
            if re.match(
                r'^(управление|включение|индикацию|поддержание|отображение|'
                r'кратковременная|для|при|на|в|с|по|предназначен)',
                name, re.IGNORECASE):
                continue
            components.append(name)
    return components


# ──────────────────────────────────────────────────────────────────────
# STRUCTURED MODEL
# ──────────────────────────────────────────────────────────────────────

class Component:
    __slots__ = ('id', 'name', 'category', 'description', 'refs',
                 'parent', 'ports', 'parts')
    def __init__(self, cid, name, category='accessory', description='',
                 refs=None, parent=None):
        self.id = cid
        self.name = name
        self.category = category
        self.description = description
        self.refs = refs or []
        self.parent = parent
        self.ports = []
        self.parts = []


class Relation:
    __slots__ = ('from_id', 'to_id', 'label', 'style', 'ports')
    def __init__(self, from_id, to_id, label='', style='solid'):
        self.from_id = from_id
        self.to_id = to_id
        self.label = label
        self.style = style
        self.ports = ('', '')


class SystemModel:
    """Complete extracted model: components + relations + notes."""
    def __init__(self):
        self.components = OrderedDict()
        self.relations = []
        self.groups = OrderedDict()
        self.flow_notes = []
        self.dropped_relations = []
        self.title = ''
        self.subtitle = ''

    def add_component(self, comp):
        self.components[comp.id] = comp

    def has_component(self, name):
        cid = _name_to_id(name)
        return cid in self.components

    def get_or_create(self, name, category=None, description=''):
        cid = _name_to_id(name)
        if cid in self.components:
            return self.components[cid]
        cat = category or classify_component(name)
        comp = Component(cid, name, cat, description)
        self.components[cid] = comp
        return comp

    def relate(self, from_name, to_name, label=''):
        """Добавить связь ``from_name → to_name``.

        Возвращает ``True``, если связь добавлена или обновлена, и ``False``,
        если ребро отброшено: один из концов не зарегистрирован как компонент.

        Отброшенное ребро НЕ теряется молча — оно попадает в
        ``self.dropped_relations`` (и в лог), а затем в таблицу состава
        с пометкой «отброшена» и причиной.
        """
        f_id = _name_to_id(from_name)
        t_id = _name_to_id(to_name)
        if f_id in self.components and t_id in self.components:
            for r in self.relations:
                if r.from_id == f_id and r.to_id == t_id:
                    if label and label not in r.label:
                        r.label += ' / ' + label
                    return True
            self.relations.append(Relation(f_id, t_id, label))
            return True

        unknown = []
        if f_id not in self.components:
            unknown.append(f'откуда «{from_name}»')
        if t_id not in self.components:
            unknown.append(f'куда «{to_name}»')
        reason = 'узел не зарегистрирован в модели: ' + ', '.join(unknown)
        self.dropped_relations.append({
            'from': from_name,
            'to': to_name,
            'label': label,
            'reason': reason,
        })
        log.warning('связь отброшена (%s → %s): %s',
                    from_name, to_name, reason)
        return False

    def add_group(self, group_name, component_names):
        gid = _name_to_id(group_name)
        cids = []
        for n in component_names:
            nid = _name_to_id(n)
            if nid in self.components:
                cids.append(nid)
                self.components[nid].parent = gid
        if cids:
            self.groups[gid] = (group_name, cids)


def _name_to_id(name):
    """Convert component name to stable ID."""
    s = name.lower().strip()
    s = re.sub(r'[^а-яa-z0-9]', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s or 'unknown'


# ──────────────────────────────────────────────────────────────────────
# PARSER — convert passport text into model
# ──────────────────────────────────────────────────────────────────────

def get_device_title(first_page_text):
    """Extract device title from first page."""
    title_match = re.search(r'([А-Я][А-Яа-я\-–\s]+)\s*(?:Паспорт|Руководство)', first_page_text)
    if title_match:
        return title_match.group(1).strip()
    return None


def extract_flow_paths(text, known_components):
    """Extract flow sequences from descriptive text."""
    flows = []
    for m in re.finditer(
            r'(теплоноситель|вода|воздух)\s+.*?'
            r'(?:поступает|подается|проходит|направляется|всасывается|выбрасывается)'
            r'(?: через | в | из | на | к )+([^.!?\n]+)',
            text.lower()):
        flows.append({
            'medium': m.group(1),
            'path': m.group(2).strip()[:120],
        })
    return flows


CONNECTION_WORDS = {
    'подключен', 'подключается', 'соединен', 'соединяется',
    'присоединен', 'присоединяется', 'управляет', 'управляется',
    'подает', 'подается', 'поступает', 'проходит', 'направляется',
}


def parse_passport_text(pages, stem=''):
    """Разобрать уже извлечённые страницы паспорта → SystemModel.

    ``pages`` — список ``(номер_страницы, текст)``, как их отдаёт
    :func:`passport_to_uml.sources.read_passport_source`.

    Отделено от :func:`parse_passport`, чтобы правила разбора можно было
    проверять без PDF и без pdfplumber (и прогнать паспорт в виде текста).
    """
    if not pages:
        log.error("No text extracted")
        return None

    all_text = '\n'.join(t for _, t in pages)
    log.info("Extracted %d chars from %d pages", len(all_text), len(pages))

    # 2. Sectionize
    sections = sectionize(pages)

    # 3. Build model
    model = SystemModel()
    model.subtitle = stem

    # Find device title
    first_page_text = pages[0][1] if pages else ''
    title = get_device_title(first_page_text)
    model.title = title or 'Функциональная схема'

    # 4. Extract main device name (first on page 1)
    device_name_match = re.search(
        r'(?:(?:БЛОК|МОДУЛЬ|ПУЛЬТ)[А-Яа-яA-Za-z\s\-]+(?:IP\d+)?(?:\s+[А-Яа-яA-Za-z\-\/]+)*)',
        first_page_text)
    # Also look for the full model designation
    model_code_match = re.search(
        r'(КЭВ[-\w]+|БЛОК[-\w]+|МП[-\w]+|ПКУ[-\w]+)',
        first_page_text)
    device_model = model_code_match.group(1) if model_code_match else None
    device_full = device_name_match.group(0).strip() if device_name_match else None

    # Register the device itself
    if device_full:
        model.get_or_create(device_full, 'structural',
                            f'Основное устройство {device_model or ""}')
    if device_model and device_model != _name_to_id(device_full or ''):
        # Only add if not already added as device_full
        if not device_full or device_model not in device_full:
            model.get_or_create(device_model, 'structural',
                                f'Основное устройство')

    # 5. Extract additional components from all sections
    seen_names = set()
    for comp in model.components.values():
        seen_names.add(comp.name.lower())
    # Also add common names seen in similar devices
    for cn in list(seen_names):
        seen_names.add(cn)

    # Phrases that are NOT components — skip these
    NON_COMPONENT_PATTERNS = re.compile(
        r'^(отображение|поддержание|управление|включение|индикацию|'
        r'выбор|установка|кратковременная|режим|работа|эксплуатация|'
        r'гарантия|утилизация|транспортировка|хранение|обслуживание|'
        r'свидетельство|комплект|назначение|условия|характеристики|'
        r'указание|требование|возможные|неисправности|способы|устранения|'
        r'внешним|эксплуатационным|несанкционированными|непроведением|'
        r'неисправно|вероятная|способ|разряжены|превышает|'
        r'увеличение|уменьшение|максимальная|средняя|низкая|вторая|первая|'
        r'при|для|рекомендуется|разработан|настроен|принят|изготовлен|'
        r'паспорт|сертификат|дата|модель|артикул|питание|степень|заводской)\b',
        re.IGNORECASE
    )

    # Process sections for list items
    for sec_id, sec_title, sec_text in sections:
        if sec_id and sec_id.replace('.', '').isdigit():
            # Extract list items
            items = extract_list_items(sec_text)
            for item in items:
                name = item['name']
                if len(name) < 5 or len(name) > 60:
                    continue
                if not re.search(r'[А-Яа-яA-Za-z]{4,}', name):
                    continue
                if name[0].islower():
                    continue  # must start with uppercase (proper noun)
                if NON_COMPONENT_PATTERNS.match(name):
                    continue
                # Skip items with too many prepositions (descriptive, not a name)
                prep_count = len(re.findall(r'\b(в|на|для|при|с|от|по|через|из|за|под|над)\b', name.lower()))
                if prep_count > 2:
                    continue
                # Skip items that look like full instructions (starts with verb)
                if re.match(r'^(проверить|закрыть|открыть|убедиться|снять|очистить|'
                            r'установить|открутить|заполнить|провести|выполнить|'
                            r'проверка|очистка|осмотр|допускается|запрещается|'
                            r'разобрать|подключить|недопускать|отключить)\b',
                            name, re.IGNORECASE):
                    continue

                nl = name.lower()
                if nl in seen_names:
                    continue
                seen_names.add(nl)

                # Classify and add
                cat = classify_component(name)
                if cat == 'accessory':
                    continue  # skip unclassifiable items
                ref = f"раздел {sec_id}"
                model.add_component(Component(_name_to_id(name), name, cat, ref))
                model.components[_name_to_id(name)].refs.append(sec_id)

            # Also extract from "установлены:" patterns
            extra = extract_component_from_section4(sec_text)
            for name in extra:
                nl = name.lower()
                if nl not in seen_names:
                    seen_names.add(nl)
                    cat = classify_component(name)
                    if cat != 'accessory':
                        model.add_component(Component(_name_to_id(name), name, cat,
                                                      f"из раздела {sec_id}"))

    # 6. Extract terminal connections -> relations
    terminal_conns = extract_terminal_connections(all_text)
    for device, terminal, verb in terminal_conns:
        # Normalize: all terminal blocks use Latin X
        term_clean = terminal.strip().upper().replace('Х', 'X')
        if not term_clean.startswith('X'):
            term_clean = 'X' + term_clean.lstrip('X')
        term_name = f'Клеммная колодка {term_clean}'
        # Add device and terminal block
        model.get_or_create(device)
        model.get_or_create(term_name, 'electrical')
        model.relate(device, term_name, verb)

    # 7. Extract additional component names from text patterns
    # Helper: add electrical component if not exists
    def _add_electrical(name, category='electrical'):
        if not model.has_component(name):
            model.get_or_create(name, category)

    # Look for named terminal blocks: X1, X2, X5, X7, etc. (normalize X)
    for m in re.finditer(r'клеммн[а-я]+\s+колодк[а-я]+\s+([ХX]\d+)', all_text, re.IGNORECASE):
        tb = m.group(1).upper().replace('Х', 'X')
        _add_electrical(f'Клеммная колодка {tb}')

    # Look for contactors: КМ1...КМ18
    kontaktor_seen = set()
    for m in re.finditer(r'\b(КМ\d+)\b', all_text):
        ref = m.group(1)
        if ref not in kontaktor_seen:
            kontaktor_seen.add(ref)
            _add_electrical(f'Контактор {ref}')

    # Look for relays: К1, К2
    for m in re.finditer(r'(?<!\w)([КK])(\d{1,2})(?!\w)', all_text):
        prefix, num = m.group(1), m.group(2)
        if prefix.upper() == 'К' and num.isdigit():
            n = int(num)
            if 1 <= n <= 20:
                _add_electrical(f'Реле К{num.upper()}')

    # Look for jumpers: П1, П2, П3
    for m in re.finditer(r'перемычк[а-я]+\s+(П\d+)', all_text, re.IGNORECASE):
        _add_electrical(f'Перемычка {m.group(1).upper()}')

    # Look for automatic breakers (если есть упоминание)
    if re.search(r'автоматическ[а-я]+\s+выключател[а-я]+', all_text, re.IGNORECASE):
        _add_electrical('Автоматический выключатель')

    # Look for short cable names
    for m in re.finditer(r'кабель\s+([А-Яа-яA-Za-z0-9\s\-]{2,30})', all_text, re.IGNORECASE):
        cable_name = m.group(1).strip()
        if 3 <= len(cable_name) <= 20 and not any(w in cable_name.lower()
                                                    for w in ['длин', 'метр', 'сечени']):
            _add_electrical(f'Кабель {cable_name}')

    # 8. External actors
    if any('воздух' in t.lower() for _, t in pages):
        model.get_or_create('Воздух из помещения', 'airflow')
    if any('проем' in t.lower() for _, t in pages):
        model.get_or_create('Проем защищаемый', 'airflow')
    if any('завес' in t.lower() for _, t in pages):
        # Find number of curtains mentioned — only in the context of "количество завес"
        curtain_count = 0
        # Look for explicit count patterns in section 1 or 3
        for m in re.finditer(r'(?:количество\s+подключаемых\s+завес|до\s+(\w+)\s+завес)\s*[:\s]+(\w+)',
                             all_text, re.IGNORECASE):
            val = m.group(2).lower()
            nums = {'одной': 1, 'одна': 1, 'двух': 2, 'две': 2, 'трех': 3, 'три': 3,
                    'четырех': 4, 'четыре': 4, 'пяти': 5, 'шести': 6, 'шесть': 6}
            if val in nums:
                curtain_count = nums[val]
            elif val.isdigit():
                curtain_count = int(val)
        # Also try: "от одной до двух завес" patterns
        if not curtain_count:
            for m in re.finditer(r'от\s+(\w+)\s+до\s+(\w+)\s+завес', all_text, re.IGNORECASE):
                val = m.group(2).lower()
                nums = {'одной': 1, 'двух': 2, 'трех': 3, 'четырех': 4, 'пяти': 5, 'шести': 6}
                if val in nums:
                    curtain_count = nums[val]
        if not curtain_count:
            curtain_count = 6  # default max for BKU-WA6
        for i in range(1, min(curtain_count + 1, 7)):  # cap at 6
            model.get_or_create(f'Завеса {i}', 'airflow')

    # 9. Group by subsystem — auto-group based on section structure
    # Find groups from section titles
    section_keywords = {
        'устройство': 'Основное устройство',
        'терморегулир': 'Узел терморегулирования',
        'электрическ': 'Электрическая часть',
        'управлени': 'Система управления',
        'подключени': 'Внешние подключения',
        'дополнительн': 'Дополнительное оборудование',
    }

    # Assign components to groups based on category
    electric_components = []
    control_components = []
    hydronic_components = []
    airflow_components = []
    external_components = []
    protection_components = []

    for cid, comp in model.components.items():
        cat = comp.category
        if cat == 'electrical':
            electric_components.append(comp.name)
        elif cat in ('control',):
            control_components.append(comp.name)
        elif cat in ('hydronic',):
            hydronic_components.append(comp.name)
        elif cat in ('airflow',):
            airflow_components.append(comp.name)
        elif cat in ('protection',):
            protection_components.append(comp.name)
        elif cat in ('external', 'power'):
            external_components.append(comp.name)

    if airflow_components:
        model.add_group('Воздушный тракт', airflow_components[:15])
    if hydronic_components:
        model.add_group('Гидравлика', hydronic_components[:15])
    if electric_components:
        model.add_group('Электрика', electric_components[:15])
    if control_components:
        model.add_group('Система управления', control_components[:15])
    if protection_components:
        model.add_group('Защита и сигнализация', protection_components[:10])
    if external_components:
        model.add_group('Питание', external_components[:10])

    # If a device model was found, add connections from the device to key components
    device_key = None
    if device_model:
        for cid, comp in model.components.items():
            if device_model in comp.name or (device_full and device_full in comp.name):
                device_key = cid
                break

    # 10. Extract connections from specific patterns in text
    # Pattern: "X должен быть подключен к клеммной колодке Y"
    # Handles gender forms: должен/должна/должно, подключен/подключена/подключено
    for m in re.finditer(
            r'(?:[–\-]\s*)?([А-Яа-яA-Za-z\s\-]{4,60}?)'
            r'\s+долж[ее][ннаот]?\s+быть\s+подключен[аоы]?\s+'
            r'к\s+клеммн[а-я]+\s+колодк[а-я]+\s+([ХX]\d+)',
            all_text, re.IGNORECASE):
        dev = m.group(1).strip().rstrip(',').strip()
        tb = m.group(2).upper().replace('Х', 'X')
        # Normalize long descriptive names - take only the core device name
        # e.g., "Узел терморегулирования с трехходовым..." -> "Узел терморегулирования"
        core = re.match(r'(Узел\s+\w+|Термостат[а-я]+\s+\w+(?:\s+\w+)?|'
                        r'Концевой\s+выключатель|Пожарная\s+сигнализация|'
                        r'Внешний\s+термостат|Циркуляционный\s+насос)', dev)
        if core:
            dev = core.group(1)
        if len(dev) > 60:
            continue
        tb_name = f'Клеммная колодка {tb}'
        model.get_or_create(dev)
        model.get_or_create(tb_name, 'electrical')
        model.relate(dev, tb_name, 'подключен')

    # Pattern: short form "X – на клеммы Y" (e.g., "Циркуляционный насос – на клеммы N-FM")
    for m in re.finditer(
            r'([А-Яа-яA-Za-z\s\-]{4,40}?)\s*[–\-]\s*на\s+клеммы?\s+'
            r'([\w\-]+(?:\s+и\s+[\w\-]+)?)',
            all_text, re.IGNORECASE):
        dev = m.group(1).strip()
        term = m.group(2).strip()
        if len(dev) > 3 and len(dev) < 50:
            model.get_or_create(dev)
            # Connect to the associated terminal block
            tb_name = f'Клеммы {term}'
            model.get_or_create(tb_name, 'electrical')
            model.relate(dev, tb_name, 'подключен')

    # 11. Extract flow notes
    for f in extract_flow_paths(all_text, []):
        model.flow_notes.append(f"{f['medium']}: {f['path']}")

    log.info("Model: %d components, %d relations, %d groups",
             len(model.components), len(model.relations), len(model.groups))
    return model


def parse_passport(path):
    """Прочитать паспорт (PDF / текст / HTML) и вернуть SystemModel.

    Бросает :class:`passport_to_uml.sources.InputNotFound` (нет файла)
    или :class:`passport_to_uml.sources.TextExtractionError` (текст не извлечь).
    """
    from .sources import read_passport_source

    log.info("Parsing passport: %s", path)
    pages = read_passport_source(path)
    stem = Path(path).stem
    return parse_passport_text(pages, stem)


# ──────────────────────────────────────────────────────────────────────
# DIAGRAM BUILDER — Graphviz DOT renderer
# ──────────────────────────────────────────────────────────────────────

def _sanitize(s):
    """Escape special chars for DOT labels."""
    return s.replace('"', "'").replace('\\', '\\\\').replace('\n', '\\n')


CIRCLED = [
    '\u2460', '\u2461', '\u2462', '\u2463', '\u2464', '\u2465',
    '\u2466', '\u2467', '\u2468', '\u2469',  # ① through ⑩
]
def _circled_num(n):
    """Return circled number for small n (e.g., ① for 1). Falls back to (n)."""
    if 1 <= n <= len(CIRCLED):
        return CIRCLED[n - 1]
    return f'({n})'


def _style_for_category(cat):
    return CATEGORY_STYLES.get(cat, CATEGORY_STYLES['accessory'])


# ──────────────────────────────────────────────────────────────────────
# ТАБЛИЦА СОСТАВА И DOT-ГРАФ — только stdlib, без Graphviz
# ──────────────────────────────────────────────────────────────────────

def _group_name_of(model, cid):
    """Имя группы, в которую входит компонент (или пустая строка)."""
    for gname, cids in model.groups.values():
        if cid in cids:
            return gname
    return ''


COMPONENT_COLUMNS = ('no', 'id', 'name', 'category', 'category_label',
                     'group', 'refs', 'links', 'description')
LINK_COLUMNS = ('no', 'from', 'to', 'label', 'status', 'reason')


def spec_rows(model):
    """Таблица состава: строка на каждый компонент модели."""
    rows = []
    for number, comp in enumerate(model.components.values(), 1):
        refs = []
        for ref in comp.refs:
            if ref and ref not in refs:
                refs.append(ref)
        style = CATEGORY_STYLES.get(comp.category, CATEGORY_STYLES['accessory'])
        rows.append({
            'no': number,
            'id': comp.id,
            'name': comp.name,
            'category': comp.category,
            'category_label': style['label'],
            'group': _group_name_of(model, comp.id),
            'refs': ', '.join(refs),
            'links': sum(1 for rel in model.relations
                         if comp.id in (rel.from_id, rel.to_id)),
            'description': comp.description,
        })
    return rows


def link_rows(model):
    """Связи модели: принятые рёбра и отброшенные (с причиной).

    Отброшенные рёбра — это случай «в паспорте нет данных для ребра»:
    система не теряет их молча, а показывает в таблице со статусом.
    """
    rows = []
    for number, rel in enumerate(model.relations, 1):
        frm = model.components.get(rel.from_id)
        to = model.components.get(rel.to_id)
        rows.append({
            'no': number,
            'from': frm.name if frm else rel.from_id,
            'to': to.name if to else rel.to_id,
            'label': rel.label,
            'status': 'принята',
            'reason': '',
        })
    for number, drop in enumerate(model.dropped_relations,
                                  len(model.relations) + 1):
        rows.append({
            'no': number,
            'from': drop['from'],
            'to': drop['to'],
            'label': drop.get('label', ''),
            'status': 'отброшена',
            'reason': drop.get('reason', ''),
        })
    return rows


def _md_cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').strip()


def _md_table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(_md_cell(cell) for cell in row) + ' |')
    return '\n'.join(lines)


def render_spec_markdown(model):
    """Таблица состава + таблица связей в markdown."""
    rows = spec_rows(model)
    links = link_rows(model)
    accepted = sum(1 for row in links if row['status'] == 'принята')
    dropped = len(links) - accepted

    parts = [
        f'# Таблица состава — {model.title or "Функциональная схема"}',
        '',
        f'- источник: `{model.subtitle or "-"}`',
        f'- компонентов: {len(rows)}',
        f'- связей: {accepted} (отброшено: {dropped})',
        f'- групп: {len(model.groups)}',
        '',
        f'## Компоненты ({len(rows)})',
        '',
        _md_table(('№', 'ID', 'Наименование', 'Категория', 'Группа',
                   'Раздел(ы)', 'Связей', 'Описание'),
                  [(r['no'], r['id'], r['name'], r['category_label'],
                    r['group'], r['refs'], r['links'], r['description'])
                   for r in rows]),
        '',
        f'## Связи ({accepted})',
        '',
        _md_table(('№', 'Откуда', 'Куда', 'Метка', 'Статус', 'Причина'),
                  [(r['no'], r['from'], r['to'], r['label'],
                    r['status'], r['reason'])
                   for r in links]),
        '',
    ]

    if model.flow_notes:
        parts.append(f'## Потоки ({len(model.flow_notes)})')
        parts.append('')
        for note in model.flow_notes:
            parts.append(f'- {note}')
        parts.append('')

    return '\n'.join(parts)


def write_spec_table(model, output_stem):
    """Записать таблицу состава: ``<stem>.spec.md``, ``<stem>.spec.csv``,
    ``<stem>.links.csv`` (CSV в UTF-8 с BOM, разделитель «;»)."""
    import csv

    paths = {
        'markdown': output_stem + '.spec.md',
        'components_csv': output_stem + '.spec.csv',
        'links_csv': output_stem + '.links.csv',
    }

    with open(paths['markdown'], 'w', encoding='utf-8') as fh:
        fh.write(render_spec_markdown(model))

    with open(paths['components_csv'], 'w', encoding='utf-8-sig',
              newline='') as fh:
        writer = csv.writer(fh, delimiter=';')
        writer.writerow(COMPONENT_COLUMNS)
        for row in spec_rows(model):
            writer.writerow([row[key] for key in COMPONENT_COLUMNS])

    with open(paths['links_csv'], 'w', encoding='utf-8-sig',
              newline='') as fh:
        writer = csv.writer(fh, delimiter=';')
        writer.writerow(LINK_COLUMNS)
        for row in link_rows(model):
            writer.writerow([row[key] for key in LINK_COLUMNS])

    return paths


def render_dot(model):
    """Собрать исходник Graphviz DOT из модели (stdlib, Graphviz не нужен).

    Это единственный источник правды для графа: тот же текст пишется в
    ``<stem>.dot`` и отдаётся Graphviz для рендера PNG/PDF.
    """
    def q(value):
        return '"' + _sanitize(str(value)) + '"'

    def node_attrs(comp):
        style = _style_for_category(comp.category)
        return (f'label={q(comp.name)}, fillcolor="{style["fill"]}", '
                f'color="{style["color"]}", fontcolor="{style["color"]}", '
                'shape="box", style="filled,rounded", penwidth="1.5"')

    title = (model.title or 'Функциональная схема')
    caption = f'{title}\\n{model.subtitle}' if model.subtitle else title
    counters = (f'Компонентов: {len(model.components)}, '
                f'связей: {len(model.relations)}')
    if model.dropped_relations:
        counters += f', отброшено: {len(model.dropped_relations)}'
    label = caption + '\\n' + counters

    lines = ['digraph functional_scheme {']
    add = lines.append
    add(f'  graph [label="{_sanitize(label)}", labelloc="t", fontsize="20", '
        'fontname="Arial", bgcolor="#FAFAFA", dpi="200", rankdir="TB", '
        'splines="true", pad="0.5", nodesep="0.5", ranksep="1.0", '
        'compound="true"];')
    add('  node [fontname="Arial", fontsize="9", shape="box", '
        'style="filled,rounded", penwidth="1.5"];')
    add('  edge [fontname="Arial", fontsize="7", penwidth="1.2"];')

    grouped = set()
    for gid, (gname, cids) in model.groups.items():
        cids = [cid for cid in cids if cid in model.components]
        if not cids:
            continue
        grouped.update(cids)
        add(f'  subgraph {q("cluster_" + gid)} {{')
        add(f'    label={q(gname)};')
        add('    style="dashed"; color="#888888"; fontsize="14"; '
            'fontname="Arial"; fontcolor="#555555"; penwidth="1.5"; margin="8";')
        for cid in cids:
            add(f'    {q(cid)} [{node_attrs(model.components[cid])}];')
        add('  }')

    # Компоненты вне групп показываем, только если у них есть связи.
    shown = set(grouped)
    for rel in model.relations:
        for cid in (rel.from_id, rel.to_id):
            if cid in model.components and cid not in shown:
                shown.add(cid)
                add(f'  {q(cid)} [{node_attrs(model.components[cid])}];')

    for rel in model.relations:
        if rel.from_id in model.components and rel.to_id in model.components:
            label_attr = f'label={q(rel.label)}, ' if rel.label else ''
            add(f'  {q(rel.from_id)} -> {q(rel.to_id)} [{label_attr}'
                'color="#666666", fontcolor="#666666"];')

    add(f'  subgraph {q("cluster_legend")} {{')
    add('    label="Легенда"; style="dotted"; color="#BBBBBB"; fontsize="10"; '
        'fontname="Arial"; fontcolor="#888888"; penwidth="0.5"; margin="10";')
    for cat_key, cat_style in CATEGORY_STYLES.items():
        if cat_key == 'accessory':
            continue
        add(f'    {q("legend_" + cat_key)} [label={q(cat_style["label"])}, '
            f'fillcolor="{cat_style["fill"]}", '
            f'color="{cat_style["color"]}", '
            f'fontcolor="{cat_style["color"]}", shape="box", '
            'style="filled", fontsize="8", width="1.2", height="0.2"];')
    add('  }')
    add('}')

    return '\n'.join(lines) + '\n'


def build_diagram(model, output_stem=None, render=True):
    """Собрать граф: DOT (всегда) → PNG + PDF (Graphviz, если установлен).

    Возвращает ``(png_path, pdf_path)``; если рендер недоступен или упал —
    ``(None, None)``, но DOT и таблица состава всё равно остаются на диске,
    чтобы граф не потерялся.
    """
    import tempfile
    import shutil

    if output_stem is None:
        output_stem = 'diagram'

    dot_path = output_stem + '.dot'
    dot_source = render_dot(model)
    with open(dot_path, 'w', encoding='utf-8') as fh:
        fh.write(dot_source)
    log.info("DOT: %s", dot_path)

    if not render:
        log.info("Рендер отключён: PNG/PDF не строятся")
        return None, None

    try:
        import graphviz
    except ImportError as exc:
        log.error("Нет python-модуля graphviz (%s): PNG/PDF не построены, "
                  "DOT сохранён в %s", exc, dot_path)
        return None, None

    try:
        source = graphviz.Source(dot_source, engine='dot')
        with tempfile.TemporaryDirectory(prefix='passport_uml_render_') as tmp:
            for fmt in ('png', 'pdf'):
                produced = source.render(
                    filename=os.path.join(tmp, 'diagram'),
                    format=fmt, cleanup=True)
                shutil.move(produced, f'{output_stem}.{fmt}')
    except Exception as exc:
        log.error("Рендер не выполнен (%s: %s): DOT сохранён в %s",
                  type(exc).__name__, exc, dot_path)
        return None, None

    png_path = output_stem + '.png'
    pdf_path = output_stem + '.pdf'
    log.info("Диаграмма: %s, %s", png_path, pdf_path)
    return png_path, pdf_path


# ──────────────────────────────────────────────────────────────────────
# CONTROL FLOW — mode-aware combined diagram
# ──────────────────────────────────────────────────────────────────────

MODE_COLORS = {
    'Зима':        '#1565C0',
    'Лето':        '#E65100',
    'Автоматический': '#2E7D32',
    'Ручной':       '#6A1B9A',
    'Вентиляция':   '#00838F',
    'Нагрев':       '#D84315',
    'Аварийный':    '#C62828',
    'Пожарный':     '#B71C1C',
    '_protection':  '#C62828',
    '_shared':      '#555555',
}

FLOW_EDGE_STYLES = {
    'trigger':    {'style': 'dashed', 'penwidth': '1.5', 'arrowhead': 'normal'},
    'command':    {'style': 'dashed', 'penwidth': '1.8', 'arrowhead': 'normal'},
    'power':      {'style': 'bold',   'penwidth': '2.5', 'arrowhead': 'normal'},
    'sensor':     {'style': 'dotted', 'penwidth': '1.2', 'arrowhead': 'open'},
    'protection': {'style': 'dashed', 'penwidth': '2.0', 'arrowhead': 'normal',
                   'color': '#C62828'},
}


def _resolve_mode_color(mode_name):
    """Get a color for a mode name — tries exact, falls back to hash-based."""
    if mode_name in MODE_COLORS:
        return MODE_COLORS[mode_name]
    # Generate a stable color from mode name
    import hashlib
    h = hashlib.md5(mode_name.encode()).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f'#{r:02x}{g:02x}{b:02x}'


def build_functional_diagram(model, seed, output_stem=None):
    """Build two separate Graphviz diagrams and stitch vertically:
      Top: structural components in groups (solid boxes, gray lines)
      Bottom: logic flow (dashed boxes, colored arrows with labels)
    Then combine into one PNG + one PDF.
    """
    import graphviz
    import tempfile
    import os
    from PIL import Image

    if output_stem is None:
        output_stem = 'functional_diagram'

    tmpdir = tempfile.mkdtemp(prefix='passport_uml_')

    # ── Parse flow data ──
    modes_section = seed.get('modes', {})
    use_flows = modes_section.get('flow', {})
    mode_descs = modes_section.get('descriptions', {})
    selector = modes_section.get('selector', {})

    flow_components = set()
    flow_edges = []

    for mode_name, flow_chain in use_flows.items():
        for step in flow_chain:
            if len(step) >= 4:
                from_name, to_name, label, edge_type = step[:4]
            elif len(step) == 3:
                from_name, to_name, label = step
                edge_type = 'command'
            else:
                continue
            fid = _name_to_id(from_name)
            tid = _name_to_id(to_name)
            flow_components.add(fid)
            flow_components.add(tid)
            flow_edges.append((fid, tid, label, mode_name, edge_type))

    if selector:
        sel_id = _name_to_id(selector.get('name', 'Переключатель'))
        for mode_name, flow_chain in use_flows.items():
            if mode_name.startswith('_'):
                continue
            if flow_chain:
                first_to = _name_to_id(flow_chain[0][1])
                flow_components.add(sel_id)
                flow_components.add(first_to)
                flow_edges.append((sel_id, first_to, f'Режим {mode_name}', mode_name, 'command'))

    # ══════════════════════════════════════════════════════════
    # DIAGRAM 1: STRUCTURAL COMPONENTS
    # ══════════════════════════════════════════════════════════

    dot1 = graphviz.Digraph(
        name='structural',
        format='png',
        engine='dot',
        graph_attr={
            'label': _sanitize(f'{model.title}\n{model.subtitle}\nСтруктура'),
            'labelloc': 't',
            'fontsize': '28',
            'fontname': 'Arial',
            'bgcolor': '#FAFAFA',
            'dpi': '200',
            'rankdir': 'LR',
            'splines': 'true',
            'overlap': 'false',
            'pad': '0.5',
            'nodesep': '0.8',
            'ranksep': '1.2',
            'compound': 'true',
            'margin': '0.3',
        },
        node_attr={
            'fontname': 'Arial',
            'fontsize': '11',
            'shape': 'box',
            'style': 'filled,rounded',
            'penwidth': '1.5',
            'margin': '0.12,0.06',
        },
        edge_attr={
            'fontname': 'Arial',
            'fontsize': '7',
            'penwidth': '0.8',
        }
    )

    comp_to_group = {}
    grouped_cids = set()
    for gid, (gname, cids) in model.groups.items():
        for cid in cids:
            comp_to_group[cid] = gid
            grouped_cids.add(cid)

    for gid, (gname, cids) in model.groups.items():
        if not cids:
            continue
        with dot1.subgraph(name=f'cluster_{gid}') as sub:
            sub.attr(
                label=_sanitize(gname),
                style='dashed',
                color='#AAAAAA',
                fontsize='12',
                fontname='Arial',
                fontcolor='#666666',
                penwidth='1.2',
                margin='6',
            )
            for cid in cids:
                if cid in model.components:
                    comp = model.components[cid]
                    style = _style_for_category(comp.category)
                    sub.node(cid,
                        label=_sanitize(comp.name),
                        fillcolor=style['fill'],
                        color=style['color'],
                        fontcolor=style['color'],
                        shape='box',
                        style='filled,rounded',
                        penwidth='1.5')

    shown_cids = set(grouped_cids)
    for rel in model.relations:
        for cid in (rel.from_id, rel.to_id):
            if cid in model.components and cid not in shown_cids:
                shown_cids.add(cid)
                comp = model.components[cid]
                style = _style_for_category(comp.category)
                dot1.node(cid,
                    label=_sanitize(comp.name),
                    fillcolor=style['fill'],
                    color=style['color'],
                    fontcolor=style['color'],
                    shape='box',
                    style='filled,rounded',
                    penwidth='1.5')

    for rel in model.relations:
        if rel.from_id in model.components and rel.to_id in model.components:
            dot1.edge(rel.from_id, rel.to_id,
                label=_sanitize(rel.label) if rel.label else '',
                color='#CCCCCC', fontcolor='#AAAAAA',
                style='solid', penwidth='0.4', fontsize='6')

    # Legend for structural diagram
    with dot1.subgraph(name='cluster_legend1') as leg:
        leg.attr(label='Категории', style='dotted', color='#CCCCCC',
                 fontsize='10', fontname='Arial', fontcolor='#888888',
                 margin='5')
        for cat_key, cat_style in CATEGORY_STYLES.items():
            if cat_key == 'accessory':
                continue
            leg.node(f's_leg_{cat_key}',
                label=cat_style['label'],
                fillcolor=cat_style['fill'], color=cat_style['color'],
                fontcolor=cat_style['color'],
                shape='box', style='filled', fontsize='9',
                width='1.8', height='0.3', penwidth='1')

    struct_png = os.path.join(tmpdir, 'struct.png')
    try:
        dot1.save(os.path.join(tmpdir, 'struct.dot'))
        dot1.render(filename=os.path.join(tmpdir, 'struct'), format='png', cleanup=False)
    except Exception as e:
        log.error("Structural render failed: %s", e)
        return None, None

    # ══════════════════════════════════════════════════════════
    # DIAGRAM 2: LOGIC FLOW
    # ══════════════════════════════════════════════════════════

    dot2 = graphviz.Digraph(
        name='logic_flow',
        format='png',
        engine='dot',
        graph_attr={
            'label': _sanitize(f'{model.title}\n{model.subtitle}\nЛогика работы'),
            'labelloc': 't',
            'fontsize': '28',
            'fontname': 'Arial',
            'bgcolor': '#FAFAFA',
            'dpi': '200',
            'rankdir': 'LR',
            'splines': 'true',
            'overlap': 'false',
            'pad': '0.5',
            'nodesep': '0.8',
            'ranksep': '1.5',
            'compound': 'true',
            'margin': '0.3',
        },
        node_attr={
            'fontname': 'Arial',
            'fontsize': '11',
            'shape': 'box',
            'style': 'filled,rounded',
            'penwidth': '1.5',
            'margin': '0.12,0.06',
        },
        edge_attr={
            'fontname': 'Arial',
            'fontsize': '9',
            'penwidth': '1.2',
        }
    )

    # Create flow component nodes (dashed boxes)
    for cid in flow_components:
        lid = f'L_{cid}'
        if cid in model.components:
            comp = model.components[cid]
            style = _style_for_category(comp.category)
            dot2.node(lid,
                label=_sanitize(comp.name),
                fillcolor=style['fill'],
                color=style['color'],
                fontcolor=style['color'],
                shape='box',
                style='filled,rounded,dashed',
                penwidth='1.5')
        else:
            dot2.node(lid,
                label=_sanitize(cid),
                fillcolor='#FFFFFF',
                color='#888888',
                fontcolor='#555555',
                shape='box',
                style='filled,rounded,dashed',
                penwidth='1.0')

    # Flow arrows with colored labels
    for fid, tid, label, mode_name, edge_type in flow_edges:
        lid_from = f'L_{fid}'
        lid_to = f'L_{tid}'
        mode_color = _resolve_mode_color(mode_name)
        ecolor = mode_color if edge_type != 'protection' else '#C62828'
        estyle = FLOW_EDGE_STYLES.get(edge_type, FLOW_EDGE_STYLES['command'])

        dot2.edge(lid_from, lid_to,
            label=_sanitize(label) if label else '',
            color=ecolor,
            fontcolor=ecolor,
            style=estyle.get('style', 'dashed'),
            penwidth=estyle.get('penwidth', '1.5'),
            arrowhead='normal',
            fontsize='9')

    # Legend for logic diagram
    with dot2.subgraph(name='cluster_legend2') as leg:
        leg.attr(label='Типы связей', style='dotted', color='#CCCCCC',
                 fontsize='10', fontname='Arial', fontcolor='#888888',
                 margin='5')
        prev = None
        for ft_name, ft_label, ft_color, ft_style in [
            ('trigger', 'Сигнал', '#E65100', 'dashed'),
            ('command', 'Управление', '#1565C0', 'dashed'),
            ('power', 'ПУСК', '#2E7D32', 'bold'),
            ('sensor', 'Измерение', '#00838F', 'dotted'),
            ('protection', 'Защита', '#C62828', 'dashed'),
        ]:
            lid = f'leg2_{ft_name}'
            leg.node(lid, label=ft_label,
                fillcolor='#FFFFFF', color=ft_color, fontcolor=ft_color,
                shape='box', style='filled', fontsize='9',
                width='1.5', height='0.3', penwidth='1.5')
            if prev:
                leg.edge(prev, lid, color=ft_color, style=ft_style,
                    penwidth='1.5', arrowhead='normal')
            prev = lid

    logic_png = os.path.join(tmpdir, 'logic.png')
    try:
        dot2.save(os.path.join(tmpdir, 'logic.dot'))
        dot2.render(filename=os.path.join(tmpdir, 'logic'), format='png', cleanup=False)
    except Exception as e:
        log.error("Logic render failed: %s", e)
        return None, None

    # ══════════════════════════════════════════════════════════
    # STITCH: combine top + bottom into one PNG
    # ══════════════════════════════════════════════════════════

    try:
        img_struct = Image.open(struct_png)
        img_logic = Image.open(logic_png)

        # Make both same width (pad with background)
        max_width = max(img_struct.width, img_logic.width)
        bg_color = (250, 250, 250)  # #FAFAFA

        def pad_to_width(img, target_w):
            if img.width >= target_w:
                return img
            new_img = Image.new('RGB', (target_w, img.height), bg_color)
            new_img.paste(img, (0, 0))
            return new_img

        img_struct = pad_to_width(img_struct, max_width)
        img_logic = pad_to_width(img_logic, max_width)

        # Create separator line
        sep_height = 8
        sep_img = Image.new('RGB', (max_width, sep_height), (180, 180, 180))

        # Stack vertically: struct + separator + logic
        total_height = img_struct.height + sep_height + img_logic.height
        combined = Image.new('RGB', (max_width, total_height), bg_color)
        combined.paste(img_struct, (0, 0))
        combined.paste(sep_img, (0, img_struct.height))
        combined.paste(img_logic, (0, img_struct.height + sep_height))

        png_path = output_stem + '.png'
        combined.save(png_path, dpi=(200, 200))
        log.info("Combined PNG: %s", png_path)

        # PDF from combined PNG
        pdf_path = output_stem + '.pdf'
        combined.save(pdf_path, 'PDF', resolution=200)
        log.info("Combined PDF: %s", pdf_path)

        # Cleanup temp
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

        return png_path, pdf_path

    except Exception as e:
        log.error("Stitch failed: %s", e)
        log.error("Traceback:", exc_info=True)
        return None, None


# ──────────────────────────────────────────────────────────────────────
# HIGH-LEVEL API
# ──────────────────────────────────────────────────────────────────────

def export_png_pdf(model, output_stem=None, verbose=False):
    """Build and render diagram from model."""
    return build_diagram(model, output_stem)


# Коды возврата CLI — контракт, который проверяют тесты и CI.
EXIT_OK = 0
EXIT_INPUT_MISSING = 1
EXIT_USAGE = 2          # argparse отдаёт его сам
EXIT_NO_TEXT = 3
EXIT_RENDER_FAILED = 4

EXIT_CODES_HELP = """\
коды возврата:
  0  успех: DOT + таблица состава (+ PNG/PDF, если рендер прошёл или задан --no-render)
  1  входной файл не найден или недоступен для чтения
  2  ошибка в аргументах командной строки
  3  текст из паспорта не извлечён (нет текстового слоя / битый файл / нет pdfplumber)
  4  рендер PNG/PDF не выполнен — DOT и таблица состава всё равно записаны

выходные файлы (по умолчанию рядом с текущим каталогом, префикс — имя входа):
  <stem>.dot        граф связей в формате Graphviz DOT (пишется всегда)
  <stem>.spec.md    таблица состава + таблица связей (markdown)
  <stem>.spec.csv   таблица состава (CSV, UTF-8 BOM, разделитель «;»)
  <stem>.links.csv  связи, включая отброшенные (статус + причина)
  <stem>.png/.pdf   диаграмма (только если доступен Graphviz)
"""


def run_cli(argv=None, stdout=None, stderr=None):
    """Паспорт → граф связей (DOT) → диаграмма (PNG/PDF) + таблица состава.

    Возвращает код возврата вместо завершения процесса: контракт проверяется
    тестами без subprocess.
    """
    import argparse
    from .sources import (InputNotFound, PassportSourceError,
                          TextExtractionError, read_passport_source)

    out = stdout or sys.stdout
    err = stderr or sys.stderr

    parser = argparse.ArgumentParser(
        prog='passport-to-uml',
        description='passport-to-uml — паспорт → граф связей → '
                    'диаграмма и таблица состава',
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input',
                        help='паспорт: .pdf (нужен pdfplumber), .txt или .html')
    parser.add_argument('output', nargs='?', default=None,
                        help='префикс выходных файлов (без расширения)')
    parser.add_argument('--outdir', default=None,
                        help='каталог для выходных файлов (по умолчанию — текущий)')
    parser.add_argument('--no-render', action='store_true',
                        help='не вызывать Graphviz: только DOT и таблица состава')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='не печатать сводку')

    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format='%(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        pages = read_passport_source(args.input)
    except InputNotFound as exc:
        print(f'Ошибка: {exc}', file=err)
        return EXIT_INPUT_MISSING
    except TextExtractionError as exc:
        print(f'Ошибка: {exc}', file=err)
        return EXIT_NO_TEXT
    except PassportSourceError as exc:  # pragma: no cover - страховка
        print(f'Ошибка: {exc}', file=err)
        return EXIT_NO_TEXT

    outdir = args.outdir or '.'
    os.makedirs(outdir, exist_ok=True)
    input_stem = os.path.splitext(os.path.basename(args.input))[0]
    stem_arg = args.output or input_stem
    if os.path.dirname(stem_arg):
        output_stem = stem_arg            # явный путь: --outdir не применяется
    else:
        output_stem = os.path.join(outdir, stem_arg)

    model = parse_passport_text(pages, input_stem)
    if model is None or not model.components:
        print(f'Ошибка: из паспорта не выделено ни одного компонента: '
              f'{args.input}', file=err)
        return EXIT_NO_TEXT

    spec_paths = write_spec_table(model, output_stem)
    png, pdf = build_diagram(model, output_stem, render=not args.no_render)

    if not args.quiet:
        print(f'passport-to-uml {__version__}', file=out)
        print(f'Вход: {args.input} ({len(pages)} стр., '
              f'{sum(len(text) for _, text in pages)} символов)', file=out)
        print(f'Компонентов: {len(model.components)} | '
              f'связей: {len(model.relations)} '
              f'(отброшено: {len(model.dropped_relations)}) | '
              f'групп: {len(model.groups)}', file=out)
        print(f'Граф (DOT): {output_stem}.dot', file=out)
        print(f'Таблица состава: {spec_paths["markdown"]} '
              f'(CSV: {spec_paths["components_csv"]}, '
              f'{spec_paths["links_csv"]})', file=out)
        if png and pdf:
            print(f'Диаграмма: {png}, {pdf}', file=out)
        elif args.no_render:
            print('Диаграмма: не строилась (--no-render)', file=out)
        else:
            print(f'Диаграмма: не построена — Graphviz недоступен или упал; '
                  f'DOT сохранён в {output_stem}.dot', file=out)

    if png and pdf:
        return EXIT_OK
    if args.no_render:
        return EXIT_OK
    return EXIT_RENDER_FAILED


def main(argv=None):
    """Точка входа CLI. Возвращает код возврата (см. EXIT_CODES_HELP)."""
    return run_cli(argv)


if __name__ == '__main__':
    sys.exit(main())

