try:
    from shutil import which
except ImportError:
    from distutils.spawn import find_executable as which


def installed(path=None):
    return which('ffmpeg', path=path) is not None
