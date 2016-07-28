from __future__ import absolute_import, print_function, unicode_literals

from wagtail.wagtailadmin.edit_handlers import BaseChooserPanel

from .widgets import AdminVideoChooser


class BaseVideoChooserPanel(BaseChooserPanel):
    object_type_name = "video"

    @classmethod
    def widget_overrides(cls):
        return {cls.field_name: AdminVideoChooser}


class VideoChooserPanel(object):
    def __init__(self, field_name):
        self.field_name = field_name

    def bind_to_model(self, model):
        return type(str('_VideoChooserPanel'), (BaseVideoChooserPanel,), {
            'model': model,
            'field_name': self.field_name,
        })
