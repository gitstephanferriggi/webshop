"""Customer-facing Bolt departments; leaf IDs stay stable for product assignments."""
DEPARTMENTS = (
    ('indoor', 'Indoor plants', {'Cacti', 'Carnivorous plants', 'Foliage Plants', 'Indoor Bonsai', 'Indoor Palms', 'Succulents'}),
    ('outdoor', 'Outdoor plants', {'Citrus Trees', 'Climbers', 'Flowering Plants', 'Fruit Trees', 'Perennial', 'Seasonal Plants', 'Shrub Roses', 'Shrubs'}),
    ('pots', 'Pots & planters', {'Balcony Pots', 'Glazed Ceramic Pots', 'Hanging Pots', 'Round Pots'}),
    ('grow', 'Grow your own', {'Fruit & Vegetable Seeds', 'Herbs Pot 14 cm'}),
    ('care', 'Soil & plant care', {'Fertilisers', 'Gravel & Pebbles', 'Plant Protection Products', 'Soil & Substrate'}),
    ('tools', 'Tools & watering', {'Drip', 'Gloves', 'Hose Fittings', 'Hose Kits', 'Hoses & Spray Pistols', 'Programmers', 'Shears', 'Sprinklers', 'Watering Cans, Sprayers & Pressure Pumps'}),
)


def category_tree(leaves):
    """Group known ERP categories; keep new/unmapped groups visible under Other."""
    remaining = {leaf['external_id']: leaf for leaf in leaves}
    result = []
    for slug, label, groups in DEPARTMENTS:
        children = [leaf for leaf in remaining.values() if leaf['name'].get('en-US') in groups]
        if children:
            result.append({'external_id': 'callus-' + slug, 'name': {'en-US': label},
                           'sub_categories': sorted(children, key=lambda leaf: leaf['name']['en-US'])})
            for leaf in children:
                del remaining[leaf['external_id']]
    if remaining:
        result.append({'external_id': 'callus-other', 'name': {'en-US': 'Other garden products'},
                       'sub_categories': sorted(remaining.values(), key=lambda leaf: leaf['name'].get('en-US', ''))})
    return result
