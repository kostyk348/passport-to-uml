"""Модель: компоненты, группы и поведение связей.

Ключевой кейс среза — «в паспорте нет данных для ребра»: что делает система,
если связь ссылается на незарегистрированный узел. До этого среза ребро молча
исчезало; теперь оно попадает в ``dropped_relations``, в лог и в таблицу связей.
"""

import logging
import unittest

from tests.support import REPO_ROOT  # noqa: F401

from passport_to_uml.engine import Component, SystemModel


class ComponentRegistryTest(unittest.TestCase):
    def test_get_or_create_is_idempotent(self):
        model = SystemModel()
        first = model.get_or_create('Контактор КМ1')
        second = model.get_or_create('Контактор КМ1')
        self.assertIs(first, second)
        self.assertEqual(len(model.components), 1)
        self.assertEqual(first.category, 'electrical')

    def test_has_component_uses_slug_id(self):
        model = SystemModel()
        model.get_or_create('Клеммная колодка X1')
        self.assertTrue(model.has_component('Клеммная колодка X1'))
        self.assertFalse(model.has_component('Клеммная колодка X9'))

    def test_add_component_keeps_insertion_order(self):
        model = SystemModel()
        model.add_component(Component('b', 'Пульт IR03', 'control'))
        model.add_component(Component('a', 'Контактор КМ1', 'electrical'))
        self.assertEqual(list(model.components.keys()), ['b', 'a'])


class RelationTest(unittest.TestCase):
    def _model_with_two(self):
        model = SystemModel()
        model.get_or_create('Концевой выключатель')
        model.get_or_create('Клеммная колодка X1')
        return model

    def test_relate_between_registered_components_returns_true(self):
        model = self._model_with_two()
        self.assertTrue(model.relate('Концевой выключатель', 'Клеммная колодка X1', 'подключен'))
        self.assertEqual(len(model.relations), 1)
        self.assertEqual(model.dropped_relations, [])

    def test_duplicate_relation_merges_labels(self):
        model = self._model_with_two()
        model.relate('Концевой выключатель', 'Клеммная колодка X1', 'подключен')
        model.relate('Концевой выключатель', 'Клеммная колодка X1', 'скорость')
        self.assertEqual(len(model.relations), 1)
        self.assertEqual(model.relations[0].label, 'подключен / скорость')

    def test_missing_endpoint_is_not_silent(self):
        """«В паспорте нет данных для ребра»: ребро не пропадает молча."""
        model = self._model_with_two()
        with self.assertLogs('passport_to_uml.engine', level=logging.WARNING) as logs:
            added = model.relate('Концевой выключатель', 'Клеммная колодка X9')
        self.assertFalse(added)
        self.assertEqual(model.relations, [])
        self.assertEqual(len(model.dropped_relations), 1)
        drop = model.dropped_relations[0]
        self.assertEqual(drop['from'], 'Концевой выключатель')
        self.assertEqual(drop['to'], 'Клеммная колодка X9')
        self.assertIn('не зарегистрирован', drop['reason'])
        self.assertTrue(any('отброшена' in record for record in logs.output))

    def test_dropped_relations_accumulate(self):
        model = self._model_with_two()
        model.relate('Нет такого устройства', 'Клеммная колодка X1')
        model.relate('Концевой выключатель', 'Тоже нет')
        self.assertEqual(len(model.dropped_relations), 2)
        self.assertEqual(len(model.relations), 0)


class GroupTest(unittest.TestCase):
    def test_add_group_assigns_parent_and_skips_unknown(self):
        model = SystemModel()
        model.get_or_create('Контактор КМ1')
        model.get_or_create('Клеммная колодка X1')
        model.add_group('Электрика', ['Контактор КМ1', 'Клеммная колодка X1', 'Нет такого'])
        self.assertEqual(list(model.groups.keys()), ['электрика'])
        self.assertEqual(model.components['контактор_км1'].parent, 'электрика')
        self.assertEqual(len(model.groups['электрика'][1]), 2)

    def test_group_without_known_components_is_not_added(self):
        model = SystemModel()
        model.add_group('Пустая группа', ['Нет такого'])
        self.assertEqual(model.groups, {})


if __name__ == '__main__':
    unittest.main()
