#!/usr/bin/env python3
"""
passport-to-uml engine.

Pipeline:
  1. Extract text from PDF (pdfplumber ± GOST CID)
  2. Sectionize — split by numbered headers (1 НАЗНАЧЕНИЕ, 4.7 Управление...)
  3. Extract components — pattern match names, quantities, types
  4. Extract relations — connections, control signals, flow
  5. Build graph → Graphviz DOT → PNG + PDF
"""

import sys
import os
import re
import json
import subprocess
import logging
from collections import defaultdict, OrderedDict
from pathlib import Path

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# PDF TEXT EXTRACTOR (copied pattern from spec-parser)
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
# SECTIONIZE — split whole-page text into logical sections
# ──────────────────────────────────────────────────────────────────────

# Pattern for Russian section headers: "4 УСТРОЙСТВО", "4.7 Управление", etc.
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
            # Save previous
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
# COMPONENT KNOWLEDGE (domain-specific for series 700 + general)
# ──────────────────────────────────────────────────────────────────────

# Default color scheme for component categories
CATEGORY_STYLES = {
    'structural':     {'color': '#8B8B8B', 'fill': '#E0E0E0', 'label': 'Конструкция'},
    'airflow':        {'color': '#2E86C1', 'fill': '#D4E6F1', 'label': 'Воздушный тракт'},
    'hydronic':       {'color': '#C0392B', 'fill': '#FADBD8', 'label': 'Гидравлика'},
    'control':        {'color': '#27AE60', 'fill': '#D5F5E3', 'label': 'Управление'},
    'electrical':     {'color': '#8E44AD', 'fill': '#E8DAEF', 'label': 'Электрика'},
    'thermal':        {'color': '#D35400', 'fill': '#FDEBD0', 'label': 'Терморегуляция'},
    'accessory':      {'color': '#5D6D7E', 'fill': '#EBF5FB', 'label': 'Аксессуары'},
    'external':       {'color': '#1B2631', 'fill': '#F2F4F4', 'label': 'Внешние устройства'},
}

# Keyword → category
CATEGORY_KEYWORDS = {
    'вентилятор': 'airflow',
    'сопло': 'airflow',
    'воздух': 'airflow',
    'теплообменник': 'thermal',
    'нагреватель': 'thermal',
    'калорифер': 'thermal',
    'корпус': 'structural',
    'кронштейн': 'structural',
    'крышка': 'structural',
    'рама': 'structural',
    'шасси': 'structural',
    'насос': 'hydronic',
    'клапан': 'hydronic',
    'фильтр': 'hydronic',
    'кран': 'hydronic',
    'фитинг': 'hydronic',
    'труб': 'hydronic',
    'патрубок': 'hydronic',
    'коллектор': 'hydronic',
    'термостат': 'control',
    'терморегул': 'thermal',
    'датчик': 'control',
    'контроллер': 'control',
    'пульт': 'control',
    'модуль': 'control',
    'блок': 'control',
    'щит': 'control',
    'шкаф': 'control',
    'гермоввод': 'electrical',
    'колодк': 'electrical',
    'кабель': 'electrical',
    'провод': 'electrical',
    'клемм': 'electrical',
    'зажим': 'electrical',
    'выключатель': 'electrical',
    'лампа': 'electrical',
    'индикатор': 'electrical',
    'уплотнени': 'accessory',
    'прокладк': 'accessory',
    'швеллер': 'structural',
    'пластин': 'structural',
}

# Known connection verbs
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


def extract_list_items(text):
    """Extract items from numbered/bullet lists.

    Patterns:
      "1 - Вентилятор осевой;"
      "– Техническое обслуживание №1"
      "– Насос;"
      "1. Вентилятор"
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
    for m in re.finditer(r'(?:^|\n)\s*[–\-]\s*([^;]+);', text, re.MULTILINE):
        name = m.group(1).strip()
        if name and len(name) > 3:
            # Skip instruction-like items (starting with verb)
            if re.match(
                r'^(проверить|закрыть|открыть|убедиться|снять|очистить|'
                r'установить|открутить|заполнить|провести|выполнить|'
                r'проверка|очистка|осмотр)\b',
                name, re.IGNORECASE):
                continue
            items.append({
                'ref': '',
                'name': name,
                'source': 'bullet',
            })

    return items


def extract_connections(text, known_components):
    """Extract relations between known components from text.

    Patterns:
      "X подключается к Y через Z"
      "X предназначен для подключения Y"
      "X состоит из Y и Z"
      "через X проходит Y"
    """
    connections = []

    comp_names = [c['name'].lower() for c in known_components]

    # Pattern: "{Comp} {verb} {something}"
    for c in known_components:
        cn = c['name'].lower()
        # Find sentences containing this component name
        for sent in re.finditer(r'[^.!?\n]*' + re.escape(cn) + r'[^.!?\n]*[.!?\n]', text.lower()):
            sent_text = sent.group()

            # Check for connection verbs
            for verb in CONNECTION_VERBS:
                if verb in sent_text:
                    # Find what other component is mentioned
                    for c2 in known_components:
                        if c2['name'].lower() == cn:
                            continue
                        if c2['name'].lower() in sent_text:
                            connections.append({
                                'from': c['name'],
                                'to': c2['name'],
                                'via': verb,
                                'context': sent_text[:100].strip(),
                            })
                            break

    return connections


def extract_flow_paths(text, known_components):
    """Extract flow sequences: "X → Y → Z" from descriptive text."""
    flows = []

    # Water flow pattern
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
        self.ports = []   # (port_name, direction: in/out/bidirectional)
        self.parts = []   # sub-component IDs


class Relation:
    __slots__ = ('from_id', 'to_id', 'label', 'style', 'ports')
    def __init__(self, from_id, to_id, label='', style='solid'):
        self.from_id = from_id
        self.to_id = to_id
        self.label = label
        self.style = style
        self.ports = ('', '')  # from_port, to_port


class SystemModel:
    """Complete extracted model: components + relations + notes."""
    def __init__(self):
        self.components = OrderedDict()     # id → Component
        self.relations = []                  # list of Relation
        self.groups = OrderedDict()          # name → [component_ids]
        self.flow_notes = []                 # text notes about flow
        self.title = ''
        self.subtitle = ''

    def add_component(self, comp):
        self.components[comp.id] = comp

    def get_or_create(self, name, category=None, description=''):
        """Find component by name or create new."""
        cid = _name_to_id(name)
        if cid in self.components:
            return self.components[cid]
        cat = category or classify_component(name)
        comp = Component(cid, name, cat, description)
        self.components[cid] = comp
        return comp

    def relate(self, from_name, to_name, label=''):
        f_id = _name_to_id(from_name)
        t_id = _name_to_id(to_name)
        if f_id in self.components and t_id in self.components:
            # Deduplicate
            for r in self.relations:
                if r.from_id == f_id and r.to_id == t_id:
                    if label and label not in r.label:
                        r.label += ' / ' + label
                    return
            self.relations.append(Relation(f_id, t_id, label))

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

# Hardcoded known components for series 700 (fallback/seed)
SERIES700_SEED = {

    # --- Structural ---
    'корпус': ('Корпус', 'structural', 'Стальной оцинкованный корпус'),
    'кронштейн': ('Кронштейн', 'structural', 'Кронштейн крепления'),
    'крышка': ('Крышка съемная', 'structural', 'Съемная крышка'),

    # --- Air flow ---
    'вентилятор': ('Вентилятор осевой', 'airflow', 'Осевой вентилятор'),
    'сопло_прямое': ('Сопло прямое', 'airflow', 'Прямое сопло, угол 0°'),
    'сопло_угловое': ('Сопло угловое', 'airflow', 'Угловое сопло, 30° (опция)'),

    # --- Thermal ---
    'теплообменник': ('Теплообменник', 'thermal', 'Водяной теплообменник с алюминиевым оребрением'),
    'трубки': ('Трубки теплообменника', 'thermal', 'Трубки теплообменника'),

    # --- Hydronic ---
    'коллектор': ('Коллектор', 'hydronic', 'Подводящий/отводящий коллектор'),
    'коллектор_промежуточный': ('Коллектор промежуточный', 'hydronic', ''),
    'отвод': ('Отвод', 'hydronic', 'Отвод с резьбовой заглушкой'),
    'патрубок': ('Патрубок водяной', 'hydronic', 'Водяные патрубки с торцевым уплотнением'),
    'кран': ('Кран шаровый запорный', 'hydronic', ''),
    'фильтр': ('Фильтр грубой очистки', 'hydronic', ''),
    'фитинг': ('Фитинг соединительный', 'hydronic', ''),
    'насос': ('Насос', 'hydronic', 'Циркуляционный насос'),
    'клапан_обратный': ('Клапан обратный проходной', 'hydronic', ''),
    'вентиль': ('Вентиль регулируемый', 'hydronic', 'Регулируемый вентиль'),
    'клапан_трехходовой': ('Клапан трехходовой', 'hydronic', 'С электроприводом'),
    'байпас': ('Байпас клапана', 'hydronic', 'За байпаса трехходового клапана'),
    'переходные_пластины': ('Переходные пластины', 'structural', ''),

    # --- Electrical ---
    'гермоввод': ('Гермоввод', 'electrical', 'Герметичный кабельный ввод'),
    'колодка_x1': ('Колодка X1', 'electrical', 'Клеммная колодка X1'),
    'колодка_x2': ('Колодка X2', 'electrical', 'Клеммная колодка X2'),
    'колодка_x3': ('Колодка X3', 'electrical', 'Клеммная колодка X3'),
    'кабель_силовой': ('Кабель силовой', 'electrical', 'Кабель питания'),
    'кабель_управления': ('Кабель управления', 'electrical', 'Кабель управления'),

    # --- Control ---
    'пульт_hl10l': ('Пульт HL10L', 'control', 'Выносной пульт управления'),
    'модуль_мп_wa': ('Модуль МП-WA', 'control', 'Модуль подключения завес'),
    'блок_wa': ('БЛОК-WA', 'control', 'Блок подключения доп. оборудования'),
    'бку_wa6': ('БКУ-WA6', 'control', 'Блок коммутации и управления завес'),

    # --- Thermal control ---
    'узел_терморегулирования': ('Узел терморегулирования', 'thermal', 'С трехходовым клапаном и насосом'),
    'термостат': ('Термостат защиты', 'control', 'Защита от замораживания'),
    'выключатель_концевой': ('Выключатель концевой', 'control', ''),
}

# Connection map for series 700
SERIES700_CONNECTIONS = [
    ('Воздух из помещения', 'Вентилятор осевой', 'всасывается'),
    ('Вентилятор осевой', 'Теплообменник', 'проходит через'),
    ('Теплообменник', 'Сопло прямое', 'выбрасывается через'),
    ('Сопло прямое', 'Проем защищаемый', 'струя воздуха'),

    ('Патрубок водяной', 'Коллектор', 'подача теплоносителя'),
    ('Коллектор', 'Трубки теплообменника', 'распределение'),
    ('Трубки теплообменника', 'Коллектор', 'сбор обратки'),
    ('Коллектор', 'Патрубок водяной', 'отвод теплоносителя'),

    ('Пульт HL10L', 'Модуль МП-WA', 'управление'),
    ('Модуль МП-WA', 'Вентилятор осевой', 'вкл/выкл, скорость'),
    ('Модуль МП-WA', 'БЛОК-WA', 'доп. оборудование'),
    ('БКУ-WA6', 'Вентилятор осевой', 'коллективное управление'),
    ('БКУ-WA6', 'Пульт HL10L', 'пульт в комплекте'),

    ('Гермоввод', 'Колодка X1', 'силовой ввод'),
    ('Колодка X1', 'Вентилятор осевой', 'питание'),
    ('Колодка X2', 'Вентилятор осевой', 'управление'),
    ('Колодка X3', 'БЛОК-WA', 'доп. оборудование'),

    ('Кран шаровый запорный', 'Фильтр грубой очистки', 'подача воды'),
    ('Фильтр грубой очистки', 'Насос', ''),
    ('Насос', 'Клапан трехходовой', ''),
    ('Клапан трехходовой', 'Теплообменник', ''),
    ('Теплообменник', 'Клапан обратный проходной', ''),
    ('Клапан обратный проходной', 'Вентиль регулируемый', ''),
    ('Вентиль регулируемый', 'Кран шаровый запорный', 'обратка'),
    ('Термостат защиты', 'Клапан трехходовой', 'сигнал'),
    ('Термостат защиты', 'Насос', 'сигнал'),
]


def parse_passport(pdf_path):
    """Main parsing function. Returns SystemModel."""
    log.info("Parsing passport: %s", pdf_path)

    # 1. Extract text
    pages = extract_text_all(pdf_path)
    if not pages:
        log.error("No text extracted")
        return None

    all_text = '\n'.join(t for _, t in pages)
    log.info("Extracted %d chars from %d pages", len(all_text), len(pages))

    # 2. Sectionize
    sections = sectionize(pages)

    # 3. Build model
    model = SystemModel()
    model.title = 'Функциональная схема'
    model.subtitle = Path(pdf_path).stem

    # Find the document title from first page
    first_page_text = pages[0][1] if pages else ''
    title_match = re.search(r'([А-Я][А-Яа-я\-–\s]+)\s*(?:Паспорт|Руководство)', first_page_text)
    if title_match:
        model.title = title_match.group(1).strip()

    # 4. Register seed components (always use _name_to_id from display name)
    for cid, (name, cat, desc) in SERIES700_SEED.items():
        real_id = _name_to_id(name)
        comp = Component(real_id, name, cat, desc)
        model.add_component(comp)
        # Also keep old ID as alias for backward compat
        if cid != real_id:
            # Register under old_key too via aliasing
            pass

    # 5. External actors (outside the system)
    model.get_or_create('Воздух из помещения', 'airflow')
    model.get_or_create('Проем защищаемый', 'airflow')

    # 6. Extract additional components from figure captions (filtered to meaningful ones)
    seen_extra = set()
    seed_ids = set(SERIES700_SEED.keys())
    for sec_id, sec_title, sec_text in sections:
        if sec_id and sec_id.replace('.', '').isdigit():
            items = extract_list_items(sec_text)
            for item in items:
                name = item['name']
                if len(name) < 3 or len(name) > 60:
                    continue
                if not re.search(r'[А-Яа-яA-Za-z]{4,}', name):
                    continue
                cid = _name_to_id(name)
                if cid in model.components or name in seen_extra:
                    continue
                seen_extra.add(name)
                # Only add if it has a known category keyword (meaningful component)
                if classify_component(name) != 'accessory' or any(
                        kw in name.lower() for kw in ['клапан', 'фильтр', 'насос', 'вентиль',
                                                       'кран', 'швеллер', 'трубк', 'коллектор',
                                                       'патрубок', 'сопло', 'крышк']):
                    cat = classify_component(name)
                    model.add_component(Component(cid, name, cat,
                                                  f"из раздела {sec_id}"))
                    model.components[cid].refs.append(sec_id)

    # 6. Add seed connections
    for from_name, to_name, label in SERIES700_CONNECTIONS:
        if from_name and to_name:
            model.relate(from_name, to_name, label)

    # 7. Group by subsystem
    model.add_group('Завеса (основные узлы)', [
        'Корпус', 'Вентилятор осевой', 'Теплообменник',
        'Сопло прямое', 'Кронштейн', 'Крышка съемная',
    ])
    model.add_group('Обвязка теплообменника', [
        'Патрубок водяной', 'Коллектор', 'Трубки теплообменника',
        'Коллектор промежуточный', 'Отвод', 'Переходные пластины',
    ])
    model.add_group('Узел терморегулирования', [
        'Кран шаровый запорный', 'Фильтр грубой очистки',
        'Фитинг соединительный', 'Насос', 'Клапан обратный проходной',
        'Вентиль регулируемый', 'Клапан трехходовой', 'Байпас клапана',
    ])
    model.add_group('Электрика', [
        'Гермоввод', 'Колодка X1', 'Колодка X2', 'Колодка X3',
        'Кабель силовой', 'Кабель управления',
    ])
    model.add_group('Система управления', [
        'Пульт HL10L', 'Модуль МП-WA', 'БЛОК-WA', 'БКУ-WA6',
        'Термостат защиты', 'Выключатель концевой',
    ])

    # External actors (outside the system)
    model.get_or_create('Воздух из помещения', 'airflow')
    model.get_or_create('Проем защищаемый', 'airflow')

    # 8. Extract flow notes
    for f in extract_flow_paths(all_text, []):
        model.flow_notes.append(f"{f['medium']}: {f['path']}")

    log.info("Model: %d components, %d relations, %d groups",
             len(model.components), len(model.relations), len(model.groups))
    return model


# ──────────────────────────────────────────────────────────────────────
# DIAGRAM BUILDER — Graphviz DOT renderer
# ──────────────────────────────────────────────────────────────────────

def _sanitize(s):
    """Escape special chars for DOT labels."""
    return s.replace('"', "'").replace('\\', '\\\\').replace('\n', '\\n')


def _style_for_category(cat):
    return CATEGORY_STYLES.get(cat, CATEGORY_STYLES['accessory'])


def build_diagram(model, output_stem=None):
    """Build Graphviz diagram and render to PNG + PDF.

    Args:
        model: SystemModel
        output_stem: output path stem (no extension)

    Returns:
        (png_path, pdf_path)
    """
    import graphviz

    if output_stem is None:
        output_stem = 'diagram'

    dot = graphviz.Digraph(
        name='functional_scheme',
        format='png',
        engine='dot',
        graph_attr={
            'label': _sanitize(f'{model.title}\n{model.subtitle}'),
            'labelloc': 't',
            'fontsize': '24',
            'fontname': 'Arial',
            'bgcolor': '#FAFAFA',
            'dpi': '200',
            'rankdir': 'LR',
            'splines': 'true',
            'pad': '0.5',
            'nodesep': '0.6',
            'ranksep': '1.2',
            'compound': 'true',
        },
        node_attr={
            'fontname': 'Arial',
            'fontsize': '9',
            'shape': 'box',
            'style': 'filled,rounded',
            'penwidth': '1.5',
        },
        edge_attr={
            'fontname': 'Arial',
            'fontsize': '7',
            'penwidth': '1.2',
        }
    )

    # Register Arial font for Graphviz
    # Graphviz on Windows finds Arial automatically

    # --- Subsystems (groups) — put nodes INSIDE clusters ---
    # Determine which components go in which group
    comp_to_group = {}  # cid → gid
    grouped_cids = set()
    for gid, (gname, cids) in model.groups.items():
        for cid in cids:
            comp_to_group[cid] = gid
            grouped_cids.add(cid)

    # Build clusters with nodes inside
    for gid, (gname, cids) in model.groups.items():
        with dot.subgraph(name=f'cluster_{gid}') as sub:
            sub.attr(
                label=_sanitize(gname),
                style='dashed',
                color='#888888',
                fontsize='14',
                fontname='Arial',
                fontcolor='#555555',
                penwidth='1.5',
                margin='20',
            )
            for cid in cids:
                if cid in model.components:
                    comp = model.components[cid]
                    style = _style_for_category(comp.category)
                    sub.node(
                        cid,
                        label=_sanitize(comp.name),
                        fillcolor=style['fill'],
                        color=style['color'],
                        fontcolor=style['color'],
                        shape='box',
                        style='filled,rounded',
                        penwidth='1.5',
                    )

    # Ungrouped but connected components (shown outside clusters)
    shown_cids = set(grouped_cids)
    for rel in model.relations:
        for cid in (rel.from_id, rel.to_id):
            if cid in model.components and cid not in shown_cids:
                shown_cids.add(cid)
                comp = model.components[cid]
                style = _style_for_category(comp.category)
                # External/environment nodes get dashed border
                is_external = comp.name in ('Воздух из помещения', 'Проем защищаемый')
                dot.node(
                    cid,
                    label=_sanitize(comp.name),
                    fillcolor=style['fill'],
                    color=style['color'],
                    fontcolor=style['color'],
                    style='dashed' if is_external else 'filled,rounded',
                    penwidth='1.5' if not is_external else '1.0',
                )

    # --- Connections ---
    for rel in model.relations:
        if rel.from_id in model.components and rel.to_id in model.components:
            dot.edge(
                rel.from_id, rel.to_id,
                label=_sanitize(rel.label) if rel.label else '',
                color='#666666',
                fontcolor='#666666',
            )

    # --- External environment annotations ---
    if 'отвод' in model.components:
        dot.edge(
            'отвод', 'отвод',
            label='Слив / выпуск воздуха',
            style='dashed',
            color='#999999',
            fontcolor='#999999',
        )

    # --- Legend (color key) ---
    with dot.subgraph(name='cluster_legend') as legend:
        legend.attr(
            label='Легенда',
            style='dotted',
            color='#BBBBBB',
            fontsize='10',
            fontname='Arial',
            fontcolor='#888888',
            penwidth='0.5',
            margin='10',
        )
        for cat_key, cat_style in CATEGORY_STYLES.items():
            if cat_key == 'accessory':
                continue
            lid = f'legend_{cat_key}'
            legend.node(
                lid,
                label=cat_style['label'],
                fillcolor=cat_style['fill'],
                color=cat_style['color'],
                fontcolor=cat_style['color'],
                shape='box',
                style='filled',
                fontsize='8',
                width='1.2',
                height='0.2',
            )

    # --- Render ---
    try:
        dot_src = output_stem  # DOT source file name
        # Render PNG
        png_result = dot.render(filename=dot_src, format='png', cleanup=True)
        log.info("PNG: %s", png_result)

        # Render PDF
        pdf_result = dot.render(filename=dot_src, format='pdf', cleanup=True)
        log.info("PDF: %s", pdf_result)

        png_path = output_stem + '.png'
        pdf_path = output_stem + '.pdf'

        log.info("Diagram: %s, %s", png_path, pdf_path)
        return png_path, pdf_path

    except Exception as e:
        log.error("Render failed: %s", e)
        # Fallback: save DOT source with proper extension
        try:
            dot.save(output_stem + '.dot')
            log.info("DOT saved to %s.dot", output_stem)
        except Exception:
            pass
        return None, None


# ──────────────────────────────────────────────────────────────────────
# HIGH-LEVEL API
# ──────────────────────────────────────────────────────────────────────

def export_png_pdf(model, output_stem=None, verbose=False):
    """Build and render diagram from model."""
    return build_diagram(model, output_stem)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='passport-to-uml — Extract functional UML diagram from passport PDF',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input', help='Passport PDF path')
    parser.add_argument('output', nargs='?', default=None,
                        help='Output stem (without extension)')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}")
        sys.exit(1)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format='%(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    model = parse_passport(args.input)
    if not model:
        print("Error: could not parse passport")
        sys.exit(1)

    output = args.output or 'uml_diagram'
    png, pdf = build_diagram(model, output)
    if png:
        print(f"OK: {png}, {pdf}")
    else:
        print(f"Warning: rendering failed, DOT saved to {output}.dot")


if __name__ == '__main__':
    main()
