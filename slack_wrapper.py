"""A wrapper around Slacker and the official Slack Python API.

Mostly to make oauth and client persistence easier.
"""
from urllib import parse as urllib_parse
from slacker import Slacker
from slack import WebClient


class SlackApi:
    """A lean Python Slack API wrapper, using slacker and the official Slack API under the hood."""
    def __init__(self, oauth_client_id=None, oauth_client_secret=None, oauth_scope=None, incoming_webhook_url=None,
                 oauth_user_token=None, oauth_bot_token=None):
        self.incoming_webhook_url = incoming_webhook_url

        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self.oauth_scope = '+'.join(oauth_scope) if isinstance(oauth_scope, list) else oauth_scope

        self.oauth_user_token = oauth_user_token
        self.oauth_bot_token = oauth_bot_token

        self.slack_as_user = None  # type: WebClient
        self.slack_as_bot = None  # type: WebClient
        self.slack_as_noauth = WebClient("")  # type: WebClient
        self.slacker_as_user = None  # type: Slacker
        self.slacker_as_bot = None  # type: Slacker

    def start_auth(self):
        """Send the user to a URL for initiating the OAuth flow.
        
        :return: 
        """
        auth_url = f"https://slack.com/oauth/authorize?scope={ self.oauth_scope }"
        auth_url += f"&client_id={ self.oauth_client_id }"
        redirect_uri = urllib_parse.quote('https://hawthorne-slack-bot.herokuapp.com/slack_auth', safe='')
        auth_url += f"&redirect_uri={ redirect_uri }"
        return auth_url

    def finish_auth(self, auth_code):
        """A method to complete OAuth authentication, given a code provided by the initial authentication to Slack.
        
        :param auth_code: 
        :return: 
        """
        response = self.slack_as_noauth.oauth_access(
            client_id=self.oauth_client_id,
            client_secret=self.oauth_client_secret,
            code=auth_code
        )
        self.oauth_user_token = response['access_token']
        import pprint
        pp = pprint.PrettyPrinter(indent=4)
        pp.pprint(response.data)
        if 'bot' in response and 'bot_access_token' in response['bot']:
            self.oauth_bot_token = response['bot']['bot_access_token']
        response = self.auth(self.oauth_user_token, self.oauth_bot_token)
        return response

    def auth(self, oauth_user_token, oauth_bot_token):
        """Authenticate against the API with the specified optional tokens.
        
        :param oauth_user_token: 
        :param oauth_bot_token: 
        :return: 
        """
        if oauth_user_token:
            self.slack_as_user = WebClient(oauth_user_token)
            self.slacker_as_user = Slacker(oauth_user_token, self.incoming_webhook_url)
            self._auth_slack(self.slacker_as_user)
        if oauth_bot_token:
            self.slack_as_bot = WebClient(oauth_bot_token)
            self.slacker_as_bot = Slacker(oauth_bot_token, self.incoming_webhook_url)
            self._auth_slack(self.slacker_as_bot)

        return self.slack_as_user, self.slack_as_bot, self.slacker_as_user, self.slacker_as_bot

    @staticmethod
    def _auth_slack(slack):
        """Get basic info about the slack instance to ensure the authentication token works
    
        :param slack: 
        :return: 
        """
        test_auth = slack.auth.test().body
        #team_name = test_auth['team']
        #current_user = test_auth['user']
        #print("Successfully authenticated for team {0} and user {1} ".format(team_name, current_user))
        return test_auth

    def post_message_raw(self, data):
        """Send a raw data message to the incoming webhook.
        
        :param data: A Python object following the Slacker.IncomingWebhook.data format, usually {"text": "A MESSAGE"}.
        :return: The raw HTTP response 
        """
        response = self.slacker_as_user.incomingwebhook.post(data)
        return response

    def post_message(self, message):
        """
        
        :param message: A text-based message to be sent by the bot user. 
        :return: 
        """
        return self.post_message_raw({"text": message})
