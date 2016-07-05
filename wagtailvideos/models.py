from __future__ import unicode_literals

import os
import os.path
import shutil
import subprocess
import tempfile
from tempfile import NamedTemporaryFile

import django
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from enum import Enum
from PIL import Image
from taggit.managers import TaggableManager
from unidecode import unidecode
from wagtail.wagtailadmin.taggable import TagSearchable
from wagtail.wagtailadmin.utils import get_object_usage
from wagtail.wagtailcore.models import CollectionMember
from wagtail.wagtailsearch import index
from wagtail.wagtailsearch.queryset import SearchableQuerySetMixin

from enumchoicefield import ChoiceEnum, EnumChoiceField


class MediaFormats(ChoiceEnum):
    webm = 'VP8 and Vorbis in WebM'
    mp4 = 'H.264 and MP3 in Mp4'
    ogg = 'Theora and Voris in Ogg'


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
        folder_name = 'original_videos'
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
    def url(self):
        return self.file.url

    def filename(self, include_ext=True):
        if include_ext:
            return os.path.basename(self.file.name)
        else:
            return os.path.splitext(os.path.basename(self.file.name))[0]

    @property
    def file_ext(self):
        return os.path.splitext(self.filename())[1][1:]

    def is_editable_by_user(self, user):
        from wagtail.wagtailimages.permissions import permission_policy
        return permission_policy.user_has_permission_for_instance(user, 'change', self)

    @classmethod
    def get_transcode_model(cls):
        if django.VERSION >= (1, 9):
            return cls.transcodes.rel.related_model
        else:
            return cls.transcodes.related.related_model

    def get_transcode(self, media_format):
        Transcode = self.get_transcode_model()
        try:
            return self.transcodes.get(media_format=media_format)
        except Transcode.DoesNotExist:
            return self.do_transcode(media_format)

    def do_transcode(self, media_format, force=False):
        input_file = self.file.path
        output_dir = tempfile.mkdtemp()
        transcode_name = "{0}.{1}".format(
            self.filename(include_ext=False),
            media_format.name)

        output_file = os.path.join(output_dir, transcode_name)
        FNULL = open(os.devnull, 'r')
        try:
            if media_format is MediaFormats.ogg:
                subprocess.check_call([
                    'ffmpeg',
                    '-i', input_file,
                    '-codec:v', 'libtheora',
                    '-qscale:v', '7',
                    '-codec:a', 'libvorbis',
                    '-qscale:a', '5',
                    output_file,
                ], stdin=FNULL)
            elif media_format is MediaFormats.mp4:
                subprocess.check_call([
                    'ffmpeg',
                    '-i', input_file,
                    '-codec:v', 'libx264',
                    '-preset', 'slow', # TODO Checkout other presets
                    '-crf', '22',
                    '-codec:a', 'copy',
                    output_file,
                ])
            elif media_format is MediaFormats.webm:
                subprocess.check_call([
                    'ffmpeg',
                    '-i', input_file,
                    '-codec:v', 'libvpx',
                    '-crf', '10',
                    '-b:v', '1M',
                    '-codec:a', 'libvorbis',
                    output_file,
                ])
            else:
                return None
            transcoded_file = ContentFile(
                open(output_file, 'rb').read(), transcode_name)

        except subprocess.CalledProcessError:
            return None

        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

        transcode, created = self.transcodes.get_or_create(
            media_format=media_format,
            defaults={'file': transcoded_file}
        )

        return transcode

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
        raise ImproperlyConfigured("WAGTAILVIDEOS_VIDEO_MODEL must be of the form 'app_label.model_name'")

    #TODO is this neccescary ??
    image_model = apps.get_model(app_label, model_name)
    if image_model is None:
        raise ImproperlyConfigured(
            "WAGTAILVIDEOS_VIDEO_MODEL refers to model '%s' that has not been installed" %
            settings.WAGTAILIMAGES_IMAGE_MODEL
        )
    return image_model


class AbstractVideoTranscode(models.Model):
    media_format = EnumChoiceField(MediaFormats)
    file = models.FileField(
        verbose_name=_('file'), upload_to=get_upload_to) # FIXME get_transcode_upload_to

    @property
    def url(self):
        return self.file.url

    def get_upload_to(self, filename):
        folder_name = 'video_transcodes'
        filename = self.file.field.storage.get_valid_name(filename)
        return os.path.join(folder_name, filename)

    class Meta:
        abstract = True


class VideoTranscode(AbstractVideoTranscode):
    video = models.ForeignKey(Video, related_name='transcodes')

    class Meta:
        unique_together = (
            ('video', 'media_format')
        )
