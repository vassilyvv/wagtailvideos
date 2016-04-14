import json

from django.core.urlresolvers import reverse
from django.shortcuts import get_object_or_404, render
from wagtail.utils.pagination import paginate
from wagtail.wagtailadmin.forms import SearchForm
from wagtail.wagtailadmin.modal_workflow import render_modal_workflow
from wagtail.wagtailcore.models import Collection
from wagtail.wagtailsearch.backends import get_search_backends
from wagtailvideos.formats import get_video_format
from wagtailvideos.forms import VideoInsertionForm, get_video_form
from wagtailvideos.models import get_video_model


def get_video_json(video):
    """
    helper function: given an image, return the json to pass back to the
    image chooser panel
    """

    return json.dumps({
        'id': video.id,
        'edit_link': reverse('wagtailvideos:edit', args=(video.id,)),
        'title': video.title,
        'preview': {
            'url': video.thumbnail.url,
        }
    })


def chooser(request):
    Video = get_video_model()

    VideoForm = get_video_form(Video)
    uploadform = VideoForm()

    videos = Video.objects.order_by('-created_at')

    q = None
    if (
        'q' in request.GET or 'p' in request.GET or 'tag' in request.GET or
        'collection_id' in request.GET
    ):
        # this request is triggered from search, pagination or 'popular tags';
        # we will just render the results.html fragment
        collection_id = request.GET.get('collection_id')
        if collection_id:
            videos = videos.filter(collection=collection_id)

        searchform = SearchForm(request.GET)
        if searchform.is_valid():
            q = searchform.cleaned_data['q']

            videos = videos.search(q)
            is_searching = True
        else:
            is_searching = False

            tag_name = request.GET.get('tag')
            if tag_name:
                videos = videos.filter(tags__name=tag_name)

        # Pagination
        paginator, videos = paginate(request, videos, per_page=12)

        return render(request, "wagtailvideos/chooser/results.html", {
            'videos': videos,
            'is_searching': is_searching,
            'query_string': q,
            'will_select_format': request.GET.get('select_format')
        })
    else:
        searchform = SearchForm()

        collections = Collection.objects.all()
        if len(collections) < 2:
            collections = None

        paginator, videos = paginate(request, videos, per_page=12)

    return render_modal_workflow(request, 'wagtailvideos/chooser/chooser.html', 'wagtailvideos/chooser/chooser.js', {
        'videos': videos,
        'uploadform': uploadform,
        'searchform': searchform,
        'is_searching': False,
        'query_string': q,
        'will_select_format': request.GET.get('select_format'),
        'popular_tags': Video.popular_tags(),
        'collections': collections,
    })


def video_chosen(request, video_id):
    video = get_object_or_404(get_video_model(), id=video_id)

    return render_modal_workflow(
        request, None, 'wagtailvideos/chooser/video_chosen.js',
        {'video_json': get_video_json(video)}
    )


def chooser_upload(request):
    Video = get_video_model()
    VideoForm = get_video_form(Video)

    searchform = SearchForm()

    if request.POST:
        video = Video(uploaded_by_user=request.user)
        form = VideoForm(request.POST, request.FILES, instance=video)

        if form.is_valid():
            form.save()

            # Reindex the video to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            if request.GET.get('select_format'):
                form = VideoInsertionForm(initial={'alt_text': video.default_alt_text})
                return render_modal_workflow(
                    request, 'wagtailvideos/chooser/select_format.html', 'wagtailvideos/chooser/select_format.js',
                    {'video': video, 'form': form}
                )
            else:
                # not specifying a format; return the video details now
                return render_modal_workflow(
                    request, None, 'wagtailvideos/chooser/videos_chosen.js',
                    {'video_json': get_video_json(video)}
                )
    else:
        form = VideoForm()

    videos = Video.objects.order_by('title')

    return render_modal_workflow(
        request, 'wagtailvideos/chooser/chooser.html', 'wagtailvideos/chooser/chooser.js',
        {'videos': videos, 'uploadform': form, 'searchform': searchform}
    )


def chooser_select_format(request, video_id):
    video = get_object_or_404(get_video_model(), id=video_id)

    if request.POST:
        form = VideoInsertionForm(request.POST, initial={'alt_text': video.default_alt_text})
        if form.is_valid():

            format = get_video_format(form.cleaned_data['format'])
            preview_video = video.get_rendition(format.filter_spec)

            video_json = json.dumps({
                'id': image.id,
                'title': image.title,
                'format': format.name,
                'alt': form.cleaned_data['alt_text'],
                'class': format.classnames,
                'edit_link': reverse('wagtailvideos:edit', args=(video.id,)),
                'preview': {
                    'url': preview_image.url,
                    'width': preview_image.width,
                    'height': preview_image.height,
                },
                'html': format.image_to_editor_html(image, form.cleaned_data['alt_text']),
            })

            return render_modal_workflow(
                request, None, 'wagtailimages/chooser/image_chosen.js',
                {'image_json': image_json}
            )
    else:
        form = ImageInsertionForm(initial={'alt_text': image.default_alt_text})

    return render_modal_workflow(
        request, 'wagtailimages/chooser/select_format.html', 'wagtailimages/chooser/select_format.js',
        {'image': image, 'form': form}
    )
