import unittest
from webshop.bolt_integration.categories import category_tree, DEPARTMENTS

class CategoryTests(unittest.TestCase):
    def leaf(self, name):
        return {'external_id': name, 'name': {'en-US': name}, 'external_provider_ids': ['test']}
    def test_all_known_groups_are_preserved_once_and_scoped(self):
        names = [name for _, _, groups in DEPARTMENTS for name in groups]
        self.assertEqual(len(names), len(set(names)))
        leaves = [self.leaf(name) for name in names]
        tree = category_tree(leaves)
        self.assertEqual(len(tree), 6)
        actual = [leaf for parent in tree for leaf in parent['sub_categories']]
        self.assertCountEqual(actual, leaves)
    def test_unknown_group_is_not_misclassified_as_a_plant(self):
        tree = category_tree([self.leaf('New material')])
        self.assertEqual(tree[0]['external_id'], 'callus-other')
    def test_empty_categories_omitted(self):
        self.assertEqual(category_tree([]), [])
        tree = category_tree([self.leaf('Cacti')])
        self.assertEqual([p['external_id'] for p in tree], ['callus-indoor'])
