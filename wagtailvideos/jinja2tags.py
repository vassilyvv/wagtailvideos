from __future__ import absolute_import, unicode_literals

from jinja2.ext import Extension

from .models import Video


def video(video, attrs='preload controls'):
    if type(video) != Video:
        raise TypeError('Expected type {0}, received {1}.'.format(Video, type(video)))
    return video.video_tag(attrs)


class WagtailVideosExtension(Extension):

    def __init__(self, environment):
        super(WagtailVideosExtension, self).__init__(environment)

        self.environment.globals.update({
            'video': video,
        })

videos = WagtailVideosExtension
