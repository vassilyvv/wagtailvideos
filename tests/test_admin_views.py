from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.urlresolvers import reverse
from django.test import TestCase
from wagtail.tests.utils import WagtailTestUtils
from wagtail.wagtailcore.models import Collection

from tests.utils import create_test_video_file
from wagtailvideos.models import Video


class TestVideoIndexView(TestCase, WagtailTestUtils):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse('wagtailvideos:index'), params)

    def test_simple(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailvideos/videos/index.html')
        self.assertContains(response, "Add a video")

    def test_search(self):
        response = self.get({'q': "Hello"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['query_string'], "Hello")

    def test_pagination(self):
        pages = ['0', '1', '-1', '9999', 'Not a page']
        for page in pages:
            response = self.get({'p': page})
            self.assertEqual(response.status_code, 200)

    def test_ordering(self):
        orderings = ['title', '-created_at']
        for ordering in orderings:
            response = self.get({'ordering': ordering})
            self.assertEqual(response.status_code, 200)


class TestVidoAddView(TestCase, WagtailTestUtils):
    def setUp(self):
        self.login()

    def get(self, params={}):
        return self.client.get(reverse('wagtailvideos:add'), params)

    def post(self, post_data={}):
        return self.client.post(reverse('wagtailvideos:add'), post_data)

    def test_get(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailvideos/videos/add.html')

        # as standard, only the root collection exists and so no 'Collection' option
        # is displayed on the form
        self.assertNotContains(response, '<label for="id_collection">')

        # Ensure the form supports file uploads
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_get_with_collections(self):
        root_collection = Collection.get_first_root_node()
        collection_name = "Takeflight manifesto"
        root_collection.add_child(name=collection_name)

        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailvideos/videos/add.html')

        self.assertContains(response, '<label for="id_collection">')
        self.assertContains(response, collection_name)

    def test_add(self):
        video_file = create_test_video_file()
        title = "Test Video"
        response = self.post({
            'title': title,
            'file': SimpleUploadedFile('small.mp4', video_file.read(), "video/mp4"),
        })

        # Should redirect back to index
        self.assertRedirects(response, reverse('wagtailvideos:index'))

        # Check that the image was created
        videos = Video.objects.filter(title=title)
        self.assertEqual(videos.count(), 1)

        # Test that extra fields were populated from post_save signal
        video = videos.first()
        self.assertTrue(video.thumbnail)
        self.assertTrue(video.duration)
        self.assertTrue(video.file_size)

        # Test that it was placed in the root collection
        root_collection = Collection.get_first_root_node()
        self.assertEqual(video.collection, root_collection)

    def test_add_no_file_selected(self):
        response = self.post({
            'title': "nothing here",
        })

        # Shouldn't redirect anywhere
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wagtailvideos/videos/add.html')

        # The form should have an error
        self.assertFormError(response, 'form', 'file', "This field is required.")
