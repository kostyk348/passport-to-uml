"""Проверка на трёх паспортах разных производителей (разные вёрстки/терминология).

Аудит музея отмечал, что проверок на разных производителях в проекте нет.
Здесь зафиксирован фактический результат по каждому паспорту: что извлекается,
а что теряется. Тесты-«known_gap» описывают текущее (неправильное) поведение —
они должны «упасть», когда правила починят, и напомнить обновить README.
"""

import unittest

from tests.support import FIXTURES, links_of, load_model, names, relation_pairs  # noqa: F401

from passport_to_uml.engine import link_rows, render_dot, spec_rows

VENDOR_A = FIXTURES[0]
VENDOR_B = FIXTURES[1]
VENDOR_C = FIXTURES[2]


class ThreePassportsTest(unittest.TestCase):
    """Все три паспорта должны доходить до графа и таблицы состава."""

    @classmethod
    def setUpClass(cls):
        cls.models = {name: load_model(name) for name in FIXTURES}

    def test_every_passport_yields_components_relations_and_dot(self):
        for name, model in self.models.items():
            with self.subTest(passport=name):
                self.assertGreaterEqual(len(model.components), 5)
                self.assertGreaterEqual(len(model.relations), 1)
                dot = render_dot(model)
                self.assertIn('digraph functional_scheme {', dot)
                self.assertEqual(dot.count(' -> '), len(model.relations))

    def test_terminology_differs_between_manufacturers(self):
        """Три паспорта пользуются разными терминами — это и есть суть проверки."""
        a, b, c = (names(self.models[name]) for name in FIXTURES)
        self.assertIn('Клеммная колодка X1', a)          # А: «клеммная колодка»
        self.assertIn('Клеммник X2', b)                  # B: «клеммник»
        self.assertIn('Контроллер C1000', c)             # C: «контроллер»
        self.assertNotIn('Клеммник X2', a)
        self.assertNotIn('Контроллер C1000', b)


class VendorATest(unittest.TestCase):
    """ЗАО «Тепломаш», ГОСТ-стиль: нумерованные пункты «1 - Название;»."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(VENDOR_A)

    def test_title_extracted_from_first_page(self):
        self.assertEqual(self.model.title,
                         'БЛОК ПОДКЛЮЧЕНИЯ КОНЦЕВОГО ВЫКЛЮЧАТЕЛЯ БЛОК-Е')

    def test_expected_components(self):
        found = names(self.model)
        for expected in ('Контактор КМ1', 'Клеммная колодка X1',
                         'Клеммная колодка X3', 'Концевой выключатель',
                         'Внешний термостат', 'Пульт IR03',
                         'Сезонный переключатель S1'):
            self.assertIn(expected, found)

    def test_relations_to_terminal_blocks(self):
        self.assertEqual(
            relation_pairs(self.model),
            {('Концевой выключатель', 'Клеммная колодка X1'),
             ('Внешний термостат', 'Клеммная колодка X3')})

    def test_known_gap_digital_designation_loses_its_link(self):
        """«Пульт IR03» есть в составе, но фраза о подключении не распознана."""
        self.assertEqual(links_of(self.model, 'Пульт IR03'), 0)

    def test_known_defect_first_component_glues_header_lines(self):
        """Заголовок страницы склеивается в один «компонент» (жадное правило)."""
        first = list(self.model.components.values())[0]
        self.assertIn('Паспорт', first.name)
        self.assertEqual(links_of(self.model, first.name), 0)

    def test_known_defect_hardcoded_six_curtains(self):
        """Завес в паспорте не шесть: 1..6 подставляются по умолчанию."""
        curtains = [name for name in names(self.model) if name.startswith('Завеса ')]
        self.assertEqual(len(curtains), 6)


class VendorBTest(unittest.TestCase):
    """ООО «Вент-Сервис», ТУ-стиль: «В состав изделия входят: – …;», «клеммник»."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(VENDOR_B)

    def test_known_gap_title_falls_back_when_designation_has_digits(self):
        self.assertEqual(self.model.title, 'Функциональная схема')

    def test_expected_components(self):
        found = names(self.model)
        for expected in ('Шкаф управления ЩУ-2', 'Клеммник X2', 'Клеммник X9',
                         'Терморегулятор ТР-1', 'Насос циркуляционный',
                         'Датчик температуры наружного воздуха'):
            self.assertIn(expected, found)

    def test_working_relation_uses_klemmnaya_kolodka_wording(self):
        self.assertIn(('Насос циркуляционный', 'Клеммная колодка X5'),
                      relation_pairs(self.model))

    def test_known_gap_klemmnik_terminology_produces_noisy_component(self):
        """«клеммнику X2» → ребро строится, но узел-источник — мусорная строка."""
        self.assertIn('Терморегулятор ТР-1 должен быть', names(self.model))
        self.assertIn(('Терморегулятор ТР-1 должен быть', 'Клеммная колодка X2'),
                      relation_pairs(self.model))

    def test_known_gap_real_terminal_blocks_stay_unconnected(self):
        """Паспортные «Клеммник X2»/«X9» остаются без связей, а в графе появляется
        выдуманный узел «Клеммная колодка X2»."""
        self.assertEqual(links_of(self.model, 'Клеммник X2'), 0)
        self.assertEqual(links_of(self.model, 'Клеммник X9'), 0)
        self.assertIn('Клеммная колодка X2', names(self.model))

    def test_known_gap_pusatel_skipped_and_renamed_to_kontaktor(self):
        """«Магнитный пускатель КМ2» отброшен как accessory, зато появился
        выдуманный «Контактор КМ2» (правило КМ\\d+)."""
        found = names(self.model)
        self.assertNotIn('Магнитный пускатель КМ2', found)
        self.assertIn('Контактор КМ2', found)

    def test_zero_link_components_are_visible_in_spec_table(self):
        rows = {row['name']: row for row in spec_rows(self.model)}
        self.assertEqual(rows['Клеммник X2']['links'], 0)
        self.assertEqual(rows['Клеммник X9']['links'], 0)


class VendorCTest(unittest.TestCase):
    """ООО «Климат-Про», евро-стиль: пункты «•», десятичная нумерация."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(VENDOR_C)

    def test_expected_components_from_bullets(self):
        found = names(self.model)
        for expected in ('Контроллер C1000', 'Дисплей LCD-200',
                         'Датчик температуры', 'Вентилятор', 'Клапан К1',
                         'Термостат Т2'):
            self.assertIn(expected, found)

    def test_two_relations_extracted(self):
        self.assertEqual(
            relation_pairs(self.model),
            {('Контроллер C1000', 'Клеммная колодка X7'),
             ('Датчик температуры', 'Клеммная колодка X8')})

    def test_flow_note_extracted(self):
        self.assertEqual(len(self.model.flow_notes), 1)
        self.assertIn('фильтр', self.model.flow_notes[0])

    def test_known_gap_terminal_designation_with_digit_loses_link(self):
        self.assertEqual(links_of(self.model, 'Термостат Т2'), 0)

    def test_known_defect_relay_k1_invented_from_valve_k1(self):
        """«Клапан К1» порождает выдуманное «Реле К1» (правило К\\d+)."""
        found = names(self.model)
        self.assertIn('Клапан К1', found)
        self.assertIn('Реле К1', found)
        self.assertEqual(links_of(self.model, 'Реле К1'), 0)


class DroppedRelationsTest(unittest.TestCase):
    """Случай «в паспорте нет данных для ребра» на всех трёх паспортах."""

    def test_no_link_is_dropped_silently_for_three_passports(self):
        for name in FIXTURES:
            with self.subTest(passport=name):
                model = load_model(name)
                # Ребро на незарегистрированный узел не пропадает молча:
                model.relate('Нет такого устройства', 'Клеммная колодка X1')
                dropped = [row for row in link_rows(model)
                           if row['status'] == 'отброшена']
                self.assertEqual(len(dropped), len(model.dropped_relations))
                self.assertEqual(len(dropped), 1)
                self.assertIn('не зарегистрирован', dropped[0]['reason'])


if __name__ == '__main__':
    unittest.main()
