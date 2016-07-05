from __future__ import absolute_import, unicode_literals

from django import template
from django.forms.widgets import flatatt
from django.template import resolve_variable
from django.utils.text import mark_safe

from wagtailvideos.models import MediaFormats, Video

register = template.Library()
# {% video self.intro_video html5(optional) extra_att extra_att %}


@register.tag(name="video")
def video(parser, token):
    template_params = token.split_contents()[1:] # Everything after 'video'
    video_expr = template_params[0]

    extra_attrs = {}
    html5 = False

    # Everyting after video expression
    if(len(template_params) > 1):
        for param in template_params[1:]:
            if param == 'html5':
                html5 = True
            else:
                try:
                    name, value = param.split('=')
                    extra_attrs[name] = value
                except ValueError:
                    extra_attrs[param] = ''  # attributes without values e.g. autoplay, controls
    return VideoNode(video_expr, html5, extra_attrs)


class VideoNode(template.Node):
    def __init__(self, video, html5=False, attrs={}):
        self.video = template.Variable(video)
        self.html5 = html5
        self.attrs = attrs

    def render(self, context):
        video = self.video.resolve(context)
        if not self.html5:
            return mark_safe("<video {0}><source  src='{1}' type='video/{2}'></video>"
                             .format(flatatt(self.attrs), video.url, video.file_ext)) # FIXME get mimetype properly (extension is not always reliable)
        else:
            transcodes = []
            for media_format in MediaFormats:
                transcode = video.get_transcode(media_format) # FIXME this is blocking when no transcodes are found
                transcodes.append("<source src='{0}' type='video/{1}' >".format(transcode.url, transcode.media_format.name))
            return mark_safe(
                "<video {0}>{1}</video".format(flatatt(self.attrs), "\n".join(transcodes)))
