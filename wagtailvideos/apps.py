from django.apps import AppConfig
from django.core.checks import Error, register
from wagtailvideos.utils import which


def ffmpeg_check(app_configs, path=None, **kwargs):
    errors = []
    if which('ffmpeg', path=path) is None:
        errors.append(
            Error(
                'ffmpeg could not be found on your system, try installing it.',
                hint=None,
                obj='SystemCheckError',
                id='wagtailvideos.E001',
            )
        )
    return errors


class WagtailVideosApp(AppConfig):
    name = 'wagtailvideos'
    label = 'wagtailvideos'
    verbose_name = 'Wagtail Videos'

    def ready(self):
        register(ffmpeg_check)
