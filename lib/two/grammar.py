"""
Utilities for pronouns and other English grammatical tricks.
"""

pronoun_map_we = {
    'he': 'he',
    'she': 'she',
    'it': 'it',
    'they': 'they',
    'name': '', # suffix
    }
pronoun_map_We = { key:val.capitalize() for (key, val) in pronoun_map_we.items() }
pronoun_map_us = {
    'he': 'him',
    'she': 'her',
    'it': 'it',
    'they': 'them',
    'name': '', # suffix
    }
pronoun_map_Us = { key:val.capitalize() for (key, val) in pronoun_map_us.items() }
pronoun_map_our = {
    'he': 'his',
    'she': 'her',
    'it': 'its',
    'they': 'their',
    'name': "'s", # suffix
    }
pronoun_map_Our = { key:val.capitalize() for (key, val) in pronoun_map_our.items() }
pronoun_map_ours = {
    'he': 'his',
    'she': 'hers',
    'it': 'its',
    'they': 'theirs',
    'name': "'s", # suffix
    }
pronoun_map_Ours = { key:val.capitalize() for (key, val) in pronoun_map_ours.items() }
pronoun_map_ourself = {
    'he': 'himself',
    'she': 'herself',
    'it': 'itself',
    'they': 'themself',
    'name': '', # suffix
    }
pronoun_map_Ourself = { key:val.capitalize() for (key, val) in pronoun_map_ourself.items() }

pronoun_map_map = {
    'we': pronoun_map_we,
    'We': pronoun_map_We,
    'us': pronoun_map_us,
    'Us': pronoun_map_Us,
    'our': pronoun_map_our,
    'Our': pronoun_map_Our,
    'ours': pronoun_map_ours,
    'Ours': pronoun_map_Ours,
    'ourself': pronoun_map_ourself,
    'Ourself': pronoun_map_Ourself,
    }

def resolve_pronoun(player, mapkey):
    """
    Work out the pronoun string for a given player and a canonical pronoun.
    ('We', 'us', 'our', etc.)
    The player argument should be a players DB object -- or at least a
    dict containing 'name' and 'pronoun' entries. (None is also allowed.)
    """
    if not player:
        player = { 'name': 'nobody', 'pronoun': 'it' }
    map = pronoun_map_map[mapkey]
    if player['pronoun'] == 'name':
        # Add the suffix to the player's name
        return player['name'] + map['name']
    res = map.get(player['pronoun'], None)
    if not res:
        res = map.get('it')
    return res


import unittest

class TestGrammarModule(unittest.TestCase):
    
    def test_pronoun(self):
        player = {'name':'Fred', 'pronoun':'he'}
        self.assertEqual('he', resolve_pronoun(player, 'we'))
        self.assertEqual('him', resolve_pronoun(player, 'us'))
        self.assertEqual('his', resolve_pronoun(player, 'our'))
        self.assertEqual('His', resolve_pronoun(player, 'Our'))
        self.assertEqual('His', resolve_pronoun(player, 'Ours'))
        self.assertEqual('Himself', resolve_pronoun(player, 'Ourself'))

        player = {'name':'Fred', 'pronoun':'she'}
        self.assertEqual('She', resolve_pronoun(player, 'We'))
        self.assertEqual('Her', resolve_pronoun(player, 'Us'))
        self.assertEqual('Her', resolve_pronoun(player, 'Our'))
        self.assertEqual('her', resolve_pronoun(player, 'our'))
        self.assertEqual('hers', resolve_pronoun(player, 'ours'))
        self.assertEqual('herself', resolve_pronoun(player, 'ourself'))

        player = {'name':'Fred', 'pronoun':'name'}
        self.assertEqual('Fred', resolve_pronoun(player, 'we'))
        self.assertEqual('Fred', resolve_pronoun(player, 'us'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'our'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'Our'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'Ours'))
        self.assertEqual('Fred', resolve_pronoun(player, 'Ourself'))

        player = {'name':'Fred', 'pronoun':'they'}
        self.assertEqual('They', resolve_pronoun(player, 'We'))
        self.assertEqual('Them', resolve_pronoun(player, 'Us'))
        self.assertEqual('Their', resolve_pronoun(player, 'Our'))
        self.assertEqual('their', resolve_pronoun(player, 'our'))
        self.assertEqual('theirs', resolve_pronoun(player, 'ours'))
        self.assertEqual('themself', resolve_pronoun(player, 'ourself'))


if __name__ == '__main__':
    unittest.main()
