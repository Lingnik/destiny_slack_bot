import os
import json
import redis
import datetime

r = redis.from_url(os.environ.get("REDIS_URL"), decode_responses=True)

from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.views.decorators.csrf import csrf_exempt

from bungie_wrapper import BungieApi
from hawthorne import Hawthorne
from utilities import logger


def home(request):

    oauth_url = os.environ.get('BUNGIE_OAUTH_URL')
    oauth_client_id = os.environ.get('BUNGIE_OAUTH_CLIENT_ID')
    oauth_client_secret = os.environ.get('BUNGIE_OAUTH_CLIENT_SECRET')

    request_url = oauth_url
    request_url += '?response_type=code'
    request_url += '&client_id={}'.format(oauth_client_id)
    request_url += '&state=12345'  # uh, this should be random... and persisted in the session
    request_url += '&redirect=/homepage'

    template = loader.get_template('checklist/index.html')
    context = {
        'oauth_url': request_url
    }
    return HttpResponse(template.render(context, request))

def oauth_callback(request):
    oauth_token = request.session.get('oauth_token')
    if not oauth_token:
        oauth_code = request.GET.get('code')
        bungie_client = BungieApi(os.environ.get('BUNGIE_API_TOKEN'))
        oauth_token = bungie_client.get_oauth_token(oauth_code, persist=True)
        request.session['oauth_token'] = oauth_token

    bungie_client = BungieApi(os.environ.get('BUNGIE_API_TOKEN'), oauth_token=request.session['oauth_token'])

    current_user = bungie_client.get_user_currentuser_membership()
    memberships = []
    for membership in current_user.get('destinyMemberships'):
        bungie_client.get_d2_profile(
            membership.get('membershipId'),
            membership.get('membershipType'),
            ['100']
        )
        memberships.append(membership)

    template = loader.get_template('checklist/oauth_callback.html')
    context = {
        'manifest': bungie_client.get_d2_manifest(),
        'oauth_token': json.dumps(oauth_token, indent=4),
        'current_user': json.dumps(current_user, indent=4),
        'memberships': json.dumps(memberships, indent=4),
    }
    return HttpResponse(template.render(context, request))

@csrf_exempt
def bot_slash_command(request):
    """Handle Slack /hawthorne commands.
    
    :param request: 
    :return: 
    """
    response_url = str(request.POST.get('response_url'))
    channel_id = str(request.POST.get('channel_id'))
    user_id = str(request.POST.get('user_id'))
    command = str(request.POST.get('text'))
    command = command.strip()

    print(f"<@{user_id}> ran a command in <#{channel_id}>: /hawthorne {command}")

    if command == 'help':
        # /hawthorne help
        template = loader.get_template('checklist/bot_slash_help.txt')
        context = {
            'response_url': response_url,
            'user_id': user_id,
            'channel_id': channel_id,
        }
        return HttpResponse(template.render(context, request))
    if command == 'unmute':
        # /hawthorne unmute
        r.delete(f'mute.{user_id}')
        return HttpResponse('Your status will appear in #hawthorne again.')
    if command.startswith('mute '):
        # /hawthorne mute 1h
        hours = command.split(' ')[1]
        hours = hours.strip('h')
        try:
            hours = int(hours)
        except Exception as e:
            return HttpResponse(status=500, content=(
                'I was unable to recognize the number you provided for hours.'
                ' You provided `{command.split(' ')[1]}` which does not match the integer format `8h` or `8`.'
            ))
        timestamp = datetime.datetime.now().timestamp() + (hours * 60.0 * 60.0)
        r.set(f'mute.{user_id}', timestamp)
        return HttpResponse(f'I will hide your activity for {hours} hours.')
    if command == 'list':
        # /hawthorne list
        r.lpush('slash.list', f'{channel_id},{user_id}')
        return HttpResponse(":wave: Hang on a sec, I'll fetch player activities and get back to you.")
    return HttpResponse(
        ("I couldn't understand your command. Try `/hawthorne help`.\n"
         f"Your command: `/hawthorne {command}`"))
