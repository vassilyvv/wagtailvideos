from __future__ import absolute_import, unicode_literals

from django import template
from django.template import resolve_variable
from django.utils.text import mark_safe

from wagtailvideos.models import MediaFormats, Video

register = template.Library()
# {% video self.intro_video html5(optional) %}


@register.tag(name="video")
def video(parser, token):
    contents = token.split_contents()
    try:
        video_field = contents[1] # A Video object should be the first variable
    except ValueError:
        raise template.TemplateSyntaxError("video tag requires a Video as the first option")
    if len(contents) > 2:
        return VideoNode(video_field, contents[2] == 'html5')
    else:
        return VideoNode(video_field)

class VideoNode(template.Node):
    def __init__(self, video, html5=False):
        self.video = template.Variable(video)
        self.html5 = html5

    def render(self, context):
        video = self.video.resolve(context)
        if not self.html5:
            return mark_safe("<video controls><source  src='{0}' type='{1}'></video>"
                             .format(video.url, 'video/mp4'))
        else:
            return ''


        # TODO
        # https://github.com/torchbox/wagtail/blob/master/wagtail/wagtailimages/models.py#L500
