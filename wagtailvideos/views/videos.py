import os

from django.core.urlresolvers import NoReverseMatch, reverse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext as _
from django.views.decorators.vary import vary_on_headers
from wagtail.utils.pagination import paginate
from wagtail.wagtailadmin import messages
from wagtail.wagtailadmin.forms import SearchForm
from wagtail.wagtailcore.models import Collection, Site
from wagtail.wagtailsearch.backends import get_search_backends

from wagtailvideos.forms import URLGeneratorForm, get_video_form
from wagtailvideos.models import get_video_model


@vary_on_headers('X-Requested-With')
def index(request):
    Video = get_video_model()

    # Get images (filtered by user permission)
    videos = Video.objects.all()

    # Search
    query_string = None
    if 'q' in request.GET:
        form = SearchForm(request.GET, placeholder=_("Search videos"))
        if form.is_valid():
            query_string = form.cleaned_data['q']

            videos = videos.search(query_string)
    else:
        form = SearchForm(placeholder=_("Search videos"))

    # Filter by collection
    current_collection = None
    collection_id = request.GET.get('collection_id')
    if collection_id:
        try:
            current_collection = Collection.objects.get(id=collection_id)
            videos = videos.filter(collection=current_collection)
        except (ValueError, Collection.DoesNotExist):
            pass

    paginator, videos = paginate(request, videos)

    # Create response
    if request.is_ajax():
        response = render(request, 'wagtailvideos/videos/results.html', {
            'vidoes': videos,
            'query_string': query_string,
            'is_searching': bool(query_string),
        })
        return response
    else:
        response = render(request, 'wagtailvideos/videos/index.html', {
            'videos': videos,
            'query_string': query_string,
            'is_searching': bool(query_string),

            'search_form': form,
            'popular_tags': Video.popular_tags(),
            'current_collection': current_collection,
        })
        return response


def edit(request, video_id):
    Video = get_video_model()
    VideoForm = get_video_form(Video)

    video = get_object_or_404(Video, id=video_id)

    if request.POST:
        original_file = video.file
        form = VideoForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            if 'file' in form.changed_data:
                # if providing a new image file, delete the old one and all renditions.
                # NB Doing this via original_file.delete() clears the file field,
                # which definitely isn't what we want...
                original_file.storage.delete(original_file.name)

                # Set new image file size
                video.file_size = video.file.size

            video = form.save()
            video.thumbnail = video.get_thumbnail()
            video.save()

            # Reindex the image to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            messages.success(request, _("Video '{0}' updated.").format(video.title), buttons=[
                messages.button(reverse('wagtailvideos:edit', args=(video.id,)), _('Edit again'))
            ])
            return redirect('wagtailvideos:index')
        else:
            messages.error(request, _("The video could not be saved due to errors."))
    else:
        form = VideoForm(instance=video)

    # Check if we should enable the frontend url generator
    try:
        reverse('wagtailvideos_serve', args=('foo', '1', 'bar'))
        url_generator_enabled = True
    except NoReverseMatch:
        url_generator_enabled = False

    if video.is_stored_locally():
        # Give error if image file doesn't exist
        if not os.path.isfile(video.file.path):
            messages.error(request, _(
                "The source video file could not be found. Please change the source or delete the video."
            ).format(video.title), buttons=[
                messages.button(reverse('wagtailvideos:delete', args=(video.id,)), _('Delete'))
            ])

    return render(request, "wagtailvideos/videos/edit.html", {
        'video': video,
        'form': form,
        'url_generator_enabled': url_generator_enabled,
        'filesize': video.get_file_size(),
        'transcodes': video.transcodes.all(),
    })


def url_generator(request, image_id):
    image = get_object_or_404(get_video_model(), id=image_id)

    form = URLGeneratorForm(initial={
        'filter_method': 'original',
        'width': image.width,
        'height': image.height,
    })

    return render(request, "wagtailvideos/images/url_generator.html", {
        'image': image,
        'form': form,
    })


def generate_url(request, image_id, filter_spec):
    # Get the image
    Image = get_video_model()
    try:
        Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        return JsonResponse({
            'error': "Cannot find image."
        }, status=404)

    # Check if this user has edit permission on this image

    # Generate url
    url = reverse('wagtailvideos_serve', args=(image_id, filter_spec))

    # Get site root url
    try:
        site_root_url = Site.objects.get(is_default_site=True).root_url
    except Site.DoesNotExist:
        site_root_url = Site.objects.first().root_url

    # Generate preview url
    preview_url = reverse('wagtailvideos:preview', args=(image_id, filter_spec))

    return JsonResponse({'url': site_root_url + url, 'preview_url': preview_url}, status=200)


def delete(request, image_id):
    image = get_object_or_404(get_video_model(), id=image_id)

    if request.POST:
        image.delete()
        messages.success(request, _("Image '{0}' deleted.").format(image.title))
        return redirect('wagtailvideos:index')

    return render(request, "wagtailvideos/images/confirm_delete.html", {
        'image': image,
    })


def add(request):
    ImageModel = get_video_model()
    ImageForm = get_video_form(ImageModel)

    if request.POST:
        image = ImageModel(uploaded_by_user=request.user)
        form = ImageForm(request.POST, request.FILES, instance=image, user=request.user)
        if form.is_valid():
            # Set image file size
            image.file_size = image.file.size

            form.save()

            # Reindex the image to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(image)

            messages.success(request, _("Image '{0}' added.").format(image.title), buttons=[
                messages.button(reverse('wagtailvideos:edit', args=(image.id,)), _('Edit'))
            ])
            return redirect('wagtailvideos:index')
        else:
            messages.error(request, _("The image could not be created due to errors."))
    else:
        form = ImageForm(user=request.user)

    return render(request, "wagtailvideos/images/add.html", {
        'form': form,
    })


def usage(request, image_id):
    image = get_object_or_404(get_video_model(), id=image_id)

    paginator, used_by = paginate(request, image.get_usage())

    return render(request, "wagtailvideos/images/usage.html", {
        'image': image,
        'used_by': used_by
    })
