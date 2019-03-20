import logging
import mimetypes
import os
import os.path
import shutil
import subprocess
import tempfile
import threading

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db.models.signals import post_save, pre_delete
from django.dispatch.dispatcher import receiver
from django.forms.utils import flatatt
from django.urls import reverse
from django.utils.encoding import python_2_unicode_compatible
from django.utils.text import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.db import models
from celery import chain
from enumchoicefield import ChoiceEnum, EnumChoiceField
from taggit.managers import TaggableManager
from wagtail.admin.utils import get_object_usage
from wagtail.core.models import CollectionMember
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from wagtailvideos.tasks import (
    get_video_metadata, schedule_default_transcode, transcoding_task,
)


logger = logging.getLogger(__name__)


class VideoQuality(ChoiceEnum):
    default = 'Default'
    lowest = 'Low'
    highest = 'High'


class MediaFormats(ChoiceEnum):
    webm = 'VP8 and Vorbis in WebM'
    mp4 = 'H.264 and MP3 in Mp4'
    ogg = 'Theora and Voris in Ogg'
    default = 'Default codec'

    def get_quality_param(self, quality):
        if self is MediaFormats.webm:
            return {
                VideoQuality.lowest: '50',
                VideoQuality.default: '22',
                VideoQuality.highest: '4'
            }[quality]
        elif self is MediaFormats.mp4:
            return {
                VideoQuality.lowest: '28',
                VideoQuality.default: '24',
                VideoQuality.highest: '18'
            }[quality]
        elif self is MediaFormats.ogg:
            return {
                VideoQuality.lowest: '5',
                VideoQuality.default: '7',
                VideoQuality.highest: '9'
            }[quality]
        elif self is MediaFormats.default:
            return '0'


class VideoQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


def get_upload_to(instance, filename):
    # Dumb proxy to instance method.
    return instance.get_upload_to(filename)


@python_2_unicode_compatible
class AbstractVideo(CollectionMember, index.Indexed, models.Model):
    title = models.CharField(max_length=255, verbose_name=_('title'))
    file = models.FileField(
        verbose_name=_('file'), upload_to=get_upload_to)
    thumbnail = models.ImageField(upload_to=get_upload_to, null=True, blank=True, verbose_name=_('thumbnail'))
    created_at = models.DateTimeField(verbose_name=_('created at'), auto_now_add=True, db_index=True)
    duration = models.DurationField(blank=True, null=True)
    uploaded_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_('uploaded by user'),
        null=True, blank=True, editable=False, on_delete=models.SET_NULL
    )

    tags = TaggableManager(help_text=None, blank=True, verbose_name=_('tags'))

    file_size = models.PositiveIntegerField(null=True, editable=False)

    objects = VideoQuerySet.as_manager()

    search_fields = list(CollectionMember.search_fields) + [
        index.SearchField('title', partial_match=True, boost=10),
        index.RelatedFields('tags', [
            index.SearchField('name', partial_match=True, boost=10),
        ]),
        index.FilterField('uploaded_by_user'),
    ]

    def __init__(self, *args, **kwargs):
        super(AbstractVideo, self).__init__(*args, **kwargs)
        self._initial_file = self.file

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
        max_length = self._meta.get_field('file').max_length

        # Truncate filename so it fits in the 100 character limit
        # https://code.djangoproject.com/ticket/9893
        file_path = os.path.join(folder_name, filename)
        too_long = len(file_path) - max_length
        if too_long > 0:
            head, ext = os.path.splitext(filename)
            if too_long > len(head) + 1:
                raise SuspiciousFileOperation('File name can not be shortened to a safe length')
            filename = head[:-too_long] + ext
            file_path = os.path.join(folder_name, filename)
        return os.path.join(folder_name, filename)

    def get_usage(self):
        return get_object_usage(self)

    @property
    def usage_url(self):
        return reverse('wagtailvideos:video_usage', args=(self.id,))

    @property
    def formatted_duration(self):
        if(self.duration):
            hours, remainder = divmod(self.duration.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return "%d:%02d:%02d" % (hours, minutes, seconds)
        return ''

    def __str__(self):
        return self.title

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
        return cls.transcodes.rel.related_model

    def get_transcode(self, media_format):
        Transcode = self.get_transcode_model()
        try:
            return self.transcodes.get(media_format=media_format)
        except Transcode.DoesNotExist:
            return self.do_transcode(media_format)

    def video_tag(self, attrs=None):
        if attrs is None:
            attrs = {}
        else:
            attrs = attrs.copy()
        if self.thumbnail:
            attrs['poster'] = self.thumbnail.url

        transcodes = self.transcodes.exclude(processing=True).filter(error_message__exact='')
        sources = []
        for transcode in transcodes:
            sources.append("<source src='{0}' type='video/{1}' >".format(transcode.url, transcode.media_format.name))

        mime = mimetypes.MimeTypes()
        sources.append("<source src='{0}' type='{1}'>"
                       .format(self.url, mime.guess_type(self.url)[0]))

        sources.append("<p>Sorry, your browser doesn't support playback for this video</p>")
        return mark_safe(
            "<video {0}>\n{1}\n</video>".format(flatatt(attrs), "\n".join(sources)))

    def do_transcode(self, media_format, quality):
        transcode, created = self.transcodes.get_or_create(
            media_format=media_format,
        )
        if transcode.processing is False:
            transcode.processing = True
            transcode.error_message = ''
            transcode.quality = quality
            # Lock the transcode model
            transcode.save(update_fields=['processing', 'error_message',
                                          'quality'])
            TranscodingTask(transcode).start()
        else:
            pass  # TODO Queue?

    class Meta:
        abstract = True
        ordering = ['-created_at']


class Video(AbstractVideo):
    admin_form_fields = (
        'title',
        'file',
        'collection',
        'thumbnail',
        'tags',
    )


class TranscodingTask:
    def __init__(self, transcode):
        self.transcode = transcode

    def start(self):
        transcoding_task.delay(self.transcode.pk)


class TranscodingThread(threading.Thread):
    def __init__(self, transcode, **kwargs):
        super(TranscodingThread, self).__init__(**kwargs)
        self.transcode = transcode

    def run(self):
        self.transcode.run_transcoding()

# Delete files when model is deleted
@receiver(pre_delete, sender=Video)
def video_delete(sender, instance, **kwargs):
    instance.thumbnail.delete(False)
    instance.file.delete(False)


# Fields that need the actual video file to create
@receiver(post_save, sender=Video)
def video_saved(sender, instance, **kwargs):
    print("video saved...")
    if hasattr(instance, '_initial_file'):
        if instance.file != instance._initial_file:
            chain(
                get_video_metadata.si(object_pk=instance.pk),
                schedule_default_transcode.si(object_pk=instance.pk),
            )()


class AbstractVideoTranscode(models.Model):
    media_format = EnumChoiceField(MediaFormats, default=MediaFormats.default)
    quality = EnumChoiceField(VideoQuality, default=VideoQuality.default)
    processing = models.BooleanField(default=False)
    file = models.FileField(null=True, blank=True, verbose_name=_('file'),
                            upload_to=get_upload_to)
    error_message = models.TextField(blank=True)

    @property
    def url(self):
        return self.file.url

    def get_upload_to(self, filename):
        folder_name = 'video_transcodes'
        filename = self.file.field.storage.get_valid_name(filename)
        return os.path.join(folder_name, filename)

    def run_transcoding(self):
        transcode = self
        video = transcode.video
        media_format = transcode.media_format
        input_file = video.file.path
        output_dir = tempfile.mkdtemp()
        ext = media_format.name if media_format is not MediaFormats.default \
            else settings.WAGTAILVIDEOS_DEFAULT_COMPRESSION_EXT
        transcode_name = "{0}.{1}".format(
            video.filename(include_ext=False),
            ext)

        output_file = os.path.join(output_dir, transcode_name)
        FNULL = open(os.devnull, 'r')
        quality_param = media_format.get_quality_param(transcode.quality)
        args = ['ffmpeg', '-hide_banner', '-i', input_file]
        try:
            if media_format is MediaFormats.ogg:
                subprocess.check_output(args + [
                    '-codec:v', 'libtheora',
                    '-qscale:v', quality_param,
                    '-codec:a', 'libvorbis',
                    '-qscale:a', '5',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            elif media_format is MediaFormats.mp4:
                subprocess.check_output(args + [
                    '-codec:v', 'libx264',
                    '-preset', 'slow',  # TODO Checkout other presets
                    '-crf', quality_param,
                    '-codec:a', 'copy',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            elif media_format is MediaFormats.webm:
                subprocess.check_output(args + [
                    '-codec:v', 'libvpx',
                    '-crf', quality_param,
                    '-codec:a', 'libvorbis',
                    output_file,
                ], stdin=FNULL, stderr=subprocess.STDOUT)
            elif media_format is MediaFormats.default:
                subprocess.check_output(
                    args + settings.WAGTAILVIDEOS_DEFAULT_COMPRESSION_ARGS.split() + [output_file],
                    stdin=FNULL, stderr=subprocess.STDOUT)

            transcode_fname = self.get_upload_to(transcode_name)
            transcode_path = os.path.join(
                settings.MEDIA_ROOT,
                transcode_fname
            )
            shutil.move(output_file, transcode_path)
            transcode.file.name = transcode_fname
            transcode.error_message = ''
        except subprocess.CalledProcessError as error:
            transcode.error_message = error.output

        finally:
            transcode.processing = False
            transcode.save()
            shutil.rmtree(output_dir, ignore_errors=True)

    class Meta:
        abstract = True


class VideoTranscode(AbstractVideoTranscode):
    video = models.ForeignKey(Video, related_name='transcodes', on_delete=models.CASCADE)

    class Meta:
        unique_together = (
            ('video', 'media_format')
        )


# Delete files when model is deleted
@receiver(pre_delete, sender=VideoTranscode)
def transcode_delete(sender, instance, **kwargs):
    instance.file.delete(False)
