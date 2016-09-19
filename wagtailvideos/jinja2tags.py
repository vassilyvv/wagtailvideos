from __future__ import absolute_import, unicode_literals

import mimetypes

from jinja2.ext import Extension

from django import template
from django.forms.widgets import flatatt
from django.utils.text import mark_safe


def video(video, attrs):
    if not video:
        return ''

    if attrs:
        return video.video_tag(attrs)
    else:
        return video


class WagtailVideosExtension(Extension):

    def __init__(self, environment):
        super(WagtailVideosExtension, self).__init__(environment)

        self.environment.globals.update({
            'video': video,
        })

videos = WagtailVideosExtension
