"""Правила извлечения: секции, классификация, списки, терминалы, заголовок.

Здесь же зафиксированы (characterization-тестами) известные пробелы правил v1.2 —
они помечены ``known_gap`` в имени теста и описаны в README, раздел
«Известные ограничения».
"""

import unittest

from tests.support import REPO_ROOT  # noqa: F401  (кладёт корень репозитория в sys.path)

from passport_to_uml.engine import (
    classify_component,
    extract_component_from_section4,
    extract_flow_paths,
    extract_list_items,
    extract_terminal_connections,
    get_device_title,
    sectionize,
)


class SectionizeTest(unittest.TestCase):
    def test_numbered_headings_become_sections(self):
        sections = sectionize([(1, '1 Общие сведения\nтекст\n3.1 Состав изделия\n1 - Контактор КМ1;')])
        ids = [sec[0] for sec in sections]
        titles = [sec[1] for sec in sections]
        self.assertEqual(ids, ['1', '3.1'])
        self.assertEqual(titles, ['Общие сведения', 'Состав изделия'])

    def test_text_before_first_heading_goes_to_preamble(self):
        sections = sectionize([(1, 'ПАСПОРТ\nИзготовитель\n1 Общие сведения\nтекст')])
        self.assertEqual(sections[0][0], 'preamble')
        self.assertIn('ПАСПОРТ', sections[0][2])

    def test_decimal_heading_is_recognized(self):
        sections = sectionize([(1, '2.1 В изделие установлены:\n• Контроллер C1000;')])
        self.assertEqual(sections[-1][0], '2.1')


class ClassifyComponentTest(unittest.TestCase):
    def test_electrical_terms(self):
        self.assertEqual(classify_component('Контактор КМ1'), 'electrical')
        self.assertEqual(classify_component('Клеммная колодка X1'), 'electrical')
        self.assertEqual(classify_component('Клеммник X2'), 'electrical')

    def test_control_thermal_hydronic_airflow(self):
        self.assertEqual(classify_component('Пульт IR03'), 'control')
        self.assertEqual(classify_component('Терморегулятор ТР-1'), 'thermal')
        self.assertEqual(classify_component('Насос циркуляционный'), 'hydronic')
        self.assertEqual(classify_component('Вентилятор'), 'airflow')

    def test_unknown_name_is_accessory(self):
        self.assertEqual(classify_component('Загадочная деталь'), 'accessory')

    def test_known_gap_pusatel_is_not_recognized(self):
        """«Магнитный пускатель» — синоним контактора, но в словаре его нет."""
        self.assertEqual(classify_component('Магнитный пускатель КМ2'), 'accessory')


class ListItemsTest(unittest.TestCase):
    def test_figure_list_and_bullet_items(self):
        text = '1 - Сезонный переключатель S1;\n2 - Контактор КМ1;\n– Клеммник X2;\n• Контроллер C1000;\n'
        items = extract_list_items(text)
        self.assertEqual(
            [(item['ref'], item['name'], item['source']) for item in items],
            [('1', 'Сезонный переключатель S1', 'figure_list'),
             ('2', 'Контактор КМ1', 'figure_list'),
             ('', 'Клеммник X2', 'bullet'),
             ('', 'Контроллер C1000', 'bullet')],
        )

    def test_instruction_like_bullet_is_skipped(self):
        items = extract_list_items('– Проверить затяжку клемм;\n– Клеммник X2;\n')
        self.assertEqual([item['name'] for item in items], ['Клеммник X2'])


class TerminalConnectionsTest(unittest.TestCase):
    def test_should_be_connected_to_terminal_block(self):
        pairs = extract_terminal_connections(
            'Концевой выключатель должен быть подключен к клеммной колодке X1.')
        self.assertEqual(pairs, [('Концевой выключатель', 'X1', 'подключен')])

    def test_short_form_connected_to_terminal(self):
        pairs = extract_terminal_connections('Контроллер C1000 подключен к X7.')
        self.assertEqual(pairs, [('Контроллер C1000', 'X7', 'подключен')])

    def test_known_gap_adjective_after_noun_breaks_match(self):
        """В правиле перечислены «насос», «датчик» и т. п., но только в конце имени."""
        self.assertEqual(
            extract_terminal_connections(
                'Насос циркуляционный должен быть подключен к клеммной колодке X5.'),
            [])

    def test_known_gap_designation_with_digits_breaks_match(self):
        """«Пульт IR03» / «Термостат Т2» — цифры в обозначении ломают правило."""
        self.assertEqual(
            extract_terminal_connections(
                'Пульт IR03 должен быть подключен к клеммной колодке X1.'),
            [])

    def test_known_gap_alternative_terminology_produces_noisy_edge(self):
        """«клеммник» вместо «клеммной колодки»: ребро строится, но имя устройства мусорное."""
        pairs = extract_terminal_connections(
            'Терморегулятор ТР-1 должен быть подключен к клеммнику X2.')
        self.assertEqual(pairs, [('Терморегулятор ТР-1 должен быть', 'X2', 'подключен')])

    def test_known_gap_plain_connected_to_klemmnaya_kolodka_misses(self):
        """Без «должен быть» шаблон «...подключен к клеммной колодке X3» не ловится."""
        self.assertEqual(
            extract_terminal_connections(
                'Воздушный клапан подключен к клеммной колодке X3.'),
            [])


class Section4ItemsTest(unittest.TestCase):
    def test_items_after_vhodyat_are_extracted(self):
        self.assertEqual(
            extract_component_from_section4(
                'В состав изделия входят: – Шкаф управления ЩУ-2; – Клеммник X2;'),
            ['Шкаф управления ЩУ-2', 'Клеммник X2'])

    def test_lowercase_items_rejected(self):
        self.assertEqual(
            extract_component_from_section4(
                'В комплект поставки входят: – кронштейн; – прокладка уплотнительная;'),
            [])


class DeviceTitleTest(unittest.TestCase):
    def test_title_before_pasport_word(self):
        self.assertEqual(
            get_device_title('БЛОК ПОДКЛЮЧЕНИЯ КОНЦЕВОГО ВЫКЛЮЧАТЕЛЯ БЛОК-Е\nПаспорт\nРедакция'),
            'БЛОК ПОДКЛЮЧЕНИЯ КОНЦЕВОГО ВЫКЛЮЧАТЕЛЯ БЛОК-Е')

    def test_known_gap_title_with_digits_not_extracted(self):
        self.assertIsNone(get_device_title('ПАСПОРТ\nШКАФ УПРАВЛЕНИЯ ЩУ-2 Паспорт\nТУ 4863'))
        self.assertIsNone(get_device_title('СИСТЕМА УПРАВЛЕНИЯ ЗАВЕСОЙ СУЗ-3 Паспорт\nРедакция 3'))


class FlowPathsTest(unittest.TestCase):
    def test_airflow_sentence_yields_note(self):
        notes = extract_flow_paths(
            'Воздух из помещения поступает через завесу и подается в защищаемый проем.', [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['medium'], 'воздух')
        self.assertIn('завесу', notes[0]['path'])


if __name__ == '__main__':
    unittest.main()
