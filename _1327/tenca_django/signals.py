from django.db.models.signals import post_save
from django.dispatch import receiver

from _1327.tenca_django.models import HashEntry
from _1327.tenca_django.connection import connection

@receiver(post_save, sender=HashEntry)
def post_save_hash_entry(sender, instance, **kwargs):
	connection.flush_hash(instance.hash_id)