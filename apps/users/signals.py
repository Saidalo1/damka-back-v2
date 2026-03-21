import os

from django.core.files.storage import default_storage
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.users.models import User


@receiver(post_delete, sender=User)
def delete_user_images(sender, instance, **kwargs):
    if instance.avatar and os.path.exists(instance.avatar.path):
        default_storage.delete(instance.avatar.path)

    deleted_dir = None

    for field_name in ['avatar_small', 'avatar_middle', 'avatar_large']:
        field = getattr(instance, field_name, None)

        if field and hasattr(field, 'path') and field.name:
            file_path = field.path
            dir_path = os.path.dirname(file_path)

            if os.path.exists(file_path):
                try:
                    field.storage.delete(field.name)
                    deleted_dir = dir_path
                except Exception as e:
                    print(f"Error deleting file {field.name}: {e}")

    if deleted_dir and os.path.isdir(deleted_dir):
        try:
            if not os.listdir(deleted_dir):
                os.rmdir(deleted_dir)
        except Exception as e:
            print(f"Error removing directory {deleted_dir}: {e}")
