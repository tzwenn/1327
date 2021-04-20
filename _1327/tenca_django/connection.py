import urllib.error

from django.core.exceptions import ImproperlyConfigured

from mailmanclient.restbase.connection import MailmanConnectionError

import tenca.connection


class FakeConnection:

	def __init__(self, exception):
		self.exception = exception

	def __getattr__(self, name):
		raise self.exception


try:
	connection = tenca.connection.Connection()
except (MailmanConnectionError, AttributeError) as e:
	connection = FakeConnection(ImproperlyConfigured(*e.args))
except urllib.error.HTTPError as e:
	connection = FakeConnection(ImproperlyConfigured(str(e)))


def flush_all_hashes():
	"""Queues reload of all invite link templates and flushes changed hashes to all storage layers

	Takes some time.
	"""
	for raw_list in connection.client.lists:
		wrapped_list = connection.get_list(raw_list.fqdn_listname)
		connection.flush_hash(wrapped_list.hash_id)