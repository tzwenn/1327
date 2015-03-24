from _1327.documents.models import Document
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.translation import ugettext_lazy as _


class MenuItem(models.Model):
	title = models.CharField(max_length=255, unique=False, verbose_name=_("Title"))
	order = models.IntegerField()

	link = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Link"))
	document = models.ForeignKey(Document, blank=True, null=True, verbose_name=_("Document"))

	parent = models.ForeignKey('self', blank=True, null=True, related_name='children')

	def __str__(self):
		return self.title

	def get_url(self):
		if self.link:
			return reverse(self.link)
		elif self.document:
			return self.document.get_url()