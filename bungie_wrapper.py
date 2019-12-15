"""A Bungie.net API wrapper.

This wrapper seeks to surface common Bungie.net API calls as methods, as well as more complex and innovative constructs
not provided by a single API call. While not every API endpoint is represented here, the pattern employed below should
be consistent and straightforward to copy for any GET request.

Example usage:
    # Create an app at https://www.bungie.net/en/Application and set your secret environment variables accordingly:
    # export BUNGIE_OAUTH_CLIENT_ID=1234567890
    # export BUNGIE_API_TOKEN=0123456789abcdef
    # export BUNGIE_OAUTH_USER_AGENT=destiny-rolls-checklist.herokuapp.com

    def cli_auth(api_token):
        msg = "https://www.bungie.net/en/OAuth/Authorize?response_type=code&state=1234&redirect=/&client_id={oauth_client_id}"
        msg = msg.format(oauth_client_id=os.environ.get('BUNGIE_OAUTH_CLIENT_ID', None))
        print("Visit: {}".format(msg))
        auth_code = input("Enter the value of the 'code' url parameter you are redirected to: ")
        d2 = BungieApi(api_token)
        oauth_token = d2.get_oauth_token(auth_code, True)
        serialized_token = json.dumps(oauth_token)
        print('')
        print('To skip this step next time, run these commands first:')
        print('export BUNGIE_OAUTH_TOKEN={}'.format(shlex.quote(serialized_token)))
        print('')
        input('Press enter to continue.')
        return oauth_token

    api_token = os.environ.get('BUNGIE_API_TOKEN', None)
    oauth_token = os.environ.get('BUNGIE_OAUTH_TOKEN', None)
    if oauth_token:
        oauth_token = json.loads(oauth_token)
        print('Using oauth token stored in BUNGIE_OAUTH_TOKEN environment variable.')
    else:
        oauth_token = cli_auth(api_token)

    d2 = BungieApi(api_token, oauth_token)
    player = d2.get_user_currentuser_membership()
    player_name = player['destinyMemberships'][0]['displayName']
    membership_type = player['destinyMemberships'][0]['membershipType']
    membership_id = player['destinyMemberships'][0]['membershipId']
"""
# Inspired by https://gist.github.com/cortical-iv/a22ef122e771b994454e02b6b4e481c3

import requests
import os
import datetime

from utilities import logger


class AuthenticationExpiredException(Exception):
    """The authentication token from Bungie has expired and a new one must be obtained with get_oauth_token()."""
    pass

class BungieApi:
    """A lean method-per-API-endpoint-based interface around the Bungie API."""
    BASE_URL = 'https://www.bungie.net/Platform'
    MEMBERSHIP_TYPES = {'xbox': '1', 'xbone': '1', 'psn': '2', 'pc': '4', 'ps4': '2'}
    COMPONENTS_ALL = [
        'Profiles', 'VendorReceipts', 'ProfileInventories', 'ProfileCurrencies', 'ProfileProgression', 'Characters',
        'CharacterInventories', 'CharacterProgressions', 'CharacterActivities', 'CharacterEquipment', 'ItemInstances',
        'ItemObjectives', 'ItemPerks', 'ItemStats', 'ItemSockets', 'ItemTalentGrids', 'ItemCommonData',
        'ItemPlugStates', 'Vendors', 'VendorCategories', 'VendorSales', 'Kiosks', 'CurrentLookups', 'PresentationNodes',
        'Collectibles', 'Records'
    ]

    def __init__(self, api_token=None, oauth_token=None):
        if api_token:
            self.api_token = api_token
        else:
            api_token = os.environ.get('BUNGIE_API_TOKEN', None)
            if not api_token:
                raise Exception("No API token was provided to BungieApi(api_token) or via the environment variable BUNGIE_API_TOKEN")
            self.api_token = api_token

        self._oauth_token = oauth_token

        self.headers = dict()
        self.headers["X-API-Key"] = self.api_token
        self.headers["User-Agent"] = os.environ.get('BUNGIE_OAUTH_USER_AGENT', '')

    def _get(self, url, extra_headers=None, params=None, as_user=False):
        bearer_header = {}
        if as_user and self._oauth_token and 'access_token' in self._oauth_token:
            bearer_header['Authorization'] = 'Bearer {}'.format(self._oauth_token.get('access_token'))
        extra_headers = extra_headers or {}
        request_headers = {**self.headers, **extra_headers, **bearer_header}

        if self._oauth_token and 'expires_at' in self._oauth_token and self.is_token_expired():
            if self.is_token_refresh_expired():
                raise AuthenticationExpiredException(
                    'Token has expired, and the window to refresh it has expired as well.'
                    'Fetch a new one with get_oauth_token().'
                )
            print('Token has expired, but we can try to refresh it.')
            #self.get_oauth_token(self.api_token, True)
            self.refresh_oauth_token(persist=True)

        response = requests.get(url, headers=request_headers, params=params)
        if response.status_code != 200:
            raise Exception("API returned non-200 status code: {} - {} - {}".format(response.status_code,
                                                                                    response.reason,
                                                                                    response.text))
        response = response.json()
        if response['ErrorStatus'] != 'Success':
            raise Exception("API returned error: {}".format(response))
        return response['Response']

    def is_token_expired(self):
        """Validate whether the persisted OAuth token is expired or not.
        
        :return: True if expired, False if not.
        """
        if not self._oauth_token:
            raise Exception("OAuth token has not been fetched.")
        now = datetime.datetime.now().timestamp()
        if now > self._oauth_token['expires_at']:
            print('token is expired')
            return True
        else:
            return False

    def is_token_refresh_expired(self):
        """Validate whether the persisted OAuth refresh token is expired or not.

        :return: True if expired, False if not.
        """
        if not self._oauth_token:
            raise Exception("OAuth token has not been fetched.")
        now = datetime.datetime.now().timestamp()
        if now > self._oauth_token['refresh_expires_at']:
            print('token is expired')
            return True
        else:
            return False

    def refresh_oauth_token(self, persist=False):
        """Refresh an existing OAuth token.

        :param persist: 
        :return: 
        """
        return self.get_oauth_token(self.api_token, persist=persist, use_refresh_token=True)

    def get_oauth_token(self, code, persist=False, use_refresh_token=False):
        """Fetch an OAuth token for the user's authentication code.
        
        Auth flow:
        1. From a login page, prompt the user to click a link to take them to https://www.bungie.net/en/OAuth/Authorize,
           passing in the querystring:
             ?response_type=code             # always code
             &client_id={oauth_client_id}    # oauth_client_id is set up on the Bungie app registration page
             &state=12345                    # uh, this should be random... and persisted in the session
             &redirect=/homepage             # the page on YOUR site to redirect to after a successful login
        2. Upon a successful Bungie login, they'll redirect you back to /auth and include a querystring:
             ?code=49d91358eff74672de1deb2a4b382b5b&state=12345
        3. Using that code (which proves the user's identity to Bungie's API), we call get_oauth_token(), which
           grabs an epehemeral oauth token from Bungie's API.
        4. Using that oauth token, we can now do privileged things against the Bungie API as that user!
        
        When refreshing tokens, the following rules apply:
        * Make a refresh request to the token endpoint using the following parameters in the body of the POST:
            grant_type: Value must be set to “refresh_token”
            refresh_token: Previously issued refresh token
        * The client must not include the scope parameter. The new access token will have the same scope as the one being refreshed.
        
        :param code: the OAuth code (a querystring provided by Bungie in their auth redirect) identifying the user
        :param persist: persist the resulting OAuth token in the API client instance for subsequent .get()s
        :param use_refresh_token: use the refresh token (instead of the auth token) to refresh an existing auth
        :return: 
        """
        url = self.BASE_URL + '/app/oauth/token/'
        client_id = os.environ.get('BUNGIE_OAUTH_CLIENT_ID')
        username = os.environ.get('BUNGIE_OAUTH_CLIENT_ID')
        password = os.environ.get('BUNGIE_OAUTH_CLIENT_SECRET')
        data = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'code': code,
        }
        if use_refresh_token:
            data['grant_type'] = 'refresh_token'
            data['refresh_token'] = self._oauth_token['refresh_token']
        with requests.Session() as s:
            s.headers = self.headers
            r = s.post(url, data=data, auth=requests.auth.HTTPBasicAuth(username, password))
            post_succeeded_at = datetime.datetime.now().timestamp()
        token = r.json()
        if persist:
            token['cached'] = True
            token['expires_at'] = post_succeeded_at + token['expires_in']
            token['refresh_expires_at'] = post_succeeded_at + token['refresh_expires_in']
            self._oauth_token = token
        return token

    def is_authenticated(self, validate=False):
        """Returns True if the user has credentials cached; if validate==True, then also verify that with the API.
        
        :param validate: Perform a GET against the Bungie API that will determine whether the user is actually logged in.
        :return: 
        """
        if not self._oauth_token:
            print('no persisted oauth token')
            return False
        if not 'access_token' in self._oauth_token:
            print('no access_token in persisted oauth token')
            return False
        if not 'expires_at' in self._oauth_token:
            print('missing token expiration date in persisted oauth token')
            return False

        # The token is expired and non-refreshable.
        if self.is_token_expired():
            if self.is_token_refresh_expired():
                print('token is expired and cannot be refreshed')
                return False
            self.refresh_oauth_token(persist=True)

        if validate:
            current_user = self.get_user_currentuser_membership()
            logger.debug(current_user)
        return True

    """
    Methods that call the API once:
    """

    def get_user_currentuser_membership(self):
        """Get the currently-authenticated user's Memberships."""
        r = self._get(self.BASE_URL + '/User/GetMembershipsForCurrentUser/', as_user=True)
        return r

    def get_gjallarhorn(self):
        """Fetch the Destiny Gjallarhorn item."""
        r = self._get(self.BASE_URL + "/Destiny/Manifest/InventoryItem/1274330687/")
        return r

    def search_users(self, search_string=''):
        # https://bungie-net.github.io/#User.SearchUsers
        """
        
        :param search_string: 
        :return: 
        """
        r = self._get(self.BASE_URL + '/User/SearchUsers/', params={'q': search_string})
        return r

    def search_d2_player(self, membership_type='2', display_name=''):
        # https://bungie-net.github.io/#Destiny2.SearchDestinyPlayer
        """
        
        :param membership_type: 
        :param display_name: 
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/Destiny2/SearchDestinyPlayer/{membershipType}/{displayName}/'.format(
                membershipType=membership_type,
                displayName=display_name
            )
        )
        return r

    def get_user_membership(self, membership_id, membership_type):
        # https://bungie-net.github.io/#User.GetMembershipDataById
        """
        
        :param membership_id: 
        :param membership_type: 
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/User/GetMembershipsById/{membershipId}/{membershipType}/'.format(
                membershipId=membership_id,
                membershipType=membership_type
            )
        )
        return r

    def get_d2_profile(self, membership_id, membership_type, components):
        # https://bungie-net.github.io/#Destiny2.GetProfile
        """
        
        :param membership_id: 
        :param membership_type: 
        :param components: Destiny.DestinyComponentType https://bungie-net.github.io/#/components/schemas/Destiny.DestinyComponentType
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/Destiny2/{membershipType}/Profile/{destinyMembershipId}/'.format(
                membershipType=membership_type,
                destinyMembershipId=membership_id
            ),
            params={'components': ','.join(components)}
        )
        return r

    def get_d2_linked_profiles(self, membership_id, membership_type):
        # https://bungie-net.github.io/#Destiny2.GetLinkedProfiles
        """
        
        :param membership_id: 
        :param membership_type: 
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/Destiny2/{membershipType}/Profile/{membershipId}/LinkedProfiles/'.format(
                membershipType=membership_type,
                membershipId=membership_id
            )
        )
        return r

    def get_d2_character(self, membership_type, membership_id, character_id, components):
        # https://bungie-net.github.io/#Destiny2.GetCharacter
        """
        
        :param membership_type: 
        :param membership_id: 
        :param character_id: 
        :param components: Destiny.DestinyComponentType https://bungie-net.github.io/#/components/schemas/Destiny.DestinyComponentType
        :return: 
        """
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
        # https://bungie-net.github.io/#Destiny2.GetDestinyManifest
        """
        
        :return: 
        """
        return self._get(self.BASE_URL + '/Destiny2/Manifest/')

    def get_d2_character_activities(self, membership_type, membership_id, character_id, count=None, mode=None, page=None):
        # https://bungie-net.github.io/#Destiny2.GetActivityHistory
        """
        
        :param membership_type: 
        :param membership_id: 
        :param character_id: 
        :param count: 
        :param mode: 
        :param page: 
        :return: 
        """
        request_params = {}
        if count:
            request_params['count'] = count
        if mode:
            request_params['mode'] = mode
        if page:
            request_params['page'] = page
        r = self._get(
            self.BASE_URL + '/Destiny2/{membershipType}/Account/{destinyMembershipId}/Character/{characterId}/Stats/Activities/'.format(
                membershipType=membership_type,
                destinyMembershipId=membership_id,
                characterId=character_id
            ),
            params=request_params
        )
        return r

    def get_post_game_carnage_report(self, activity_id):
        # https://bungie-net.github.io/#Destiny2.GetPostGameCarnageReport
        """Obtain the PGCR (Post Game Carnage Report) for a specified activity.
        
        :param activity_id: 
        :return: a post game carnage report object (dict)
        """
        r = self._get(
            self.BASE_URL + '/Destiny2/Stats/PostGameCarnageReport/{activityId}/'.format(
                activityId=activity_id
            )
        )
        return r

    def get_clan_for_player(self, membership_type, membership_id):
        # /GroupV2/User/{membershipType}/{membershipId}/0/1/
        """Get the user's clan.
        
        :param membership_type: 
        :param membership_id: 
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/GroupV2/User/{membershipType}/{membershipId}/0/1/'.format(
                membershipType=membership_type,
                membershipId=membership_id
            )
        )
        return r

    def get_clan_members(self, clan_id):
        # https://bungie-net.github.io/#GroupV2.GetMembersOfGroup
        # /GroupV2/{groupId}/Members/
        """Get the members of a group (clan).
        
        :param clan_id: 
        :return: 
        """
        r = self._get(
            self.BASE_URL + '/GroupV2/{groupId}/Members/'.format(
                groupId=clan_id
            )
        )
        return r


    """
    More-complex API operations below here, things that require >1 API call.
    """

    def get_primary_membership(self, membership_type, membership_id):
        """For a given player "membership", fetch the canonical membership associated with their cross-save config.
        
        :param membership_type: 
        :param membership_id: 
        :return: a two-tuple of membership type (int) and membership id (int)
        """
        memberships = self.get_user_membership(membership_id, membership_type)
        memberships = memberships['destinyMemberships']
        primary_membership_type = None
        primary_membership_id = None
        for membership in memberships:
            if primary_membership_id:
                break
            membership_id = membership['membershipId']
            membership_type = membership['membershipType']
            linked_profiles = self.get_d2_linked_profiles(membership_id, membership_type)
            for profile in linked_profiles['profiles']:
                if profile['isOverridden'] is False:
                    primary_membership_id = profile['membershipId']
                    primary_membership_type = profile['membershipType']
        return primary_membership_type, primary_membership_id

    def get_latest_activity(self, membership_type, membership_id):
        """Fetch the single most recent activity record of a player's N characters.
        
        :param membership_type: 
        :param membership_id: 
        :return: an activity object (dict)
        """
        profile = self.get_d2_profile(membership_id, membership_type, ['100'])
        latest_activity = None
        latest_activity_dt = None
        for character in profile['profile']['data']['characterIds']:
            activities = self.get_d2_character_activities(membership_type, membership_id, character, count=1, page=0)
            activity = activities['activities'][0]
            dt = datetime.datetime.strptime(activity['period'], '%Y-%m-%dT%H:%M:%S%z')
            if not latest_activity:
                latest_activity = activity
                latest_activity_dt = dt
            else:
                if dt > latest_activity_dt:
                    latest_activity = activity
                    latest_activity_dt = dt
        return latest_activity

    def get_current_activity(self, membership_type, membership_id):
        """
        
        :param membership_type: 
        :param membership_id: 
        :return: three-tuple of activity_hash, activity_mode_hash, active_character or None,None,None if no activity
        """
        activities = self.get_d2_profile(membership_id, membership_type, ['204'])
        characters = activities['characterActivities']['data']
        activity_hash = None
        activity_mode_hash = None
        active_character = None
        for key in characters:
            tmp_activity_hash = characters[key]['currentActivityHash']
            tmp_activity_mode_hash = characters[key]['currentActivityModeHash']
            if tmp_activity_hash in (0, 82913930) and tmp_activity_mode_hash in (0, 2166136261):
                continue
            else:
                activity_hash = tmp_activity_hash
                activity_mode_hash = tmp_activity_mode_hash
                active_character = key
                break

        return activity_hash, activity_mode_hash, active_character


    def get_clan_last_on(self, clan_id):
        """Return a clan's roster including the last time each member played and when they joined.
    
        :param clan_id: 
        :return: List of dicts, each member of the clan roster
        """
        clan_members = self.get_clan_members(clan_id)
        clan_members_clean = []
        for member in clan_members['results']:
            profile = self.get_d2_profile(
                member['destinyUserInfo']['membershipId'],
                member['destinyUserInfo']['membershipType'],
                components=['100'])
            last_played = profile['profile']['data']['dateLastPlayed']
            last_played = datetime.datetime.strptime(last_played, '%Y-%m-%dT%H:%M:%S%z')
            now = datetime.datetime.now(datetime.timezone.utc)
            time_since_last_played = now - last_played
            clan_members_clean.append(
                {
                    'name': member['destinyUserInfo']['displayName'],
                    'joinDate': member['joinDate'],
                    'lastPlayed': last_played,
                    'timeSinceLastPlayed': str(time_since_last_played),
                    'isOnline': member['isOnline']
                })
        return sorted(clan_members_clean, key=lambda i: i['lastPlayed'])
