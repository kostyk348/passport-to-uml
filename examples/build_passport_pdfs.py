#!/usr/bin/env python3
"""Собрать PDF-версии паспортов-фикстур (нужен LibreOffice ``soffice``).

Фикстуры в ``examples/passports/*.txt`` — три паспорта разных производителей
с разной вёрсткой и терминологией. Чтобы прогнать конвейер ровно так, как он
работает с настоящими документами (через PDF и pdfplumber), их можно
отконвертировать в PDF:

    python examples/build_passport_pdfs.py            # → examples/passports/pdf/
    python check_passports.py examples/passports/pdf/*.pdf

Скрипт не входит в зависимости пакета: LibreOffice нужен только для этой
подготовки, сам конвейер рендерит диаграммы через Graphviz.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, 'passports')
DEFAULT_OUT = os.path.join(SOURCES, 'pdf')

FIXTURES = (
    'vendor_a_teplomash_blok-e_gost.txt',
    'vendor_b_vent-servis_shu-2_tu.txt',
    'vendor_c_klimat-pro_suz-3_tu.txt',
)


def find_soffice():
    for name in ('soffice', 'libreoffice'):
        found = shutil.which(name)
        if found:
            return found
    return None


def convert(soffice, source, outdir):
    cmd = [soffice, '--headless', '--convert-to', 'pdf',
           '--outdir', outdir, source]
    result = subprocess.run(cmd, capture_output=True, text=True)
    pdf_path = os.path.join(
        outdir, os.path.splitext(os.path.basename(source))[0] + '.pdf')
    ok = result.returncode == 0 and os.path.exists(pdf_path)
    return ok, pdf_path, (result.stdout + result.stderr).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--outdir', default=DEFAULT_OUT)
    parser.add_argument('sources', nargs='*', default=None,
                        help='по умолчанию — все фикстуры из examples/passports/')
    args = parser.parse_args(argv)

    soffice = find_soffice()
    if not soffice:
        print('Ошибка: не найден soffice/libreoffice. Установите LibreOffice '
              'или запустите конвейер прямо по .txt-фикстурам.', file=sys.stderr)
        return 1

    sources = args.sources or [os.path.join(SOURCES, name) for name in FIXTURES]
    os.makedirs(args.outdir, exist_ok=True)

    failed = 0
    for source in sources:
        if not os.path.exists(source):
            print(f'Ошибка: нет файла {source}', file=sys.stderr)
            failed += 1
            continue
        ok, pdf_path, log = convert(soffice, source, args.outdir)
        if ok:
            print(f'OK: {pdf_path} '
                  f'({os.path.getsize(pdf_path)} байт)')
        else:
            print(f'Ошибка конвертации {source}: {log}', file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
