try:
    from shutil import which
except ImportError:
    from distutils.spawn import find_executable as which
