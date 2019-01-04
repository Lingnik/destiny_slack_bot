# Inspired by https://gist.github.com/cortical-iv/a22ef122e771b994454e02b6b4e481c3

import requests
import os


class BungieApi:
    BASE_URL = 'https://bungie.net/Platform'
    MEMBERSHIP_TYPES = {'xbox': '1', 'xbone': '1', 'psn': '2', 'pc': '4', 'ps4': '2'}

    def __init__(self, api_token=None):
        if api_token:
            self.api_token = api_token
        else:
            self.api_token = os.environ.get('BUNGIE_API_TOKEN', None)

        self.headers = {"X-API-Key": self.api_token}

    def _get(self, url, extra_headers=None, params=None):
        extra_headers = extra_headers or {}
        request_headers = {**self.headers, **extra_headers}

        r = requests.get(url, headers=request_headers, params=params)
        r = r.json()
        if r['ErrorStatus'] != 'Success':
            raise Exception("API returned error: {}".format(r))
        return r['Response']

    def get_gjallarhorn(self):
        r = self._get(self.BASE_URL + "/Destiny/Manifest/InventoryItem/1274330687/")
        return r

    def search_users(self, search_string=''):
        r = self._get(self.BASE_URL + '/User/SearchUsers/', params={'q': search_string})
        return r

    def search_d2_player(self, display_name=''):
        r = self._get(
            self.BASE_URL + '/Destiny2/SearchDestinyPlayer/{membershipType}/{displayName}/'.format(
                membershipType='2',
                displayName=display_name
            )
        )
        return r

    def get_user_membership(self, membership_id, membership_type):
        r = self._get(
            self.BASE_URL + '/User/GetMembershipsById/{membershipId}/{membershipType}/'.format(
                membershipId=membership_id,
                membershipType=membership_type
            )
        )
        return r

    def get_d2_profile(self, membership_id, membership_type, components):
        r = self._get(
            self.BASE_URL + '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/'.format(
                membershipType=membership_type,
                destinyMembershipId=membership_id
            ),
            params={'components': ','.join(components)}
        )
        return r

    def get_d2_character(self, membership_type, membership_id, character_id, components):
        r = self._get(
            self.BASE_URL + '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/Character/{characterId}/'.format(
                membershipType=membership_type,
                destinyMembershipId=membership_id,
                characterId=character_id
            ),
            params={'components': ','.join(components)}
        )
        return r

    def get_d2_manifest(self):
        return self._get(self.BASE_URL + '/Destiny2/Manifest/')
