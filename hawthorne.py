"""@Hawthorne bot for Destiny 2.

"""
import os
import json
import pprint
import shlex
import datetime
import time
import signal

import requests

from slack_wrapper import SlackApi
from bungie_wrapper import BungieApi

MEMBERSHIP_TYPE_XBOX = 1
MEMBERSHIP_TYPE_PSN = 2
MEMBERSHIP_TYPE_STEAM = 3
MEMBERSHIP_TYPE_STADIA = 5

# #hawthorne = CR0NPJWBT
# #hawthorne-log = CRDP36TMX
# #hawthorne-playground = CRJERJ0S3
# #destiny-export = CQDKVNF3R
SLACK_FIELD_PSN = 'Xf0DB6LM46'
SLACK_FIELD_XBL = 'XfMDV8FH3K'
SLACK_FIELD_STM = 'XfMKSQK1S8'


SIGTERM_RECEIVED = False
DEBUG = bool(os.environ.get('HAWTHORNE_DEBUG', False))
pp = pprint.PrettyPrinter(indent=4)


class Hawthorne:
    """@Hawthorne, the Destiny 2 Slack bot."""

    def __init__(
            self,
            slack_api_token,
            slack_incoming_webhook_url,
            slack_oauth_client_id,
            slack_oauth_client_secret,
            slack_oauth_token,
            bungie_api_token,
            bungie_oauth_token,
            slack_channel_hawthorne,
            slack_channel_log,
            slack_bot_user_id,
            slack,
            bungie
    ):
        self.slack_api_token = slack_api_token
        self.slack_incoming_webhook_url = slack_incoming_webhook_url
        self.slack_oauth_client_id = slack_oauth_client_id
        self.slack_oauth_client_secret = slack_oauth_client_secret
        self.slack_oauth_token = slack_oauth_token
        self.bungie_api_token = bungie_api_token
        self.bungie_oauth_token = bungie_oauth_token
        self.slack_channel_hawthorne = slack_channel_hawthorne
        self.slack_channel_log = slack_channel_log
        self.slack_bot_user_id = slack_bot_user_id
        self.slack = slack
        self.bungie = bungie

        self.bungie_manifest = None
        self.bungie_manifest_activity_definitions = None
        self.bungie_manifest_activity_mode_definitions = None
        self.player_activity_cache = None  # type: dict
        self.keep_running = False

    """
    LOGGERS
    """

    def announce(self, message):
        """Announce a message to the default Slack channel as the bot user.
        
        :param message: 
        :return: 
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        print(f"{now} SLACK: {message}")#
        return self.slack.slack_as_bot.chat_postMessage(channel=self.slack_channel_hawthorne, text=message).get('ts')

    def log(self, message):
        """Log something pertinent to the Slack log channel (and the console).
        
        :param message: 
        :return: 
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        msg = f"{now} LOG: {message}"
        print(msg)
        return self.slack.slack_as_bot.chat_postMessage(channel=self.slack_channel_log, text=msg).get('ts')

    def log_thread(self, thread_ts, message):
        """Log a followup to a thread.
        
        :param thread_ts: 
        :param message: 
        :return: 
        """
        return self.slack.slack_as_bot.chat_postMessage(channel=self.slack_channel_log, thread_ts=thread_ts, text=message)

    @staticmethod
    def log_local(message):
        """Log something pertinent to the console (only).

        :param message: 
        :return: 
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        msg = f"{now} LOG_LOCAL: {message}"
        print(msg)

    @staticmethod
    def debug(message):
        """Emit debugging information, when wanted, to the console.
        
        :param message: 
        :return: 
        """
        if DEBUG:
            now = datetime.datetime.now(datetime.timezone.utc)
            print(f"{now} DEBUG: {message}")

    """
    TICKER LOOP
    """

    def stop(self):
        """Send the instruction to stop the bot after the current tick completes.

        :return: 
        """
        self.keep_running = False

    def start(self):
        """Start the bot running.
        
        :return: 
        """
        if self.keep_running:
            raise Exception("Bot instance is already running.")

        # This is a simple loop-based ticker. Every tick of the loop, we execute zero or one actions from the registry.
        # It is not guaranteed to call from the registry at the exactly-correct time: time will drift if call runtime
        # exceeds the frequency or if another method call results in an execution time being missed, but it will attempt
        # to execute things as soon as possible after they are scheduled to be run.

        self.announce("I'm back! [Bot started.]")

        # Register actions that the loop will tick against.
        action_registry = [
            {'method': self.heartbeat, 'frequency': 300, 'last': 0, 'wait': 0},
            {'method': self.cache_bungie_manifests, 'frequency': 86400, 'last': 0, 'wait': 0},
            {'method': self.cache_player_activities, 'frequency': None, 'last': 0, 'wait': 0},
            {'method': self.report_player_activity, 'frequency': 30, 'last': 0, 'wait': 0},
            {'method': self.dump_slack_history, 'frequency': 86400, 'last': 0, 'wait': 86400},
        ]
        # Enqueue future things that we're waiting on by setting their 'last' to the future.
        for i, action in enumerate(action_registry):
            wait = action['wait']
            if wait > 0:
                now = datetime.datetime.now(datetime.timezone.utc).timestamp()
                action_registry[i]['last'] = now + wait

        # Start the loop.
        self.log("Starting action ticker.")
        self.keep_running = True
        while self.keep_running is True:
            if SIGTERM_RECEIVED:
                self.keep_running = False
                msg = "I need to feed Louis before he freaks out again, brb. [Heroku is probably restarting me.]"
                self.announce(msg)
            if self.keep_running is False:
                self.log('Hawthorne has been instructed to stop. Breaking out of tick loop.')
                break
            time.sleep(1)  # We sleep by one second to prevent bot spam.
            self.debug('TICK')

            # Try to find an action to call, call it, then break as soon as we call one action.
            for i, action in enumerate(action_registry):
                now = datetime.datetime.now(datetime.timezone.utc).timestamp()
                last = action['last']
                frequency = action['frequency']
                # Skip actions that don't repeat (their frequency is None) after they've run once:
                if frequency is None:
                    frequency = 0
                    if last > 0:
                        continue
                if last + frequency < now:
                    action_call = action['method']
                    if DEBUG:
                        action_call_name = action_call.__name__
                        self.debug(f"Ticking on {action_call_name}. [DEBUG]")
                        action_call()
                    else:
                        try:
                            action_call_name = action_call.__name__
                            self.debug(f"Ticking on {action_call_name}.")
                            action_call()
                        except Exception as e:
                            thread_ts = self.log(f"Exception occurred when ticking on {action_call_name}.")
                            self.log_thread(thread_ts, f"```\n{e}\n```")
                            break
                    action_registry[i]['last'] = now
                    break

            # END TICK
            self.debug('TOCK')

    """
    TICKER METHODS
    """

    def heartbeat(self):
        """Log something to the console every 5 minutes to keep the Heroku worker alive.
        
        :return: 
        """
        self.log_local('heartbeat')

    def dump_slack_history(self):
        # TODO: Port this over from the Slack activity exporter, and write a data persistence layer
        """
        
        :return: 
        """
        pass

    def cache_bungie_manifests(self):
        """Cache relevant Bungie manifests.

        :return: 
        """
        self.log("Caching Bungie.net manifests...")
        self.bungie_manifest = self.bungie.get_d2_manifest()
        self.bungie_manifest_activity_definitions = requests.get('https://www.bungie.net/{}'.format(
            self.bungie_manifest['jsonWorldComponentContentPaths']['en']['DestinyActivityDefinition'])
        ).json()
        self.bungie_manifest_activity_mode_definitions = requests.get('https://www.bungie.net/{}'.format(
            self.bungie_manifest['jsonWorldComponentContentPaths']['en']['DestinyActivityModeDefinition'])
        ).json()

    def cache_player_activities(self):
        """Cache the current activity for each player in the channel so we don't spam on startup or future ticks.

        :return: 
        """
        self.log("*Pre-caching player activities...*")
        self.player_activity_cache = {}
        players_activities = self.get_players_activities()
        for activity in players_activities:
            cache_key = f"{activity['destiny_membership_type']}-{activity['destiny_membership_id']}"
            if activity['active_character'] is None:
                self.log(f"_Cache:_ No activity for {cache_key}")
                # self.player_activity_cache[cache_key] = None
                continue

            msg = self.activity_message_for(activity)
            self.log(f"_Cache:_ Activity for {cache_key}: {activity['activity']['hash']} `{msg}`")
            cache_val = activity["activity"]["hash"]
            self.player_activity_cache[cache_key] = [cache_val]

    def report_player_activity(self):
        """Report on player activity.

        :return: 
        """
        players_activities = self.get_players_activities()
        for activity in players_activities:
            if activity['active_character'] is None:
                self.debug(f"{activity['slack_member']['slack_display_name']}: No activity.")
                continue

            cache_key = f"{activity['destiny_membership_type']}-{activity['destiny_membership_id']}"
            new_activity_hash = activity['activity']['hash']

            # Fetch and update the cache.
            seen_activities = self.player_activity_cache.get(cache_key)
            if seen_activities is not None and isinstance(seen_activities, list):
                seen_activities = seen_activities.copy()
                if len(seen_activities) > 10:  # Only cache up to 10 recent activity hashes.
                    del self.player_activity_cache[cache_key][0]
            else:
                self.player_activity_cache[cache_key] = []
            self.player_activity_cache[cache_key].append(new_activity_hash)  # Update the cache.

            # If the activity is in the cache, skip announcing.
            if isinstance(seen_activities, list) and new_activity_hash in seen_activities:
                self.debug(f"{activity['slack_member']['slack_display_name']}: Seen activity: {new_activity_hash}")
                continue

            # Announce the activity.
            msg = self.activity_message_for(activity)
            self.announce(msg)
            self.log(f"{cache_key}: {new_activity_hash}")

    """
    HELPER METHODS
    """

    def get_players_activities(self):
        """Get a list of players (dicts) of a channel and their most recent activity.
        
        :return: 
        """
        players_activities = []
        channel_members = self.fetch_slack_channel_members(self.slack_channel_hawthorne)
        for member in channel_members:
            # Ask for the user by gamertag and fetch their Bungie.net profile.
            if 'destiny_psn_id' in member and member['destiny_psn_id']:
                player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_PSN,
                                                      display_name=member['destiny_psn_id'])
            elif 'destiny_xbl_id' in member and member['destiny_xbl_id']:
                player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_XBOX,
                                                      display_name=member['destiny_xbl_id'])
            elif 'destiny_stm_id' in member and member['destiny_stm_id']:
                player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_STEAM,
                                                      display_name=member['destiny_stm_id'])
            else:
                self.log(f"Player is a member of channel, but has no gamer tags: {member['slack_display_name']}")
                continue
            if len(player) == 0:
                self.log(f"Unable to find characters for member: {member['slack_display_name']}")
                continue
            player_name = player[0]['displayName']
            membership_type = player[0]['membershipType']
            membership_id = player[0]['membershipId']

            # Get the "current" activity for the player and hydrate that with additional context.
            activity, activity_mode, active_character = self.bungie.get_current_activity(membership_type, membership_id)
            activity_name = None
            if active_character is not None:
                activity_name = ""
                activity = self.bungie_manifest_activity_definitions[str(activity)]
                activity_name += activity["displayProperties"]["name"]
                try:
                    activity_mode = self.bungie_manifest_activity_mode_definitions[str(activity_mode)]
                    activity_name = "{} - {}".format(activity_mode["displayProperties"]["name"], activity_name)
                except:
                    pass
                if activity["activityLightLevel"] > 0:
                    activity_name = "{} (PL{})".format(activity_name, activity["activityLightLevel"])

            players_activities.append({
                'slack_member': member,
                'destiny_player': player,
                'destiny_player_name': player_name,
                'destiny_membership_type': membership_type,
                'destiny_membership_id': membership_id,
                'activity': activity,
                'activity_mode': activity_mode,
                'active_character': active_character,
                'activity_name': activity_name
            })
        return players_activities

    @staticmethod
    def activity_message_for(activity):
        """Return a Slack-formatted message (raw, not blocks) representing the current activity.
        
        :param activity: 
        :return: 
        """
        slack_display_name = activity["slack_member"]["slack_display_name"]
        destiny_player_name = activity["destiny_player_name"]
        activity_name = activity["activity_name"]
        if not slack_display_name:
            display_name = f'*{destiny_player_name}*'
        else:
            display_name = f'*{destiny_player_name}* (@{slack_display_name})'
        return f':hawthorne: {display_name} is now playing *{activity_name}*'

    def fetch_slack_channel_members(self, slack_channel_id):
        """Fetch all the Slack members for a channel and their various Destiny usernames.
        
        :param slack_channel_id: 
        :return: 
        """
        channel_members = []
        raw_members = self.slack.slack_as_user.channels_info(channel=slack_channel_id).data['channel'].get(
            'members')
        for member_id in raw_members:
            member = self.slack.slack_as_user.users_profile_get(user=member_id)
            if 'bot_id' in member['profile']:
                continue
            if 'fields' in member.data['profile'] and isinstance(member.data['profile']['fields'], dict):
                record = {
                    'slack_id': member_id,
                    'slack_display_name': member.data['profile'].get('display_name', None),
                    'destiny_psn_id': member.data['profile'].get('fields', {}).get(SLACK_FIELD_PSN, {}).get('value', None),
                    'destiny_xbl_id': member.data['profile'].get('fields', {}).get(SLACK_FIELD_XBL, {}).get('value', None),
                    'destiny_stm_id': member.data['profile'].get('fields', {}).get(SLACK_FIELD_STM, {}).get('value', None)
                }
                channel_members.append(record)
            else:
                self.debug(f"{member.data['profile'].get('display_name', None)} does not have valid gamertag fields.")
        return channel_members


"""
COMMAND LINE HANDLER
"""

def cli_bungie_auth(api_token):
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

def required_environment_variable(varname):
    """Retrieve a required environment variable.
    
    :param varname: 
    :return: 
    """
    envvar_value = os.environ.get(varname, None)
    if not envvar_value:
        raise Exception(f"Missing environment variable {varname}")
    return envvar_value

def optional_environment_variable(varname, default=None):
    """Retrieve an optional environment variable.
    
    :param varname: 
    :param default: 
    :return: 
    """
    envvar_value = os.environ.get(varname, default)
    return envvar_value


def command_line_main():
    """CLI entrypoint. Instantiates the Hawthorne daemon."""

    # Fetch environment variables.
    slack_api_token = required_environment_variable('SLACK_API_TOKEN')
    slack_api_bot_token = required_environment_variable('SLACK_API_BOT_TOKEN')
    slack_incoming_webhook_url = required_environment_variable('SLACK_INCOMING_WEBHOOK_URL')
    slack_oauth_client_id = required_environment_variable('SLACK_OAUTH_CLIENT_ID')
    slack_oauth_client_secret = required_environment_variable('SLACK_OAUTH_CLIENT_SECRET')
    slack_oauth_token = optional_environment_variable('SLACK_OAUTH_TOKEN')
    slack_channel_hawthorne = required_environment_variable('SLACK_CHANNEL_HAWTHORNE')
    slack_channel_log = required_environment_variable('SLACK_CHANNEL_LOG')
    slack_bot_user_id = required_environment_variable('SLACK_BOT_USER_ID')
    bungie_api_token = required_environment_variable('BUNGIE_API_TOKEN')
    bungie_oauth_token = optional_environment_variable('BUNGIE_OAUTH_TOKEN')
    if bungie_oauth_token:
        bungie_oauth_token = json.loads(bungie_oauth_token)

    # Fetch command-line arguments.
    # ---

    # Authenticate with Slack
    oauth_scope = ['users.profile:read']
    if not slack_oauth_token:
        slack = SlackApi(oauth_client_id=slack_oauth_client_id,
                         oauth_client_secret=slack_oauth_client_secret,
                         oauth_scope=oauth_scope,
                         oauth_user_token=slack_api_token,
                         oauth_bot_token=slack_api_bot_token,
                         incoming_webhook_url=slack_incoming_webhook_url)
        print(slack.start_auth())
        code = input('Enter the code provided by Slack: ')
        slack.finish_auth(code)
    else:
        slack = SlackApi(oauth_user_token=slack_oauth_token, incoming_webhook_url=slack_incoming_webhook_url)
        slack.auth(slack_oauth_token, slack_api_bot_token)

    # Authenticate with Bungie
    if not bungie_oauth_token:
        print('No oauth token in BUNGIE_OAUTH_TOKEN, so fetching a new one.')
        bungie_oauth_token = cli_bungie_auth(bungie_api_token)
    bungie = BungieApi(bungie_api_token, bungie_oauth_token)
    print("Verifying Bungie API connection.")
    try:
        if not bungie.is_authenticated(validate=True):
            print("Unable to proceed, not authenticated with valid credentials.")
            return
    except Exception as e:
        print("Exception encountered when authenticating - fetching new credentials.")
        bungie_oauth_token = cli_bungie_auth(bungie_api_token)
        bungie = BungieApi(bungie_api_token, bungie_oauth_token)
        if not bungie.is_authenticated(validate=True):
            print("Unable to proceed, not authenticated with valid credentials.")
            return

    # Start the bot.
    bot = Hawthorne(
        slack_api_token,
        slack_incoming_webhook_url,
        slack_oauth_client_id,
        slack_oauth_client_secret,
        slack_oauth_token,
        bungie_api_token,
        bungie_oauth_token,
        slack_channel_hawthorne,
        slack_channel_log,
        slack_bot_user_id,
        slack,
        bungie
    )
    signal.signal(signal.SIGTERM, receive_signal)
    print("Starting Hawthorne.")
    bot.start()
    print("Hawthorne has stopped.")


def receive_signal(signal_number, frame):
    """Receive UNIX process signals so we can handle Heroku's SIGTERM and shut down gracefully.
    
    :param signal_number: 
    :param frame: 
    :return: 
    """
    global SIGTERM_RECEIVED

    if signal_number == 15:
        print('SIGTERM received.')
        SIGTERM_RECEIVED = True
    else:
        print(f"Signal received: {signal_number}")

    return

if __name__ == "__main__":
    command_line_main()
