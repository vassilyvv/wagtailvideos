from __future__ import unicode_literals

import os
import os.path
import re
import shutil
import subprocess
import tempfile
import threading

import django
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models.signals import post_save, pre_delete
from django.dispatch.dispatcher import receiver
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from enumchoicefield import ChoiceEnum, EnumChoiceField
from taggit.managers import TaggableManager
from unidecode import unidecode
from wagtail.wagtailadmin.taggable import TagSearchable
from wagtail.wagtailadmin.utils import get_object_usage
from wagtail.wagtailcore.models import CollectionMember
from wagtail.wagtailsearch import index
from wagtail.wagtailsearch.queryset import SearchableQuerySetMixin


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
    thumbnail = models.ImageField(upload_to=get_upload_to, null=True, blank=True)
    created_at = models.DateTimeField(verbose_name=_('created at'), auto_now_add=True, db_index=True)
    duration = models.CharField(max_length=255, blank=True)
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
        return reverse('wagtailvideos:video_usage', args=(self.id,))

    search_fields = list(TagSearchable.search_fields) + list(CollectionMember.search_fields) + [
        index.FilterField('uploaded_by_user'),
    ]

    def __str__(self):
        return self.title

    def get_duration(self):
        if self.duration:
            return self.duration

        file_path = self.file.path
        try:
            show_format = subprocess.check_output(['ffprobe', '-i', file_path, '-show_format', '-v', 'quiet'])
            show_format = show_format.decode("utf-8")
            # show_format comes out in key=value pairs seperated by newlines
            duration = re.findall(r'([duration^=]+)=([^=]+)(?:\n|$)', show_format)[0][1]
            hours, remainder = divmod(float(duration), 3600)
            minutes, seconds = divmod(remainder, 60)
            return "%d:%02d:%02d" % (hours, minutes, seconds)
        except subprocess.CalledProcessError:
            return ''

    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail

        file_path = self.file.path
        file_name = self.filename(include_ext=False) + '_thumb.jpg'

        try:
            output_dir = tempfile.mkdtemp()
            output_file = os.path.join(output_dir, file_name)
            try:
                FNULL = open(os.devnull, 'r')
                subprocess.check_call([
                    'ffmpeg',
                    '-v', 'quiet',
                    '-itsoffset', '-4',
                    '-i', file_path,
                    '-vcodec', 'mjpeg',
                    '-vframes', '1',
                    '-an', '-f', 'rawvideo',
                    '-s', '320x240',
                    output_file,
                ], stdin=FNULL)
            except subprocess.CalledProcessError:
                return None
            return ContentFile(open(output_file, 'rb').read(), file_name)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def save(self, **kwargs):
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
        from wagtailvideos.permissions import permission_policy
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
        transcode, created = self.transcodes.get_or_create(
            media_format=media_format,
        )

        if transcode.processing is False:
            transcode.processing = True
            transcode.error_messages = ''
            transcode.save(update_fields=['processing', 'error_message']) # Lock the transcode model
            TranscodingThread(transcode).start()
        else:
            pass  # TODO Queue?

    class Meta:
        abstract = True


class Video(AbstractVideo):
    admin_form_fields = (
        'title',
        'file',
        'collection',
        'tags',
    )


class TranscodingThread(threading.Thread):
    def __init__(self, transcode, **kwargs):
        super().__init__(**kwargs)
        self.transcode = transcode

    def run(self):
        video = self.transcode.video
        media_format = self.transcode.media_format
        input_file = video.file.path
        output_dir = tempfile.mkdtemp()
        transcode_name = "{0}.{1}".format(
            video.filename(include_ext=False),
            media_format.name)

        output_file = os.path.join(output_dir, transcode_name)
        FNULL = open(os.devnull, 'r')
        args = ['ffmpeg', '-hide_banner', '-i', input_file]
        try:
            if media_format is MediaFormats.ogg:
                subprocess.check_output(args + [
                    '-codec:v', 'libtheora',
                    '-qscale:v', '7',
                    '-codec:a', 'libvorbis',
                    '-qscale:a', '5',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            elif media_format is MediaFormats.mp4:
                subprocess.check_output(args + [
                    '-codec:v', 'libx264',
                    '-preset', 'slow', # TODO Checkout other presets
                    '-crf', '22',
                    '-codec:a', 'copy',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            elif media_format is MediaFormats.webm:
                subprocess.check_output(args + [
                    '-codec:v', 'libvpx',
                    '-crf', '10',
                    '-b:v', '1M',
                    '-codec:a', 'libvorbis',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            self.transcode.file = ContentFile(
                open(output_file, 'rb').read(), transcode_name)
            self.transcode.error_message = ''
        except subprocess.CalledProcessError as error:
            self.transcode.error_message = error.output

        finally:
            self.transcode.processing = False
            self.transcode.save()
            shutil.rmtree(output_dir, ignore_errors=True)


# Delete files when model is deleted
@receiver(pre_delete, sender=Video)
def video_delete(sender, instance, **kwargs):
    instance.thumbnail.delete(False)
    instance.file.delete(False)

# Fields that need the actual video file to create
@receiver(post_save, sender=Video)
def video_saved(sender, instance, **kwargs):
    if hasattr(instance, '_from_signal'):
        return
    instance.thumbnail = instance.get_thumbnail()
    instance.duration = instance.get_duration()
    instance.file_size = instance.file.size
    instance._from_signal = True
    instance.save()
    del instance._from_signal

class AbstractVideoTranscode(models.Model):
    media_format = EnumChoiceField(MediaFormats)
    processing = models.BooleanField(default=False)
    file = models.FileField(null=True, blank=True,
        verbose_name=_('file'), upload_to=get_upload_to)
    error_message = models.TextField(blank=True)

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

# Delete files when model is deleted
@receiver(pre_delete, sender=VideoTranscode)
def transcode_delete(sender, instance, **kwargs):
    instance.file.delete(False)
