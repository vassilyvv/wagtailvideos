from wagtail.wagtailcore.permission_policies.collections import \
    CollectionOwnershipPermissionPolicy
from wagtailvideos.models import Video, get_video_model

permission_policy = CollectionOwnershipPermissionPolicy(
    get_video_model(),
    auth_model=Video,
    owner_field_name='uploaded_by_user'
)
