import unittest

from django.test import TestCase

from tests.utils import create_test_video
from wagtailvideos.models import Video


class TestVideoTag(TestCase):
    def setUp(self):
        self.video = Video.objects.create(
            title="Test Video",
            file=create_test_video()
        )

    def test_whatever(self):
        print(self.video.file.path)
        pass
