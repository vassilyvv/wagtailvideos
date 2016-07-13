from __future__ import absolute_import, unicode_literals

from django import template
from django.forms.widgets import flatatt
from django.template import resolve_variable
from django.utils.text import mark_safe
from wagtailvideos.models import MediaFormats, Video

register = template.Library()
# {% video self.intro_video extra_att extra_att %}


@register.tag(name="video")
def video(parser, token):
    template_params = token.split_contents()[1:] # Everything after 'video'
    video_expr = template_params[0]

    extra_attrs = {}

    # Everyting after video expression
    if(len(template_params) > 1):
        for param in template_params[1:]:
            try:
                name, value = param.split('=')
                extra_attrs[name] = value
            except ValueError:
                extra_attrs[param] = ''  # attributes without values e.g. autoplay, controls
    return VideoNode(video_expr, extra_attrs)


class VideoNode(template.Node):
    def __init__(self, video, attrs={}):
        self.video = template.Variable(video)
        self.attrs = attrs

    def render(self, context):
        video = self.video.resolve(context)

        if not video:
            raise template.TemplateSyntaxError("video tag requires a Video object as the first parameter")

        sources = ["<source src='{0}' type='video/{1}'>"
                         .format(video.url, video.file_ext)]  # TODO get mimetype properly (extension is not always reliable)

        transcodes = video.transcodes.exclude(processing=True).filter(error_message__exact='')
        for transcode in transcodes:
             sources.append("<source src='{0}' type='video/{1}' >".format(transcode.url, transcode.media_format.name))
        sources.append("<p>Sorry, your browser doesn't support playback for this video</p>")
        return mark_safe(
            "<video {0}>{1}</video>".format(flatatt(self.attrs), "\n".join(sources)))
