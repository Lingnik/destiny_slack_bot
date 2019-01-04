import os

from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader

from bungie_api import BungieApi


def home(request):
    oauth_url = os.environ.get('BUNGIE_OAUTH_URL')
    oauth_client_id = os.environ.get('BUNGIE_OAUTH_CLIENT_ID')
    oauth_client_secret = os.environ.get('BUNGIE_OAUTH_CLIENT_SECRET')

    request_url = oauth_url
    request_url += '?response_type=code'
    request_url += '&client_id={}'.format(oauth_client_id)
    request_url += '&state=12345'  # uh, this should be random... and persisted in the session

    template = loader.get_template('checklist/index.html')
    context = {
        'oauth_url': request_url
    }
    return HttpResponse(template.render(context, request))

def oauth_callback(request):
    oauth_code = request.content_params.get('code')
    bungie_client = BungieApi(os.environ.get('BUNGIE_API_TOKEN'))
    oauth_token = bungie_client.get_oauth_token(oauth_code)
    request.session['oauth_token'] = oauth_token

    template = loader.get_template('checklist/oauth_callback.html')
    context = {}
    return HttpResponse(template.render(context, request))
