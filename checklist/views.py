from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader

from bungie_api import BungieApi


def home(request):
    c = BungieApi()

    deracinist_d2 = c.search_d2_player('Deracinist')

    template = loader.get_template('checklist/index.html')
    context = {
        'deracinist_d2': deracinist_d2
    }
    return HttpResponse(template.render(context, request))
