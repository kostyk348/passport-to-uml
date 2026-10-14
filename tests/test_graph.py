"""Граф и таблица состава: DOT-исходник (stdlib) + markdown/CSV.

Граф проверяется как артефакт: состав узлов и рёбер сверяется с моделью,
а сам DOT — на структурную целостность (парные скобки, кавычки, «;» в конце
инструкций). Инструмент Graphviz для этих тестов не нужен.
"""

import csv
import os
import tempfile
import unittest

from tests.support import REPO_ROOT, load_model  # noqa: F401

from passport_to_uml.engine import (
    CATEGORY_STYLES,
    parse_passport_text,
    render_dot,
    render_spec_markdown,
    spec_rows,
    link_rows,
    write_spec_table,
)

MINI_PASSPORT = """\
БЛОК ПОДКЛЮЧЕНИЯ КОНЦЕВОГО ВЫКЛЮЧАТЕЛЯ БЛОК-Е
Паспорт

3 Устройство и работа изделия
3.1 Состав изделия
1 - Контактор КМ1;
2 - Клеммная колодка X1;
3 - Концевой выключатель;

4 Указания по монтажу
Монтаж выполняется по настоящему руководству.
Концевой выключатель должен быть подключен к клеммной колодке X1.
"""


def mini_model():
    return parse_passport_text([(1, MINI_PASSPORT)], 'mini')


class DotSanityTest(unittest.TestCase):
    def assert_dot_is_sane(self, dot):
        self.assertTrue(dot.startswith('digraph functional_scheme {'))
        self.assertTrue(dot.rstrip().endswith('}'))
        self.assertEqual(dot.count('{'), dot.count('}'))
        for number, line in enumerate(dot.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            self.assertEqual(stripped.count('"') % 2, 0,
                             f'непарные кавычки в строке {number}: {line!r}')
            self.assertTrue(stripped.endswith((';', '{', '}')),
                            f'строка {number} не завершена «;»/«{{»/«}}»: {line!r}')

    def test_dot_is_structurally_valid(self):
        self.assert_dot_is_sane(render_dot(mini_model()))

    def test_dot_is_deterministic(self):
        model = mini_model()
        self.assertEqual(render_dot(model), render_dot(model))

    def test_quotes_in_names_are_escaped(self):
        model = mini_model()
        model.get_or_create('Пульт "IR03"')
        model.relate('Пульт "IR03"', 'Клеммная колодка X1')
        dot = render_dot(model)
        self.assert_dot_is_sane(dot)
        self.assertNotIn('"IR03"', dot)
        self.assertIn("Пульт 'IR03'", dot)


class DotContentTest(unittest.TestCase):
    def setUp(self):
        self.model = mini_model()
        self.dot = render_dot(self.model)

    def test_every_relation_becomes_one_edge(self):
        self.assertEqual(self.dot.count(' -> '), len(self.model.relations))
        self.assertIn('"концевой_выключатель" -> "клеммная_колодка_x1"', self.dot)

    def test_grouped_components_go_into_cluster(self):
        self.assertIn('subgraph "cluster_электрика"', self.dot)
        self.assertIn('"контактор_км1" [label="Контактор КМ1"', self.dot)

    def test_legend_lists_categories_except_accessory(self):
        self.assertIn('subgraph "cluster_legend"', self.dot)
        for category, style in CATEGORY_STYLES.items():
            if category == 'accessory':
                self.assertNotIn(f'legend_{category}', self.dot)
            else:
                self.assertIn(f'legend_{category}', self.dot)
                self.assertIn(style['label'], self.dot)

    def test_label_carries_counts_and_dropped_number(self):
        self.assertIn('Компонентов:', self.dot)
        self.assertNotIn('отброшено', self.dot)
        model = mini_model()
        model.relate('Концевой выключатель', 'Клеммная колодка X9')
        self.assertIn('отброшено: 1', render_dot(model))

    def test_unconnected_component_is_not_a_node(self):
        model = mini_model()
        model.get_or_create('Дисплей LCD-200', 'control')
        dot = render_dot(model)
        self.assertNotIn('дисплей_lcd_200', dot)
        self.assertEqual(dot.count(' [label='), dot.count(' [label='))


class SpecTableTest(unittest.TestCase):
    def setUp(self):
        self.model = mini_model()

    def test_spec_rows_follow_component_order_with_group_and_links(self):
        rows = spec_rows(self.model)
        self.assertEqual(len(rows), len(self.model.components))
        first = rows[0]
        self.assertEqual(sorted(first.keys()),
                         sorted(['no', 'id', 'name', 'category', 'category_label',
                                 'group', 'refs', 'links', 'description']))
        by_name = {row['name']: row for row in rows}
        self.assertEqual(by_name['Контактор КМ1']['group'], 'Электрика')
        self.assertEqual(by_name['Контактор КМ1']['links'], 0)
        self.assertEqual(by_name['Концевой выключатель']['links'], 1)
        self.assertEqual(by_name['Клеммная колодка X1']['category_label'],
                         CATEGORY_STYLES['electrical']['label'])

    def test_link_rows_mark_dropped_edges(self):
        self.model.relate('Концевой выключатель', 'Клеммная колодка X9')
        rows = link_rows(self.model)
        self.assertEqual([row['status'] for row in rows], ['принята', 'отброшена'])
        self.assertIn('не зарегистрирован', rows[1]['reason'])
        self.assertEqual(rows[1]['no'], 2)

    def test_markdown_has_both_tables(self):
        md = render_spec_markdown(self.model)
        self.assertIn('| № | ID | Наименование |', md)
        self.assertIn('| № | Откуда | Куда |', md)
        self.assertIn(f'компонентов: {len(self.model.components)}', md)
        self.assertIn(f'связей: {len(self.model.relations)} (отброшено: 0)', md)

    def test_pipe_in_name_does_not_break_markdown(self):
        self.model.get_or_create('Пульт | IR03', 'control')
        md = render_spec_markdown(self.model)
        row = [line for line in md.splitlines() if 'IR03' in line][0]
        self.assertIn('Пульт \\| IR03', row)

    def test_write_spec_table_creates_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = os.path.join(tmp, 'diagram')
            paths = write_spec_table(self.model, stem)
            self.assertEqual(sorted(paths.keys()),
                             ['components_csv', 'links_csv', 'markdown'])
            for path in paths.values():
                self.assertTrue(os.path.getsize(path) > 0, path)

            with open(paths['components_csv'], encoding='utf-8-sig') as fh:
                rows = list(csv.reader(fh, delimiter=';'))
            self.assertEqual(len(rows), len(self.model.components) + 1)
            self.assertEqual(rows[0][0], 'no')
            self.assertEqual(rows[1][2], list(self.model.components.values())[0].name)

            with open(paths['links_csv'], encoding='utf-8-sig') as fh:
                link_rows_csv = list(csv.reader(fh, delimiter=';'))
            self.assertEqual(link_rows_csv[0], ['no', 'from', 'to', 'label',
                                                'status', 'reason'])
            self.assertEqual(len(link_rows_csv), len(self.model.relations) + 1)

    def test_three_passport_fixtures_write_dot_and_table_without_graphviz(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('vendor_a_teplomash_blok-e_gost.txt',
                         'vendor_b_vent-servis_shu-2_tu.txt',
                         'vendor_c_klimat-pro_suz-3_tu.txt'):
                model = load_model(name)
                stem = os.path.join(tmp, name[:-4])
                dot_path = stem + '.dot'
                with open(dot_path, 'w', encoding='utf-8') as fh:
                    fh.write(render_dot(model))
                paths = write_spec_table(model, stem)
                self.assertTrue(os.path.getsize(dot_path) > 0)
                self.assertTrue(os.path.getsize(paths['markdown']) > 0)


if __name__ == '__main__':
    unittest.main()
