# Inspired by https://gist.github.com/cortical-iv/a22ef122e771b994454e02b6b4e481c3

import requests
import logging
import os

try:
    from django.conf import settings
    if settings.DEBUG:
        try:
            import http.client as http_client
        except ImportError:
            # Python 2
            import httplib as http_client
        http_client.HTTPConnection.debuglevel = 1
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
except:
    pass


class BungieApi:
    BASE_URL = 'https://www.bungie.net/Platform'
    MEMBERSHIP_TYPES = {'xbox': '1', 'xbone': '1', 'psn': '2', 'pc': '4', 'ps4': '2'}

    def __init__(self, api_token=None, api_bearer_token=None):
        if api_token:
            self.api_token = api_token
        else:
            self.api_token = os.environ.get('BUNGIE_API_TOKEN', None)

        self.headers = dict()
        self.headers["X-API-Key"] = self.api_token
        self.headers["User-Agent"] = 'destiny-rolls-checklist.herokuapp.com'
        if api_bearer_token:
            self.headers['Authorization'] = api_bearer_token

    def _get(self, url, extra_headers=None, params=None):
        extra_headers = extra_headers or {}
        request_headers = {**self.headers, **extra_headers}

        r = requests.get(url, headers=request_headers, params=params)
        r = r.json()
        if r['ErrorStatus'] != 'Success':
            raise Exception("API returned error: {}".format(r))
        return r['Response']

    # Auth flow:
    # 1. From a login page, prompt the user to click a link to take them to https://www.bungie.net/en/OAuth/Authorize,
    #    passing in the querystring:
    #      ?response_type=code             # always code
    #      &client_id={oauth_client_id}    # oauth_client_id is set up on the Bungie app registration page
    #      &state=12345                    # uh, this should be random... and persisted in the session
    #      &redirect=/homepage             # the page on YOUR site to redirect to after a successful login
    # 2. Upon a successful Bungie login, they'll redirect you back to /auth and include a querystring:
    #      ?code=49d91358eff74672de1deb2a4b382b5b&state=12345
    # 3. Using that code (which proves the user's identity to Bungie's API), we call get_oauth_token(), which
    #    grabs an epehemeral oauth token from Bungie's API.
    # 4. Using that oauth token, we can now do privileged things against the Bungie API as that user!
    def get_oauth_token(self, code):
        url = self.BASE_URL + '/app/oauth/token/'
        data = {
            'grant_type': 'authorization_code',
            'client_id': os.environ.get('BUNGIE_OAUTH_CLIENT_ID'),
            'code': code
        }
        username = os.environ.get('BUNGIE_OAUTH_CLIENT_ID')
        password = os.environ.get('BUNGIE_OAUTH_CLIENT_SECRET')
        with requests.Session() as s:
            s.headers = self.headers
            r = s.post(url, data=data, auth=requests.auth.HTTPBasicAuth(username, password))
        return r.json()

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
