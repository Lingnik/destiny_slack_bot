"""Destiny 2 CLI.

"""
import os
import json
import pprint
import shlex
import datetime

import requests

from bungie_api import BungieApi, AuthenticationExpiredException


pp = pprint.PrettyPrinter(indent=4)


def cli_auth(api_token):
    """Mimic an oauth flow to get the user an API token."""
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

def handle_cli():
    """CLI entrypoint for __main__"""
    api_token = os.environ.get('BUNGIE_API_TOKEN', None)
    if not api_token:
        raise Exception('Missing environment variable BUNGIE_API_TOKEN.')

    oauth_token = os.environ.get('BUNGIE_OAUTH_TOKEN', None)
    if oauth_token:
        oauth_token = json.loads(oauth_token)
        print('Using oauth token stored in BUNGIE_OAUTH_TOKEN environment variable.')
    else:
        oauth_token = cli_auth(api_token)

    print("Authenticating...")
    d2 = BungieApi(api_token, oauth_token)

    try:
        if not d2.is_authenticated(validate=True):
            print("Unable to proceed, not authenticated with valid credentials.")
            return
    except AuthenticationExpiredException:
        oauth_token = cli_auth(api_token)
        d2 = BungieApi(api_token, oauth_token)
        d2.is_authenticated(validate=True)


    print("Getting manifest...")
    manifest = d2.get_d2_manifest()
    activity_types = requests.get('https://www.bungie.net/{}'.format(
        manifest['jsonWorldComponentContentPaths']['en']['DestinyActivityDefinition'])
    ).json()
    pp.pprint(activity_types)

    print("Getting current user...")
    player = d2.get_user_currentuser_membership()
    player_name = player['destinyMemberships'][0]['displayName']
    membership_type = player['destinyMemberships'][0]['membershipType']
    membership_id = player['destinyMemberships'][0]['membershipId']

    # print("Getting Rip...")
    # player = d2.search_d2_player(membership_type='2', display_name='RipRippington')
    # player_name = player[0]['displayName']
    # membership_type = player[0]['membershipType']
    # membership_id = player[0]['membershipId']

    # Getting details about previously looked-up player
    membership_type, membership_id = d2.get_primary_membership(membership_type, membership_id)
    #pp.pprint(player)
    print(f'User is {player_name=} {membership_type=} {membership_id=}')

    def get_activity_details(activity_obj):
        activity_timestamp = latest_activity['period']
        activity_duration = latest_activity['values']['activityDurationSeconds']['basic']['displayValue']
        activity_type = \
        activity_types[str(latest_activity['activityDetails']['directorActivityHash'])]['displayProperties']['name']
        latest_pgcr = d2.get_post_game_carnage_report(latest_activity['activityDetails']['instanceId'])
        # player_count = len(latest_pgcr['entries'])
        other_players = [player['player']['destinyUserInfo']['displayName'] for player in latest_pgcr['entries']]
        return f"Latest activity: {activity_type=} {activity_timestamp=} {activity_duration=} {other_players=}"
        # pp.pprint(latest_activity)
        # pp.pprint(latest_pgcr)
        # for player in latest_pgcr['entries']:
        #     player_name = player['player']['destinyUserInfo']['displayName']
        #     membership_type = player['player']['destinyUserInfo']['membershipType']
        #     membership_id = player['player']['destinyUserInfo']['membershipId']
        #     # print(f"    Player: {player_name=} {membership_type=} {membership_id=}")

    print("Getting latest activity...")
    latest_activity = d2.get_latest_activity(membership_type, membership_id)
    pp.pprint(latest_activity)
    # pp.pprint(activity_types[str(latest_activity['activityDetails']['directorActivityHash'])])
    # pp.pprint(activity_types[str(latest_activity['activityDetails']['referenceId'])])
    return

    print("Getting details about latest activity...")
    print(get_activity_details(latest_activity))

    print("Getting most recent 1,000 activities...")
    activities = []
    profile = d2.get_d2_profile(membership_id, membership_type, ['100'])  # , ['100', '200', '204', '900', '1000'])
    for character in profile['profile']['data']['characterIds']:
        c_c = 0
        for page in range(10000):
            these_activities = d2.get_d2_character_activities(
                membership_type, membership_id, character, count=250, page=page)
            if 'activities' in these_activities:
                these_activities = these_activities['activities']
                print(len(these_activities))
                c_c += len(these_activities)
                activities += these_activities
            else:
                break
        print(c_c)
    print(len(activities))

if __name__ == "__main__":
    handle_cli()
