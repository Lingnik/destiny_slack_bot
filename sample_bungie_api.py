from bungie_api import BungieApi


c = BungieApi()

# inventoryItem = c.get_gjallarhorn()
# print(inventoryItem['data']['inventoryItem']['itemName'])

# print('search_users()')
# deracinist = c.search_users('Deracinist')
# print(deracinist)

print('search_destiny2_player()')
deracinist_d2 = c.search_d2_player('Deracinist')
print(deracinist_d2)

# print('get_user_membership()')
# deracinist_membership = c.get_user_membership(deracinist_d2[0]['membershipId'], 2)
# print(deracinist_membership)

membership_id = deracinist_d2[0]['membershipId']
print(membership_id)
membership_type = 2

print('get_d2_profile()')
deracinist_profile = c.get_d2_profile(membership_id, membership_type, ['Profiles', 'ProfileInventories'])
print(deracinist_profile)

character1 = deracinist_profile['profile']['data']['characterIds'][0]
character2 = deracinist_profile['profile']['data']['characterIds'][0]
character3 = deracinist_profile['profile']['data']['characterIds'][0]
print(character1)

print('get_d2_character()')
deracinist_char1 = c.get_d2_character(membership_id, membership_type, character1, ['200'])
print(deracinist_char1)

# print(c.get_d2_manifest())
