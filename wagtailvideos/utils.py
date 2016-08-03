from __future__ import absolute_import, print_function, unicode_literals

try:
    from shutil import which
except ImportError:
    from distutils.spawn import find_executable as which


def ffmpeg_installed(path=None):
    return which('ffmpeg', path=path) is not None
