"""@Hawthorne bot for Destiny 2.

"""
import os
import json
import pprint
import shlex
import datetime
import time
import signal
import traceback

import redis
import requests
import humanize

from slack_wrapper import SlackApi
from bungie_wrapper import BungieApi, Non200ResponseException

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

CLASSES = {
    '2271682572': {'name': 'Warlock', 'emoji': ':warlock:'},
    '3655393761': {'name': 'Titan', 'emoji': ':titan:'},
    '671679327': {'name': 'Hunter', 'emoji': ':hunter:'}
}

"""Activities that should not be reported at all."""
ACTIVITY_BLACKLIST = [
    (0, 0),
    (82913930, 2166136261),  # Orbit
    (3903562779, 1589650888),  # Tower
    (1048645278, 1686739444)  # Orbit
]

"""Activities that should not be reported when they appear repeatedly back-to-back."""
ACTIVITY_DUPE_BLACKLIST = [
    1019949956  # Forges
]

MAINTENANCE_SLEEP_TIME = 300
SIGTERM_RECEIVED = False
pp = pprint.PrettyPrinter(indent=4)


class Hawthorne:
    """@Hawthorne, the Destiny 2 Slack bot."""


    # region INITIALIZERS

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
            slack_wrapper,
            bungie_wrapper,
            redis_wrapper,
            slack_channel_for_staging_with_real_users=None
    ):
        self.slack_api_token = slack_api_token
        self.slack_incoming_webhook_url = slack_incoming_webhook_url
        self.slack_oauth_client_id = slack_oauth_client_id
        self.slack_oauth_client_secret = slack_oauth_client_secret
        self.slack_oauth_token = slack_oauth_token
        self.bungie_api_token = bungie_api_token
        self.bungie_oauth_token = bungie_oauth_token
        self.slack_channel_hawthorne = slack_channel_hawthorne
        self.slack_channel_for_staging_with_real_users = slack_channel_for_staging_with_real_users
        self.slack_channel_log = slack_channel_log
        self.slack_bot_user_id = slack_bot_user_id
        self.slack = slack_wrapper  # type: SlackApi
        self.bungie = bungie_wrapper  # type: BungieApi
        self.redis = redis_wrapper  # type: redis.Redis

        self.unable_to_find_users_squelch = {}
        self.slack_seen_cache = {}
        self.bungie_manifest = None
        self.bungie_manifest_activity_definitions = None
        self.bungie_manifest_activity_mode_definitions = None
        self.keep_running = False
        self.back_pressure = None
        self.status_thread_ts = None
        self.status_log_thread_ts = None

    @staticmethod
    def instantiate_from_environment(cache_manifests=False):
        """Instantiate a Hawthorne() from environment variables.

            :return: 
            """
        # Fetch environment variables.
        slack_api_token = required_environment_variable('SLACK_API_TOKEN')
        slack_api_bot_token = required_environment_variable('SLACK_API_BOT_TOKEN')
        slack_incoming_webhook_url = required_environment_variable('SLACK_INCOMING_WEBHOOK_URL')
        slack_oauth_client_id = required_environment_variable('SLACK_OAUTH_CLIENT_ID')
        slack_oauth_client_secret = required_environment_variable('SLACK_OAUTH_CLIENT_SECRET')
        slack_oauth_token = optional_environment_variable('SLACK_OAUTH_TOKEN')
        slack_channel_hawthorne = required_environment_variable('SLACK_CHANNEL_HAWTHORNE')
        slack_channel_for_staging_with_real_users = optional_environment_variable(
            'SLACK_CHANNEL_FOR_STAGING_WITH_REAL_USERS')
        slack_channel_log = required_environment_variable('SLACK_CHANNEL_LOG')
        slack_bot_user_id = required_environment_variable('SLACK_BOT_USER_ID')
        bungie_api_token = required_environment_variable('BUNGIE_API_TOKEN')
        bungie_oauth_token = optional_environment_variable('BUNGIE_OAUTH_TOKEN')
        if bungie_oauth_token:
            bungie_oauth_token = json.loads(bungie_oauth_token)
        redis_url = required_environment_variable('REDIS_URL')

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

        # Authenticate with Redis
        my_redis = redis.from_url(redis_url, decode_responses=True)

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
            bungie,
            my_redis,
            slack_channel_for_staging_with_real_users=slack_channel_for_staging_with_real_users
        )
        if cache_manifests:
            bot.cache_bungie_manifests()
        return bot

    # endregion


    # region TICKER LOOP

    def stop(self):
        """Send the instruction to stop the bot after the current tick completes.

        :return: 
        """
        self.keep_running = False

    def start(self):
        """Start the bot running.

        :return: 
        """
        try:
            if self.keep_running:
                raise Exception("Bot instance is already running.")

            # This is a simple loop-based ticker. Every tick of the loop, we execute zero or one actions from the registry.
            # It is not guaranteed to call from the registry at the exactly-correct time: time will drift if call runtime
            # exceeds the frequency or if another method call results in an execution time being missed, but it will attempt
            # to execute things as soon as possible after they are scheduled to be run.

            self.announce("I'm back! [Bot started.]")

            # Register actions that the loop will tick against.
            action_registry = [
                {'method': self.heartbeat, 'frequency': 300, 'last': 0, 'wait': 0, 'calls-api': False},
                {'method': self.cache_bungie_manifests, 'frequency': 86400, 'last': 0, 'wait': 0, 'calls-api': True},
                {'method': self.slash_list, 'frequency': 1, 'last': 0, 'wait': 0, 'calls-api': True},
                {'method': self.cache_player_activities, 'frequency': None, 'last': 0, 'wait': 0, 'calls-api': True},
                {'method': self.report_player_activity, 'frequency': 30, 'last': 0, 'wait': 0, 'calls-api': True},
                {'method': self.dump_slack_history, 'frequency': 86400, 'last': 0, 'wait': 86400, 'calls-api': False},
            ]
            for i, action in enumerate(action_registry):
                action_registry[i]['seq'] = i
            # Enqueue future things that we're waiting on by setting their 'last' to the future.
            for i, action in enumerate(action_registry):
                wait = action['wait']
                if wait > 0:
                    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    action_registry[i]['last'] = now + wait

            # Start the loop.
            self.log(":information_source: Starting action ticker.")
            self.keep_running = True
            while self.keep_running is True:
                if SIGTERM_RECEIVED:
                    self.keep_running = False
                    msg = "I need to feed Louis before he freaks out again, brb. [Heroku is probably restarting me.]"
                    self.announce(msg)
                if self.keep_running is False:
                    self.log(':information_source: Hawthorne has been instructed to stop. Breaking out of tick loop.')
                    break
                self.back_off_if_needed()
                time.sleep(1)  # We sleep by one second to prevent bot spam.
                self.debug('TICK')

                # Try to find an action to call, call it, then break as soon as we call one action.
                sorted_registry = sorted(action_registry, key=lambda x: (x['last'], x['seq']))
                for i, action in enumerate(sorted_registry):
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
                        if bool(os.environ.get('HAWTHORNE_DEBUG', False)):
                            action_call_name = action_call.__name__
                            self.debug(f"Ticking on {action_call_name}. [DEBUG]")
                            action_call()
                        else:
                            try:
                                action_call_name = action_call.__name__
                                self.debug(f"Ticking on {action_call_name}.")
                                action_call()
                                if self.status_thread_ts:
                                    self.status_thread_ts = None
                                    self.status_log_thread_ts = None
                            except Non200ResponseException as e:
                                exc = traceback.format_exc()
                                try:
                                    response_data = json.loads(e.response.text)
                                except json.decoder.JSONDecodeError as e2:
                                    exc = traceback.format_exc()
                                    ts = self.log(f":warning: Exception occurred when parsing json: `{e2}`")
                                    self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
                                    self.log_thread(ts, e.response.text)
                                    break
                                if response_data.get('ErrorStatus') == 'SystemDisabled':
                                    if self.status_thread_ts:
                                        self.log_thread(self.status_log_thread_ts, f'Maintenance message: `{e.response.text}`')
                                        self.log_thread(self.status_thread_ts, 'Bungie.net is still down for maintenance. Will check again in 5 minutes.')
                                        self.back_pressure = MAINTENANCE_SLEEP_TIME
                                        break
                                    self.status_log_thread_ts = self.log(f'Maintenance message: `{e.response.text}`')
                                    self.status_thread_ts = self.announce(
                                        "Looks like Bungie.net is down for maintenance. :thread: for status updates.")
                                    self.back_pressure = MAINTENANCE_SLEEP_TIME
                                    break
                                ts = self.log(f":warning: Non200ResponseException occurred when ticking on {action_call_name}: `{e}`")
                                self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
                                break
                            except Exception as e:
                                exc = traceback.format_exc()
                                ts = self.log(f":warning: Exception occurred when ticking on {action_call_name}: `{e}`")
                                self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
                                break
                        action_registry[action['seq']]['last'] = now
                        break

                # END TICK
                self.debug('TOCK')
        except Exception as e:
            exc = traceback.format_exc()
            ts = self.log(f":big-red-siren: Exception occurred: `{e}`")
            self.log_thread(ts, f"Exception:\n```\n{exc}\n```")

    # endregion


    # region LOGGERS

    def announce(self, message):
        """Announce a message to the default Slack channel as the bot user.
        
        :param message: 
        :return: 
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        print(f"{now} SLACK: {message}")
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
        print(message)
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
        if bool(os.environ.get('HAWTHORNE_DEBUG', False)):
            now = datetime.datetime.now(datetime.timezone.utc)
            print(f"{now} DEBUG: {message}")

    # endregion


    # region TICKER METHODS

    def back_off_if_needed(self):
        """Check whether we have received backpressure from the API and wait a bit.
        
        :return: 
        """
        if self.back_pressure is None:
            return

        seconds = self.back_pressure
        self.log(f':warning: Backpressure signal received. Backing off for {seconds} seconds.')
        time.sleep(seconds)
        self.log(':warning: Backoff ending.')

        self.back_pressure = None

    def heartbeat(self):
        """Log something to the console every 5 minutes to keep the Heroku worker alive.
        
        :return: 
        """
        self.log_local('heartbeat')

    def dump_slack_history(self):
        # TODO: Port this over from the Slack activity exporter, and write a data persistence layer
        """Not implemented.
        
        :return: 
        """
        pass

    def cache_bungie_manifests(self):
        """Cache relevant Bungie manifests.

        :return: 
        """
        self.log(":information_source: Caching Bungie.net manifests...")
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
        self.log(":information_source: Pre-caching player activities...")
        self.report_player_activity(cache_only=True)
        self.log(':information_source: Caching complete')

    def report_player_activity(self, cache_only=False):
        """Report on player activity.

        :return: 
        """
        self.debug('report_player_activity()')
        players_activities = self.get_players_activities(is_cache_run=cache_only)
        for activity in players_activities:
            if isinstance(activity, self.SlackIsNotProperlySetUpException):
                slack_id = activity.context['slack_user']['slack_id']
                slack_display_name = activity.context['slack_user']['slack_display_name']
            else:
                slack_id = activity['slack_member']['slack_id']
                slack_display_name = activity['slack_member']['slack_display_name']

            if not cache_only:
                # Send an appropriate message to users on first contact.
                if isinstance(activity, self.SlackUserHasNoCharacters):
                    if not self.unable_to_find_users_squelch.get(slack_id):
                        self.log(f":warning: Unable to find characters for member: {slack_id} {slack_display_name}")
                    self.unable_to_find_users_squelch[slack_id] = True
                    msg = (
                        "You have some gamer tags in your user profile, but I wasn't able to locate any characters"
                        " for your gamer tags, and your activity won't be shown until that's the case."
                        " Check out the instructions pinned in the sidebar."
                    )
                elif isinstance(activity, self.SlackUserHasNoGamerTags):
                    if not self.unable_to_find_users_squelch.get(slack_id):
                        self.log(f":warning: Player is a member of channel, but has no gamer tags: {slack_id} {slack_display_name}")
                    self.unable_to_find_users_squelch[slack_id] = True
                    msg = (
                        "You currently do not have any gamer tags in your user profile, and your activity won't be shown"
                        " until that's the case. Check out the instructions pinned in the sidebar."
                    )
                else:
                    msg = (
                        "Your in-game activities will be shared in this channel."
                        " Check out the instructions pinned in the sidebar."
                    )
                self.first_seen(slack_id, slack_display_name, msg)

            # Skip doing anything else for users that don't have Slack set up correctly.
            if isinstance(activity, self.SlackIsNotProperlySetUpException):
                continue

            # Handle the case where there is no activity for any of the player's characters.
            active_character = activity['active_character']
            if active_character is None:
                self.debug(f"{slack_id} {slack_display_name}: No activity.")
                continue

            new_activity_hash = activity['activity_context']['currentActivityHash']
            new_activity_mode_hash = activity['activity_context']['currentActivityModeHash']
            new_activity_ts = activity['activity_context']['epochActivityStarted']

            # We use Redis to cache past activities to ensure we aren't too noisy. Redis needs some keys.
            membership_type = activity['destiny_membership_type']
            membership_id = activity['destiny_membership_id']
            #membership_activities_list_key = f"activities!{membership_type}!{membership_id}"
            activity_instance_key = f"activity!{membership_type}!{membership_id}!{active_character}!{new_activity_hash}!{new_activity_ts}"
            membership_latest_activity_key = f"latest_activity!{membership_type}!{membership_id}"

            # Skip activities that have already been seen and, for some reason, are being seen again
            if self.redis.exists(activity_instance_key):
                self.debug(f"{slack_id} {slack_display_name}: SEEN: {activity_instance_key}")
                continue
            # Skip activities that are older than the most recently seen activity.
            membership_latest_activity = self.redis.get(f"{membership_latest_activity_key}!ts")
            if membership_latest_activity and new_activity_ts < float(membership_latest_activity):
                self.debug(f"{slack_id} {slack_display_name}: Activity older than most recent: {activity_instance_key}")
                continue

            #day = str(datetime.datetime.utcfromtimestamp(new_activity_ts).isoformat()[0:11])
            #activity_day_bucket = f"activity-bucket!{day}"
            #activity_day_membership_bucket = f"activity-bucket!{day}!{membership_type}!{membership_id}"

            # Update the cache.
            old_activity_hash = self.redis.get(f"{membership_latest_activity_key}!activity")
            old_activity_char = self.redis.get(f"{membership_latest_activity_key}!active_character")
            self.redis.set(f"{membership_latest_activity_key}!ts", new_activity_ts)
            self.redis.set(f"{membership_latest_activity_key}!activity", new_activity_hash)
            self.redis.set(f"{membership_latest_activity_key}!active_character", active_character)
            self.redis.set(f"{membership_latest_activity_key}!activity_json", json.dumps(activity))
            #self.redis.lpush(membership_activities_list_key, activity_instance_key, ex=datetime.timedelta(days=30))
            self.redis.set(activity_instance_key, 1, ex=datetime.timedelta(days=30))

            # Finally, announce the activity (if we need to).
            if not cache_only:
                # Skip reporting activities that we aren't interested in.
                if self._activity_is_blacklisted(new_activity_hash, new_activity_mode_hash):
                    self.debug(f"SKIP reporting uninteresting activity: {activity_instance_key}")
                    continue

                # Skip reporting duplicate activities that don't need to be reported.
                for blacklist_activity_hash in ACTIVITY_DUPE_BLACKLIST:
                    if (new_activity_hash == blacklist_activity_hash and
                            new_activity_hash == old_activity_hash and
                            active_character == old_activity_char
                        ):
                        self.debug(f"SKIP reporting duplicate activity: {activity_instance_key}")
                        continue

                # Announce the activity.
                msg = self.activity_message_for(activity)
                self.announce(msg)
                membership_key = f"{activity['destiny_membership_type']}-{activity['destiny_membership_id']}"
                self.log_local(f":information_source: {membership_key}: {new_activity_hash}")

    def slash_list(self):
        """List current player activities by request.
        
        :return: 
        """
        if not self.redis.llen('slash.list'):
            return False

        queued_cmd = self.redis.rpop('slash.list')
        channel_id, user_id = queued_cmd.split(',')

        self.log(f":information_source: Listing player activities on behalf of {user_id} in {channel_id}...")
        messages = []
        players_activities = self.get_players_activities(is_cache_run=True, fetch_from_cache=True)
        players_activities = sorted(
            players_activities,
            key=lambda x: float(x.get("activity_context", {}).get("epochActivityStarted", 0)) if isinstance(x, dict) else 0
        )
        for activity in players_activities:
            try:
                if activity['active_character'] is None:
                    continue
            except Exception as e:
                exc = traceback.format_exc()
                ts = self.log(f":warning: Exception occurred in slash_list(): `{e}`")
                self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
                continue
            if self._activity_is_blacklisted(activity['activity'], activity['activity_mode']):
                continue
            messages.append(self.activity_message_for(activity, include_start=True))
        messages = '\n'.join(messages)
        message = f"Here's what folk are currently doing:\n{messages}"
        self.slack.slack_as_bot.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=message,
            parse='mrkdwn'
        )

    # endregion


    # region CUSTOM EXCEPTIONS

    class SlackIsNotProperlySetUpException(Exception):
        """An exception that conveys a Slack member's user profile is not set up properly."""
        def __init__(self, message, context: dict = None):
            super().__init__(message)
            self.context = context

    class SlackUserHasNoGamerTags(SlackIsNotProperlySetUpException):
        """An exception that conveys a Slack member has no gamertags in their user profile."""
        def __init__(self, message="Slack User Has No Gamer Tags", context: dict = None):
            super().__init__(message, context)

    class SlackUserHasNoCharacters(SlackIsNotProperlySetUpException):
        """An exception that conveys a Slack member has no gamertags that could be found on their platform(s)."""
        def __init__(self, message="Slack User Has No Gamer Tags", context: dict = None):
            super().__init__(message, context)

    # endregion


    # region HELPER METHODS

    @staticmethod
    def _activity_is_blacklisted(new_activity_hash, new_activity_mode_hash):
        for blacklist_activity_hash, blacklist_activity_mode_hash in ACTIVITY_BLACKLIST:
            if new_activity_hash == blacklist_activity_hash and new_activity_mode_hash == blacklist_activity_mode_hash:
                return True

    def first_seen(self, slack_id, slack_name, msg):
        """Onboard a user when they first join the channel.
        
        :param slack_id: 
        :param slack_name: 
        :param msg: 
        :return: 
        """
        if not self.slack_seen_cache.get(slack_id):
            slack_channel = self.slack_channel_hawthorne
            message = f":hawthorne: :wave: Welcome to <#{slack_channel}>, <@{slack_id}>! {msg}"
            self.log(f":wave: First seen: {slack_id} {slack_name}")
            try:
                self.slack.slack_as_bot.chat_postEphemeral(
                    channel=slack_channel,
                    user=slack_id,
                    text=message,
                    parse='mrkdwn'
                )
            except Exception as e:
                exc = traceback.format_exc()
                ts = self.log(f":warning: Exception occurred in first_seen(): `{e}`")
                self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
            self.slack_seen_cache[slack_id] = True

    def get_players_activities(self, is_cache_run=False, fetch_from_cache=False):
        """Get a list of players (dicts) of a channel and their most recent activity.
        
        :return: 
        """
        self.debug(f'get_players_activities({is_cache_run=}')
        players_activities = []
        slack_channel = self.slack_channel_hawthorne
        if self.slack_channel_for_staging_with_real_users:
            slack_channel = self.slack_channel_for_staging_with_real_users
        channel_members = self.fetch_slack_channel_members(slack_channel)

        for member in channel_members:
            slack_id = member['slack_id']
            slack_name = member['slack_display_name']
            if is_cache_run:
                self.slack_seen_cache[slack_id] = True
            try:
                activity = self.get_activity_for_slack_user(member, fetch_from_cache=fetch_from_cache)
                players_activities.append(activity)
                self.unable_to_find_users_squelch[slack_id] = False
            except self.SlackUserHasNoGamerTags as e:
                players_activities.append(e)
            except self.SlackUserHasNoCharacters as e:
                players_activities.append(e)

        return players_activities

    def get_membership_for_slack_user(self, slack_user):
        """Get a Bungie.net membership for a given Slack user. 
        
        :param slack_user: 
        :return: 
        """
        self.debug(f'get_membership_for_slack_user({slack_user=})')
        # Ask for the user by gamertag and fetch their Bungie.net profile.
        if 'destiny_psn_id' in slack_user and slack_user['destiny_psn_id']:
            player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_PSN,
                                                  display_name=slack_user['destiny_psn_id'])
        elif 'destiny_stm_id' in slack_user and slack_user['destiny_stm_id']:
            player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_STEAM,
                                                  display_name=slack_user['destiny_stm_id'])
        elif 'destiny_xbl_id' in slack_user and slack_user['destiny_xbl_id']:
            player = self.bungie.search_d2_player(membership_type=MEMBERSHIP_TYPE_XBOX,
                                                  display_name=slack_user['destiny_xbl_id'])
        else:
            raise self.SlackUserHasNoGamerTags(context={'slack_user': slack_user})
        if len(player) == 0:
            raise self.SlackUserHasNoCharacters(context={'slack_user': slack_user})
        player_name = player[0]['displayName']
        membership_type = player[0]['membershipType']
        membership_id = player[0]['membershipId']

        return player, player_name, membership_type, membership_id

    def get_activity_for_slack_user(self, slack_user, fetch_from_cache=False):
        """Get the latest activity for a Slack user based on their user profile gamertags.
        
        :param slack_user: dict
        :param fetch_from_cache: 
        :return: 
        """
        self.debug(f'get_activity_for_slack_user({slack_user=}')
        player, player_name, membership_type, membership_id = self.get_membership_for_slack_user(slack_user)

        if fetch_from_cache:
            membership_latest_activity_key = f"latest_activity!{membership_type}!{membership_id}!activity_json"
            latest_activity = self.redis.get(membership_latest_activity_key)
            try:
                latest_activity = json.loads(str(latest_activity))
            except Exception as e:
                exc = traceback.format_exc()
                ts = self.log(f":warning: Exception occurred in get_activity_for_slack_user(): `{e}`")
                self.log_thread(ts, f"Exception:\n```\n{exc}\n```")
            return latest_activity

        # Get the "current" activity for the player and hydrate that with additional context.
        character_activities = self.bungie.get_current_activity(membership_type, membership_id)
        most_recent_activity = None
        for character_id in character_activities['characterActivities']:
            character_key = f'{membership_type}-{membership_id}-{character_id}'
            tmp_activity_hash = character_activities['characterActivities'][character_id]['currentActivityHash']
            tmp_activity_mode_hash = character_activities['characterActivities'][character_id]['currentActivityModeHash']

            # Find the character with the most recent activity by epoch:
            tmp_activity_epoch = character_activities['characterActivities'][character_id]['epochActivityStarted']
            tmp_char_activity_key = f'activity.{character_key}.{tmp_activity_hash}.{tmp_activity_mode_hash}'
            if not most_recent_activity or tmp_activity_epoch > most_recent_activity['epochActivityStarted']:
                most_recent_activity = character_activities['characterActivities'][character_id]

        activity = most_recent_activity['currentActivityHash']
        activity_mode = most_recent_activity['currentActivityModeHash']
        active_character = most_recent_activity['characterId']

        most_recent_activity_blacklisted = False
        for blacklist_activity_hash, blacklist_activity_mode_hash in ACTIVITY_BLACKLIST:
            if (activity == blacklist_activity_hash and
                activity_mode == blacklist_activity_mode_hash):
                most_recent_activity_blacklisted = True

        activity_name = None
        character = None
        character_class = None
        if active_character is not None and not most_recent_activity_blacklisted:
            activity_name = ""
            activity = self.bungie_manifest_activity_definitions[str(activity)]
            if not activity["displayProperties"].get("name"):
                activity_str = pp.pformat(activity)
                character_str = pp.pformat(character_activities['characterActivities'])
                self.log_local(f"Error in activity data, missing 'name': {activity_str}\n{character_str}")
            activity_name += activity["displayProperties"].get("name", "Unknown")
            try:
                activity_mode = self.bungie_manifest_activity_mode_definitions[str(activity_mode)]
                if not activity_mode["displayProperties"].get("name"):
                    activity_str = pp.pformat(activity_mode)
                    self.log_local(f"Error in activity mode data, missing 'name': {activity_str}")
                activity_name = "{} - {}".format(activity_mode["displayProperties"]["name"], activity_name)
            except:
                pass
            if activity["activityLightLevel"] > 0:
                activity_name = "{} (PL{})".format(activity_name, activity["activityLightLevel"])
            character = self.bungie.get_d2_character(membership_type, membership_id, active_character, ['200'])
            character_class = character.get('character', {}).get('data', {}).get('classHash', 0)
            character_class = CLASSES.get(str(character_class))


        return_activity = {
            'slack_member': slack_user,
            'destiny_player': player,
            'destiny_player_name': player_name,
            'destiny_membership_type': membership_type,
            'destiny_membership_id': membership_id,
            'destiny_character': character,
            'destiny_character_class': character_class,
            'activity': activity,
            'activity_mode': activity_mode,
            'active_character': active_character,
            'activity_name': activity_name,
            'transitory_data': character_activities.get('transitoryData'),
            'activity_context': most_recent_activity
        }
        return return_activity

    @staticmethod
    def activity_emoji_for(activity_name):
        """Return an emoji for a particular activity name.
        
        :param activity_name: 
        :return: 
        """
        emoji = ""
        if activity_name.startswith('Explore - '):
            emoji = ':fireteam:'
        elif activity_name.startswith('Control - '):
            emoji = ':crucible:'
        elif activity_name.startswith('Garden of Salvation'):
            emoji = ':raid2:'
        elif activity_name.startswith('Team Scorched - '):
            emoji = ':crucible:'
        elif activity_name.startswith('Scored Nightfall Strikes - '):
            emoji = ':nightfall:'
        elif activity_name.startswith('Normal Strikes - '):
            emoji = ':vanguard2:'
        elif activity_name.startswith('Clash - '):
            emoji = ':crucible:'
        elif activity_name.startswith('Gambit '):
            emoji = ':gambit:'
        elif activity_name.startswith('Dungeon - '):
            emoji = ':dungeon:'
        elif activity_name.startswith('Story - The Shattered Throne'):
            emoji = ':dungeon:'
        elif activity_name.startswith('Crucible'):
            emoji = ':crucible:'
        elif activity_name.startswith('Rumble'):
            emoji = ':crucible:'
        elif activity_name.startswith('Story -'):
            emoji = ':fireteam:'
        return emoji

    def fetch_slack_channel_members(self, slack_channel_id):
        """Fetch all the Slack members for a channel and their various Destiny usernames.

        :param slack_channel_id: 
        :return: 
        """
        self.debug(f'fetch_slack_channel_members({slack_channel_id=})')
        channel_members = []
        raw_members = self.slack.slack_as_user.channels_info(channel=slack_channel_id).data['channel'].get(
            'members')
        for member_id in raw_members:
            mute_timestamp_expiration = self.redis.get(f'mute.{member_id}')
            if mute_timestamp_expiration:
                mute_timestamp_expiration = float(mute_timestamp_expiration)
                now = datetime.datetime.now().timestamp()
                if now > mute_timestamp_expiration:
                    self.redis.delete(f'mute.{member_id}')
                else:
                    continue
            member = self.slack.slack_as_user.users_profile_get(user=member_id)
            if 'bot_id' in member['profile']:
                continue
            member_fields = member.data.get('profile', {}).get('fields', {}) or {}
            slack_display_name = member.data.get('profile', {}).get('display_name', None)
            if not slack_display_name or slack_display_name == '':
                slack_display_name = member.data.get('profile', {}).get('real_name', None)
            record = {
                'slack_id': member_id,
                'slack_display_name': slack_display_name,
                'destiny_psn_id': member_fields.get(SLACK_FIELD_PSN, {}).get('value', None),
                'destiny_xbl_id': member_fields.get(SLACK_FIELD_XBL, {}).get('value', None),
                'destiny_stm_id': member_fields.get(SLACK_FIELD_STM, {}).get('value', None)
            }
            channel_members.append(record)
        return channel_members

    def activity_message_for(self, activity, include_start=False):
        """Return a Slack-formatted message (raw, not blocks) representing the current activity.
        
        :param activity: 
        :param include_start:
        :return: 
        """
        slack_display_name = activity["slack_member"]["slack_display_name"]
        destiny_player_name = activity["destiny_player_name"]
        character_class = activity["destiny_character_class"]
        if character_class:
            character_class_emoji = character_class['emoji']
        else:
            character_class_emoji = ""
        activity_name = activity["activity_name"]
        if not activity_name:
            activity_name = 'Unknown'
        activity_emoji = self.activity_emoji_for(activity_name)
        if not slack_display_name:
            display_name = f'*{destiny_player_name}*'
        else:
            display_name = f'*{destiny_player_name}* (@{slack_display_name})'

        if include_start:
            now = datetime.datetime.now(datetime.timezone.utc)
            date_activity_started = activity["activity_context"]["epochActivityStarted"]
            delta = now.timestamp() - date_activity_started
            delta = datetime.timedelta(seconds=delta)
            delta_human = humanize.naturaltime(delta)
            msg = f'{character_class_emoji} {display_name} started playing {activity_emoji} *{activity_name}* _{delta_human}_'
        else:
            msg = f'{character_class_emoji} {display_name} is playing {activity_emoji} *{activity_name}*'

        return msg

    pass
    # endregion


# region COMMAND LINE HANDLER

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

def start_hawthorne():
    """CLI entrypoint. Instantiates and starts Hawthorne."""

    bot = Hawthorne.instantiate_from_environment()
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

# endregion

if __name__ == "__main__":
    start_hawthorne()
