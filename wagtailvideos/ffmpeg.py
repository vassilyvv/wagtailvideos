import datetime
import logging
import os
import re
import shutil
import subprocess
import tempfile
import json

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

try:
    from shutil import which
except ImportError:
    from distutils.spawn import find_executable as which


def DEVNULL():
    return open(os.devnull, 'r+b')


def installed(path=None):
    return which('ffmpeg', path=path) is not None


def get_duration(file_path):
    if not installed():
        raise RuntimeError('ffmpeg is not installed')

    try:
        show_format = subprocess.check_output(
            ['ffprobe', file_path, '-show_format', '-v', 'quiet'],
            stdin=DEVNULL(), stderr=DEVNULL())
        show_format = show_format.decode("utf-8")
        # show_format comes out in key=value pairs seperated by newlines
        duration = re.findall(r'([duration^=]+)=([^=]+)(?:\n|$)', show_format)[0][1]
        return datetime.timedelta(seconds=float(duration))
    except subprocess.CalledProcessError:
        logger.exception("Getting video duration failed")
        return None


def get_thumbnail(file_path):
    if not installed():
        raise RuntimeError('ffmpeg is not installed')

    file_name = os.path.basename(file_path)
    thumb_name = '{}_thumb{}'.format(os.path.splitext(file_name)[0], '.jpg')

    try:
        output_dir = tempfile.mkdtemp()
        output_file = os.path.join(output_dir, thumb_name)
        try:
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
            ], stdin=DEVNULL(), stdout=DEVNULL())
        except subprocess.CalledProcessError:
            return None
        return ContentFile(open(output_file, 'rb').read(), thumb_name)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def get_video_codec(file_path):
    if not installed():
        raise RuntimeError('ffmpeg is not installed')
    if not os.path.exists(file_path):
        logger.exception("Video file not found")
        return None

    try:
        fprobe_result = subprocess.check_output(
            ['ffprobe', file_path, '-show_entries', 'stream=codec_name,codec_type', '-of', 'json', '-v', 'quiet'],
            stdin=DEVNULL(), stderr=DEVNULL())
        return parse_fprobe_result(fprobe_result)
    except subprocess.CalledProcessError:
        logger.exception("Getting video duration failed")
        return None


def get_video_codec_from_bytes(bytes_data):
    if not installed():
        raise RuntimeError('ffmpeg is not installed')
    try:
        fprobe_result = subprocess.check_output(
            ['ffprobe', '-show_entries', 'stream=codec_name,codec_type', '-of', 'json', '-v', 'quiet', '-'],
            stderr=DEVNULL(), input=bytes_data)
        return parse_fprobe_result(fprobe_result)
    except subprocess.CalledProcessError:
        logger.exception("Getting video duration failed")
        return None


def parse_fprobe_result(fprobe_result):
    try:
        fprobe_result = json.loads(fprobe_result)
        video_stream = get_videostream_data(fprobe_result)
        if video_stream is None:
            return None
        else:
            return video_stream["codec_name"]
    except json.JSONDecodeError:
        logger.exception("Parsing fprobe result failed")
        return None


def get_videostream_data(fprobe_res_dict):
    streams = fprobe_res_dict.get('streams', None)
    if streams is not None:
        streams = list(filter(lambda s: s['codec_type'] == 'video', streams))
        if len(streams) > 0:
            return streams[0]
    return None
