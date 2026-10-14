"""CLI-контракт: вход, выход, коды возврата и сообщения об ошибках.

Коды: 0 — успех, 1 — нет входа, 2 — ошибка аргументов, 3 — текст не извлечён,
4 — рендер PNG/PDF не выполнен (DOT и таблица всё равно записаны).
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from tests.support import REPO_ROOT, fixture_path  # noqa: F401

from passport_to_uml.engine import (
    EXIT_INPUT_MISSING,
    EXIT_NO_TEXT,
    EXIT_OK,
    EXIT_RENDER_FAILED,
    EXIT_USAGE,
    run_cli,
)

FIXTURE = fixture_path('vendor_a_teplomash_blok-e_gost.txt')
FIXTURE_B = fixture_path('vendor_b_vent-servis_shu-2_tu.txt')


def renderer_available():
    """Есть ли и python-модуль graphviz, и бинарник dot."""
    try:
        import graphviz  # noqa: F401
    except ImportError:
        return False
    return shutil.which('dot') is not None


class CliSuccessTest(unittest.TestCase):
    def test_txt_passport_with_no_render_writes_dot_and_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            code = run_cli([FIXTURE, '--outdir', tmp, '--no-render'],
                           stdout=out, stderr=io.StringIO())
            self.assertEqual(code, EXIT_OK)
            for suffix in ('.dot', '.spec.md', '.spec.csv', '.links.csv'):
                path = os.path.join(tmp, 'vendor_a_teplomash_blok-e_gost' + suffix)
                self.assertTrue(os.path.exists(path), path)
            text = out.getvalue()
            self.assertIn('passport-to-uml', text)
            self.assertIn('Компонентов: ', text)
            self.assertIn('Граф (DOT): ', text)
            self.assertIn('Диаграмма: не строилась (--no-render)', text)

    def test_explicit_output_stem_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run_cli([FIXTURE_B, 'diagram', '--outdir', tmp, '--no-render'],
                           stdout=io.StringIO(), stderr=io.StringIO())
            self.assertEqual(code, EXIT_OK)
            self.assertTrue(os.path.exists(os.path.join(tmp, 'diagram.dot')))
            self.assertTrue(os.path.exists(os.path.join(tmp, 'diagram.spec.md')))

    def test_quiet_suppresses_summary_but_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            code = run_cli([FIXTURE, '--outdir', tmp, '--no-render', '--quiet'],
                           stdout=out, stderr=io.StringIO())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(out.getvalue(), '')
            self.assertTrue(
                os.path.exists(os.path.join(tmp, 'vendor_a_teplomash_blok-e_gost.dot')))

    def test_render_exit_code_depends_on_graphviz(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run_cli([FIXTURE, '--outdir', tmp], stdout=io.StringIO(),
                           stderr=io.StringIO())
            expected = EXIT_OK if renderer_available() else EXIT_RENDER_FAILED
            self.assertEqual(code, expected)
            # DOT пишется в любом случае: граф не теряется без рендера.
            self.assertTrue(
                os.path.exists(os.path.join(tmp, 'vendor_a_teplomash_blok-e_gost.dot')))


class CliErrorTest(unittest.TestCase):
    def test_missing_input_returns_1(self):
        err = io.StringIO()
        code = run_cli(['нет-такого-паспорта.pdf'], stdout=io.StringIO(), stderr=err)
        self.assertEqual(code, EXIT_INPUT_MISSING)
        self.assertIn('не найден', err.getvalue())

    def test_directory_as_input_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            code = run_cli([tmp], stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_INPUT_MISSING)
            self.assertIn('каталог', err.getvalue())

    def test_broken_pdf_returns_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, 'битый-паспорт.pdf')
            with open(broken, 'wb') as fh:
                fh.write(b'%PDF-1.4 not a real PDF body \x00\x01\x02\xff')
            err = io.StringIO()
            code = run_cli([broken, '--outdir', tmp], stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_NO_TEXT)
            self.assertTrue(err.getvalue().startswith('Ошибка:'), err.getvalue())

    def test_empty_file_returns_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, 'пусто.txt')
            open(empty, 'w').close()
            err = io.StringIO()
            code = run_cli([empty, '--outdir', tmp], stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_NO_TEXT)
            self.assertIn('пустой', err.getvalue())

    def test_text_without_components_returns_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = os.path.join(tmp, 'нет-состава.txt')
            with open(blank, 'w', encoding='utf-8') as fh:
                fh.write('1 Общие сведения\nИзделие предназначено для чего-то.\n')
            err = io.StringIO()
            code = run_cli([blank, '--outdir', tmp], stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_NO_TEXT)
            self.assertIn('ни одного компонента', err.getvalue())

    def test_missing_arguments_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            run_cli([], stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(cm.exception.code, EXIT_USAGE)

    def test_help_lists_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                run_cli(['--help'], stdout=out, stderr=io.StringIO())
        self.assertEqual(cm.exception.code, EXIT_OK)
        self.assertIn('коды возврата', out.getvalue())
        self.assertIn('рендер PNG/PDF не выполнен', out.getvalue())


if __name__ == '__main__':
    unittest.main()
