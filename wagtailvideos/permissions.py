from __future__ import absolute_import, print_function, unicode_literals

from wagtail.wagtailcore.permission_policies.collections import \
    CollectionOwnershipPermissionPolicy

from wagtailvideos.models import Video

permission_policy = CollectionOwnershipPermissionPolicy(
    Video,
    auth_model=Video,
    owner_field_name='uploaded_by_user'
)
