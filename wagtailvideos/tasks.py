from contextlib import contextmanager
import os
from django.core.files.temp import NamedTemporaryFile
from django.core.exceptions import ImproperlyConfigured

from celery import shared_task
from django.apps import apps
from wagtailvideos import ffmpeg
import logging
log = logging.getLogger(__name__)


@shared_task
def get_video_metadata(object_pk, *args):
    Video = apps.get_model(app_label="wagtailvideos", model_name="Video")
    instance = Video.objects.get(pk=object_pk)
    log.debug('getting video metadata for %s', instance)

    if not ffmpeg.installed():
        raise ImproperlyConfigured("ffmpeg could not be found on your system. Transcoding will be disabled")

    with get_local_file(instance.file) as file_path:
        instance.thumbnail = ffmpeg.get_thumbnail(file_path)
        instance.duration = ffmpeg.get_duration(file_path)

    instance.file_size = instance.file.size
    instance.save()


@shared_task
def schedule_default_transcode(object_pk, *args):
    Video = apps.get_model(app_label="wagtailvideos", model_name="Video")
    instance = Video.objects.get(pk=object_pk)
    log.debug('transcoding video for %s', instance)
    if not ffmpeg.installed():
        raise ImproperlyConfigured("ffmpeg could not be found on your system. Transcoding will be disabled")

    transcode, created = instance.transcodes.get_or_create()
    if transcode.processing is False:
        transcode.processing = True
        transcode.error_message = ''
        # Lock the transcode model
        transcode.save(update_fields=['processing', 'error_message'])
        transcode.run_transcoding()


@shared_task
def transcoding_task(transcode_pk, *args):
    Transcode = apps.get_model(app_label="wagtailvideos", model_name="VideoTranscode")

    transcode = Transcode.objects.get(pk=transcode_pk)
    transcode.run_transcoding()


@shared_task
def get_video_codec_task(file_path):
    result = ffmpeg.get_video_codec(file_path)
    return result


@contextmanager
def get_local_file(file):
    """
    Get a local version of the file, downloading it from the remote storage if
    required. The returned value should be used as a context manager to
    ensure any temporary files are cleaned up afterwards.
    """
    try:
        with open(file.path):
            yield file.path
    except NotImplementedError:
        _, ext = os.path.splitext(file.name)
        with NamedTemporaryFile(prefix='wagtailvideo-', suffix=ext) as tmp:
            try:
                file.open('rb')
                for chunk in file.chunks():
                    tmp.write(chunk)
            finally:
                file.close()
            tmp.flush()
            yield tmp.name
