"""Общие помощники для тестов (стандартная библиотека, без внешних зависимостей).

Запуск: ``python -m unittest discover -s tests -t . -v``
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSPORTS_DIR = os.path.join(REPO_ROOT, 'examples', 'passports')

FIXTURES = (
    'vendor_a_teplomash_blok-e_gost.txt',
    'vendor_b_vent-servis_shu-2_tu.txt',
    'vendor_c_klimat-pro_suz-3_tu.txt',
)

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def fixture_path(name):
    return os.path.join(PASSPORTS_DIR, name)


def load_model(name, stem=None):
    """Разобрать фикстуру-паспорт в SystemModel (текстовый путь, без pdfplumber)."""
    from passport_to_uml import parse_passport_text, read_passport_source

    path = fixture_path(name)
    pages = read_passport_source(path)
    return parse_passport_text(pages, stem or os.path.splitext(name)[0])


def names(model):
    """Множество имён компонентов модели."""
    return {comp.name for comp in model.components.values()}


def component_by_name(model, name):
    for comp in model.components.values():
        if comp.name == name:
            return comp
    raise AssertionError(f'в модели нет компонента {name!r}; есть: {sorted(names(model))}')


def links_of(model, name):
    """Сколько связей (входящих + исходящих) у компонента с указанным именем."""
    comp = component_by_name(model, name)
    return sum(1 for rel in model.relations
               if comp.id in (rel.from_id, rel.to_id))


def relation_pairs(model):
    """Связи как множество пар имён ``(откуда, куда)``."""
    return {(model.components[rel.from_id].name,
             model.components[rel.to_id].name)
            for rel in model.relations}
