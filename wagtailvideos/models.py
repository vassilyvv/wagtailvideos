from __future__ import unicode_literals

import os
import os.path
import shutil
import subprocess
import tempfile
from tempfile import NamedTemporaryFile

from PIL import Image

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from taggit.managers import TaggableManager
from unidecode import unidecode
from wagtail.wagtailadmin.taggable import TagSearchable
from wagtail.wagtailadmin.utils import get_object_usage
from wagtail.wagtailcore.models import CollectionMember
from wagtail.wagtailsearch import index
from wagtail.wagtailsearch.queryset import SearchableQuerySetMixin


class VideoQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


def get_upload_to(instance, filename):
    # Dumb proxy to instance method.
    return instance.get_upload_to(filename)


@python_2_unicode_compatible
class AbstractVideo(CollectionMember, TagSearchable):
    title = models.CharField(max_length=255, verbose_name=_('title'))
    file = models.FileField(
        verbose_name=_('file'), upload_to=get_upload_to)
    thumbnail = models.ImageField()
    created_at = models.DateTimeField(verbose_name=_('created at'), auto_now_add=True, db_index=True)
    uploaded_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_('uploaded by user'),
        null=True, blank=True, editable=False, on_delete=models.SET_NULL
    )

    tags = TaggableManager(help_text=None, blank=True, verbose_name=_('tags'))

    file_size = models.PositiveIntegerField(null=True, editable=False)

    objects = VideoQuerySet.as_manager()

    def is_stored_locally(self):
        """
        Returns True if the image is hosted on the local filesystem
        """
        try:
            self.file.path

            return True
        except NotImplementedError:
            return False

    def get_file_size(self):
        if self.file_size is None:
            try:
                self.file_size = self.file.size
            except OSError:
                # File doesn't exist
                return

            self.save(update_fields=['file_size'])

        return self.file_size

    def get_upload_to(self, filename):
        folder_name = 'original_images'
        filename = self.file.field.storage.get_valid_name(filename)

        # do a unidecode in the filename and then
        # replace non-ascii characters in filename with _ , to sidestep issues with filesystem encoding
        filename = "".join((i if ord(i) < 128 else '_') for i in unidecode(filename))

        # Truncate filename so it fits in the 100 character limit
        # https://code.djangoproject.com/ticket/9893
        while len(os.path.join(folder_name, filename)) >= 95:
            prefix, dot, extension = filename.rpartition('.')
            filename = prefix[:-1] + dot + extension
        return os.path.join(folder_name, filename)

    def get_usage(self):
        return get_object_usage(self)

    @property
    def usage_url(self):
        return reverse('wagtailvideos:image_usage',
                       args=(self.id,))

    search_fields = TagSearchable.search_fields + CollectionMember.search_fields + (
        index.FilterField('uploaded_by_user'),
    )

    def __str__(self):
        return self.title

    def get_rendition(self, filter):
        pass # TODO

    def get_thumbnail(self):
        file_path = self.file.path
        try:
            output_dir = tempfile.mkdtemp()
            output_file = os.path.join(output_dir, 'thumbnail.jpg')
            try:
                FNULL = open(os.devnull, 'r')
                subprocess.check_call([
                    'ffmpeg',
                    '-itsoffset',
                    '-4',
                    '-i', file_path,
                    '-vcodec', 'mjpeg',
                    '-vframes', '1',
                    '-an', '-f', 'rawvideo',
                    '-s', '320x240',
                    output_file,
                ], stdin=FNULL)
            except subprocess.CalledProcessError:
                return None
            return ContentFile(open(output_file, 'rb').read(), 'thumb.jpg')
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def save(self, **kwargs):
        self.thumbnail = self.get_thumbnail()
        super(AbstractVideo, self).save(**kwargs)

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def default_alt_text(self):
        # by default the alt text field (used in rich text insertion) is populated
        # from the title. Subclasses might provide a separate alt field, and
        # override this
        return self.title

    def is_editable_by_user(self, user):
        from wagtail.wagtailimages.permissions import permission_policy
        return permission_policy.user_has_permission_for_instance(user, 'change', self)

    class Meta:
        abstract = True


class Video(AbstractVideo):
    admin_form_fields = (
        'title',
        'file',
        'collection',
        'tags',
    )


def get_video_model():
    from django.conf import settings
    from django.apps import apps

    try:
        app_label, model_name = settings.WAGTAILVIDEOS_VIDEO_MODEL.split('.')
    except AttributeError:
        return Video
    except ValueError:
        raise ImproperlyConfigured("WAGTAILIMAGES_IMAGE_MODEL must be of the form 'app_label.model_name'")

    image_model = apps.get_model(app_label, model_name)
    if image_model is None:
        raise ImproperlyConfigured(
            "WAGTAILIMAGES_IMAGE_MODEL refers to model '%s' that has not been installed" %
            settings.WAGTAILIMAGES_IMAGE_MODEL
        )
    return image_model
