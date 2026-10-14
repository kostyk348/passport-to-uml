#!/usr/bin/env python3
"""Прогон конвейера по нескольким паспортам сразу — замена run_all.py.

``run_all.py`` жёстко привязан к машине автора (``os.environ['USERPROFILE']``,
абсолютные пути ``Downloads/Для функциональных схем``, восемь заранее описанных
seed'ов), поэтому вне Windows он падает ещё на импорте. Этот скрипт делает то же
самое, но честно: берёт паспорта, которые ему передали, и показывает, что из них
извлекается — без seed'ов и без предположений о вёрстке.

    python check_passports.py examples/passports/*.txt --outdir out
    python check_passports.py examples/passports/pdf/*.pdf --outdir out   # нужен pdfplumber

Коды возврата:
  0  все паспорта разобраны (DOT + таблица состава записаны)
  1  хотя бы один паспорт не разобран (причина в выводе)
  2  ошибка аргументов
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from passport_to_uml import (  # noqa: E402
    __version__,
    build_diagram,
    parse_passport_text,
    read_passport_source,
    write_spec_table,
)
from passport_to_uml.sources import PassportSourceError  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

#: Минимум паспортов, который требует срез (разные производители).
MIN_PASSPORTS = 3


def process(path, outdir, render=True):
    """Разобрать один паспорт. Возвращает (строку-итог, код 0/1)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    print('=' * 78)
    print(f'Паспорт: {path}')

    try:
        pages = read_passport_source(path)
    except PassportSourceError as exc:
        print(f'  ОШИБКА: {exc}')
        return None, EXIT_FAILED

    model = parse_passport_text(pages, stem)
    if model is None or not model.components:
        print('  ОШИБКА: компоненты не выделены')
        return None, EXIT_FAILED

    output_stem = os.path.join(outdir, stem)
    spec_paths = write_spec_table(model, output_stem)
    png, pdf = build_diagram(model, output_stem, render=render)

    print(f'  страниц: {len(pages)} | символов: '
          f'{sum(len(text) for _, text in pages)}')
    print(f'  заголовок модели: {model.title}')
    print(f'  компонентов: {len(model.components)} | '
          f'связей: {len(model.relations)} '
          f'(отброшено: {len(model.dropped_relations)}) | '
          f'групп: {len(model.groups)}')
    print(f'  граф:      {output_stem}.dot')
    print(f'  таблица:   {spec_paths["markdown"]}, '
          f'{spec_paths["components_csv"]}, {spec_paths["links_csv"]}')
    if png and pdf:
        print(f'  диаграмма: {png}, {pdf}')
    else:
        print('  диаграмма: не построена (Graphviz недоступен или рендер упал)')

    if model.dropped_relations:
        for drop in model.dropped_relations[:5]:
            print(f'  отброшена связь: {drop["from"]} → {drop["to"]} '
                  f'({drop["reason"]})')

    summary = {
        'passport': stem,
        'components': len(model.components),
        'relations': len(model.relations),
        'dropped': len(model.dropped_relations),
        'groups': len(model.groups),
        'rendered': bool(png and pdf),
    }
    return summary, EXIT_OK


def print_summary(summaries):
    print('=' * 78)
    print(f'ИТОГО по {len(summaries)} паспортам (passport-to-uml {__version__})')
    header = ('паспорт', 'компонентов', 'связей', 'отброшено', 'групп', 'рендер')
    widths = (46, 12, 8, 11, 7, 8)
    print(''.join(str(cell).ljust(width) for cell, width in zip(header, widths)))
    print('-' * sum(widths))
    for row in summaries:
        cells = (row['passport'], row['components'], row['relations'],
                 row['dropped'], row['groups'],
                 'да' if row['rendered'] else 'нет')
        print(''.join(str(cell).ljust(width) for cell, width in zip(cells, widths)))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='check_passports.py',
        description='Прогнать конвейер passport-to-uml по нескольким паспортам '
                    'и напечатать сводку (замена run_all.py).')
    parser.add_argument('passports', nargs='*',
                        help='паспорта: .pdf (нужен pdfplumber), .txt, .html')
    parser.add_argument('--outdir', default='out',
                        help='каталог для DOT/таблиц/диаграмм (по умолчанию out/)')
    parser.add_argument('--no-render', action='store_true',
                        help='не вызывать Graphviz (только DOT и таблицы)')
    parser.add_argument('--min', type=int, default=MIN_PASSPORTS,
                        help=f'предупреждать, если паспортов меньше (по умолчанию '
                             f'{MIN_PASSPORTS})')
    args = parser.parse_args(argv)

    if not args.passports:
        parser.print_usage(sys.stderr)
        print('Ошибка: не передано ни одного паспорта', file=sys.stderr)
        return EXIT_USAGE

    if len(args.passports) < args.min:
        print(f'Внимание: паспортов {len(args.passports)}, а срез требует '
              f'минимум {args.min} (разные производители)', file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)

    summaries = []
    failed = []
    for path in args.passports:
        summary, code = process(path, args.outdir, render=not args.no_render)
        if code == EXIT_OK and summary:
            summaries.append(summary)
        else:
            failed.append(path)

    if summaries:
        print_summary(summaries)

    if failed:
        print()
        print('Не разобраны:', ', '.join(failed), file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
