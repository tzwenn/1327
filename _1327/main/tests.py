import datetime
from io import StringIO
import json
import re

from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail, management
from django.core.management import call_command
from django.test import override_settings, RequestFactory, TestCase
from django.urls import reverse
from django.utils import translation
from django_webtest import WebTest
from guardian.shortcuts import assign_perm, remove_perm
from guardian.utils import get_anonymous_user
from model_bakery import baker

from _1327.information_pages.models import InformationDocument
from _1327.main.tools import translate
from _1327.main.utils import alternative_emails, find_root_menu_items
from _1327.minutes.models import MinutesDocument
from _1327.user_management.models import UserProfile
from .context_processors import mark_selected
from .models import MenuItem


class TestMenuProcessor(TestCase):

	def test_mark_selected(self):
		rf = RequestFactory()
		request = rf.get('/this_is_a_page_that_most_certainly_does_not_exist.html')

		menu_item = baker.make(MenuItem)
		try:
			mark_selected(request, menu_item)
		except AttributeError:
			self.fail("mark_selected() raises an AttributeError")


class MainPageTests(WebTest):

	def test_main_page_no_page_set(self):
		response = self.app.get(reverse('index'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'index.html')

	def test_main_page_information_page_set(self):
		document = baker.make(InformationDocument)
		assign_perm(InformationDocument.VIEW_PERMISSION_NAME, get_anonymous_user(), document)
		with self.settings(MAIN_PAGE_ID=document.id):
			response = self.app.get(reverse('index')).follow()
			self.assertEqual(response.status_code, 200)
			self.assertTemplateUsed(response, 'documents_base.html')

			response = self.app.get(reverse('index') + '/').follow()
			self.assertEqual(response.status_code, 200)
			self.assertTemplateUsed(response, 'documents_base.html')

	def test_main_page_minutes_document_set(self):
		document = baker.make(MinutesDocument)
		assign_perm(MinutesDocument.VIEW_PERMISSION_NAME, get_anonymous_user(), document)
		with self.settings(MAIN_PAGE_ID=document.id):
			response = self.app.get(reverse('index')).follow()
			self.assertEqual(response.status_code, 200)
			self.assertTemplateUsed(response, 'documents_base.html')


class MenuItemTests(WebTest):

	csrf_checks = False

	@classmethod
	def setUpTestData(cls):
		cls.root_user = baker.make(UserProfile, is_superuser=True)
		cls.user = baker.make(UserProfile)

		cls.staff_group = Group.objects.get(name=settings.STAFF_GROUP_NAME)
		cls.root_user.groups.add(cls.staff_group)
		cls.user.groups.add(cls.staff_group)

		cls.root_menu_item = baker.make(MenuItem, title_en="root_menu_item")
		cls.sub_item = baker.make(MenuItem, parent=cls.root_menu_item, title_en="sub_item", order=3)
		cls.sub_sub_item = baker.make(MenuItem, parent=cls.sub_item, title_en="sub_sub_item", order=4)

		assign_perm(cls.sub_item.change_children_permission_name, cls.user, cls.sub_item)
		assign_perm(cls.sub_item.view_permission_name, cls.user, cls.sub_item)

	def setUp(self):
		self.root_menu_item.refresh_from_db()
		self.sub_item.refresh_from_db()
		self.sub_sub_item.refresh_from_db()

	def test_visit_menu_item_page(self):
		user = baker.make(UserProfile)

		response = self.app.get(reverse('menu_items_index'), user=user, status=403)
		self.assertEqual(response.status_code, 403)

		assign_perm(self.root_menu_item.change_children_permission_name, user, self.root_menu_item)
		response = self.app.get(reverse('menu_items_index'), user=user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(self.root_menu_item.title, response.body.decode('utf-8'))

	def test_create_menu_item_as_superuser_document_and_link(self):
		menu_item_count = MenuItem.objects.count()
		document = baker.make(InformationDocument)

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['link'] = 'polls:index'
		form['document'].select(value=document.id)
		form['group'].select(text=self.staff_group.name)

		response = form.submit()
		self.assertEqual(200, response.status_code)
		self.assertIn('You are only allowed to define one of document and link', response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count)

	def test_create_menu_item_as_superuser_with_link(self):
		menu_item_count = MenuItem.objects.count()

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['link'] = 'polls:index'
		form['group'].select(text=self.staff_group.name)

		response = form.submit().follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Successfully created menu item.", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count + 1)

	def test_create_menu_item_as_superuser_with_link_and_param(self):
		menu_item_count = MenuItem.objects.count()

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['link'] = 'minutes:list?groupid={}'.format(self.staff_group.id)
		form['group'].select(text=self.staff_group.name)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Successfully created menu item.", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count + 1)

	def test_create_menu_item_as_superuser_wrong_link(self):
		menu_item_count = MenuItem.objects.count()

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['link'] = 'polls:index?kekse?kekse2'
		form['group'].select(text=self.staff_group.name)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn('This link is not valid.', response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count)

	def test_create_menu_item_as_superuser_wrong_link_2(self):
		menu_item_count = MenuItem.objects.count()

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['link'] = 'www.example.com'
		form['group'].select(text=self.staff_group.name)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn('This link is not valid.', response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count)

	def test_create_menu_item_as_superuser_with_document(self):
		menu_item_count = MenuItem.objects.count()
		document = baker.make(InformationDocument)

		response = self.app.get(reverse('menu_item_create'), user=self.root_user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['document'].select(value=document.id)
		form['group'].select(text=self.staff_group.name)

		response = form.submit().follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Successfully created menu item.", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count + 1)

	def test_create_menu_item_as_normal_user(self):
		response = self.app.get(reverse('menu_item_create'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn("Link", response.body.decode('utf-8'))

	def test_create_menu_item_as_normal_user_with_document(self):
		menu_item_count = MenuItem.objects.count()
		document = baker.make(InformationDocument)

		response = self.app.get(reverse('menu_item_create'), user=self.user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['document'].select(value=document.id)
		form['group'].select(text=self.staff_group.name)
		form['parent'].select(text=self.sub_item.title)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Successfully created menu item.", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count + 1)

	def test_create_menu_item_as_normal_user_with_document_without_parent(self):
		menu_item_count = MenuItem.objects.count()
		document = baker.make(InformationDocument)

		response = self.app.get(reverse('menu_item_create'), user=self.user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['document'].select(value=document.id)
		form['group'].select(text=self.staff_group.name)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("This field is required", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count)

	def test_create_menu_wrong_group(self):
		menu_item_count = MenuItem.objects.count()
		document = baker.make(InformationDocument)
		group = baker.make(Group)

		response = self.app.get(reverse('menu_item_create'), user=self.user)
		form = response.form
		form['title_en'] = 'test title'
		form['title_de'] = 'test titel'
		form['document'].select(value=document.id)
		form['group'].force_value(group.id)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Select a valid choice. That choice is not one of the available choices.", response.body.decode('utf-8'))
		self.assertEqual(MenuItem.objects.count(), menu_item_count)

	def test_change_menu_items(self):
		for user in [self.root_user, self.user]:
			response = self.app.get(reverse('menu_items_index'), user=user)
			self.assertEqual(response.status_code, 200)

			response_text = response.body.decode('utf-8')
			self.assertIn(self.root_menu_item.title, response_text)
			self.assertIn(self.sub_item.title, response_text)
			self.assertIn(self.sub_sub_item.title, response_text)

	def test_possibility_to_change_root_item(self):
		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn(reverse('menu_item_edit', args=[self.root_menu_item.id]), response.body.decode('utf-8'))

		response = self.app.get(reverse('menu_items_index'), user=self.root_user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('menu_item_edit', args=[self.root_menu_item.id]), response.body.decode('utf-8'))

	def test_find_root_menu_items(self):
		sub_item = baker.make(MenuItem, parent=self.root_menu_item)
		sub_sub_item = baker.make(MenuItem, parent=self.sub_item)

		menu_items = [sub_sub_item, self.sub_sub_item, sub_item]
		root_menu_items = find_root_menu_items(menu_items)

		self.assertEqual(root_menu_items, set([self.root_menu_item]))

	def test_set_edit_permission_on_menu_item(self):
		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn(reverse('menu_item_edit', args=[self.sub_item.id]), response.body.decode('utf-8'))
		self.assertIn(reverse('menu_item_edit', args=[self.sub_sub_item.id]), response.body.decode('utf-8'))

		assign_perm(self.sub_item.edit_permission_name, self.user, self.sub_item)

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('menu_item_edit', args=[self.sub_item.id]), response.body.decode('utf-8'))
		self.assertIn(reverse('menu_item_edit', args=[self.sub_sub_item.id]), response.body.decode('utf-8'))

	def test_change_parent_without_edit_permission(self):
		extra_sub_item = baker.make(MenuItem, parent=self.sub_item)

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('menu_item_edit', args=[extra_sub_item.id]), response.body.decode('utf-8'))

		extra_sub_item.parent = self.root_menu_item
		extra_sub_item.save()

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn(reverse('menu_item_edit', args=[extra_sub_item.id]), response.body.decode('utf-8'))

	def test_change_parent_with_edit_permission(self):
		extra_sub_item = baker.make(MenuItem, parent=self.sub_item, title_en='extra_sub_item')
		assign_perm(extra_sub_item.edit_permission_name, self.user, extra_sub_item)

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('menu_item_edit', args=[extra_sub_item.id]), response.body.decode('utf-8'))

		extra_sub_item.parent = self.root_menu_item
		extra_sub_item.save()

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('menu_item_edit', args=[extra_sub_item.id]), response.body.decode('utf-8'))

	def test_can_see_link_details(self):
		extra_sub_item = baker.make(MenuItem, parent=self.root_menu_item, title_en="name", link="link123")

		assign_perm(MenuItem.EDIT_PERMISSION_NAME, self.user, extra_sub_item)

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn("(<i>Link:</i> link123)", response.body.decode('utf-8'))

		remove_perm(MenuItem.EDIT_PERMISSION_NAME, self.user, extra_sub_item)

		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn("(<i>Link:</i> link123)", response.body.decode('utf-8'))

	def test_menu_item_ordering(self):
		self.root_menu_item.order = 2
		self.root_menu_item.save()

		baker.make(MenuItem, order=1)  # root item before self.root_menu_item
		root_item_5 = baker.make(MenuItem, order=5)  # root item after self.root_menu_item

		sub_item_5_1 = baker.make(MenuItem, parent=root_item_5, order=6)
		baker.make(MenuItem, parent=sub_item_5_1, order=8)  # out of creation order, should be second
		baker.make(MenuItem, parent=sub_item_5_1, order=7)
		baker.make(MenuItem, parent=root_item_5, order=11)  # out of creation order, should be third
		sub_item_5_2 = baker.make(MenuItem, parent=root_item_5, order=9)
		baker.make(MenuItem, parent=sub_item_5_2, order=10)

		menu_items = list(MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU).order_by('order'))
		for idx, item in enumerate(menu_items):
			assign_perm(item.change_children_permission_name, self.user, item)
			item.order = idx
			item.save()
		menu_items.append(MenuItem.objects.get(menu_type=MenuItem.FOOTER))

		response = self.app.get(reverse('menu_items_index'), user=self.root_user)
		response_text = response.body.decode('utf-8')

		menu_item_ids = re.findall(r"menu_item/(\d+)/edit", response_text)
		self.assertEqual(len(menu_item_ids), len(menu_items))

		for menu_item_id, menu_item in zip(menu_item_ids, menu_items):
			self.assertEqual(menu_item.id, int(menu_item_id), 'Menu Item ordering is not as expected')

	def test_menu_item_visible_for_user(self):
		document = baker.make(InformationDocument)
		self.sub_item.document = document
		self.sub_item.save()
		assign_perm(self.root_menu_item.view_permission_name, self.user, self.root_menu_item)

		response = self.app.get(reverse('index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('view', args=[document.url_title]), response.body.decode('utf-8'))

		document2 = baker.make(InformationDocument)
		self.sub_sub_item.document = document2
		self.sub_sub_item.save()
		assign_perm(self.sub_sub_item.view_permission_name, self.user, self.sub_sub_item)

		response = self.app.get(reverse('index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(reverse('view', args=[document2.url_title]), response.body.decode('utf-8'))

	def test_menu_item_not_visible_for_user(self):
		document = baker.make(InformationDocument)
		self.root_menu_item.document = document
		self.root_menu_item.save()

		response = self.app.get(reverse('index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertNotIn(reverse('view', args=[document.url_title]), response.body.decode('utf-8'))

	def test_menu_item_edit_no_permission(self):
		response = self.app.get(reverse('menu_item_edit', args=[self.root_menu_item.pk]), user=self.user, expect_errors=True)
		self.assertEqual(response.status_code, 403)

	def test_menu_item_edit(self):
		document_2 = baker.make(InformationDocument)
		self.sub_item.document = document_2
		self.sub_item.save()

		assign_perm(self.root_menu_item.change_children_permission_name, self.user, self.root_menu_item)

		response = self.app.get(reverse('menu_item_edit', args=[self.sub_item.pk]), user=self.user)
		self.assertEqual(response.status_code, 200)

		original_menu_item = self.sub_item

		form = response.form
		form['title_en'] = 'Lorem Ipsum'
		form['title_de'] = 'test titel'
		form['document'] = ''

		response = form.submit().maybe_follow()
		self.assertEqual(response.status_code, 200)

		changed_menu_item = MenuItem.objects.get(pk=self.sub_item.pk)
		self.assertNotEqual(original_menu_item.title, changed_menu_item.title)
		self.assertIsNone(changed_menu_item.document)

	def test_menu_item_edit_with_children(self):
		assign_perm(self.root_menu_item.edit_permission_name, self.user, self.root_menu_item)

		response = self.app.get(reverse('menu_item_edit', args=[self.root_menu_item.pk]), user=self.root_user)
		self.assertEqual(response.status_code, 200)

		form = response.form
		form['link'] = 'index'

		response = form.submit().maybe_follow()
		self.assertEqual(response.status_code, 200)

		changed_menu_item = MenuItem.objects.get(pk=self.root_menu_item.pk)
		# MenuItems are not allowed to have content and children, so it should not be edited
		self.assertIsNone(changed_menu_item.link)

	def test_update_order_as_superuser(self):
		all_main_menu_items = list(MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU, parent_id=None).exclude(id=self.root_menu_item.id))
		menu_items = [self.root_menu_item]
		menu_items.extend(all_main_menu_items)

		order_data = {
			'main_menu_items': [{'id': m.id} for m in menu_items],
			'footer_items': [{'id': m.id} for m in MenuItem.objects.filter(menu_type=MenuItem.FOOTER)],
		}

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.root_user)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(MenuItem.objects.get(id=self.root_menu_item.id).order, 0)

	def test_move_items_to_other_parent(self):
		order_data = {
			'main_menu_items': [{'id': m.id} for m in list(MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU, parent_id=None))],
			'footer_items': [{'id': m.id} for m in MenuItem.objects.filter(menu_type=MenuItem.FOOTER)],
		}

		parent_item = baker.make(MenuItem, parent=None)
		child_item = baker.make(MenuItem, parent=parent_item)
		new_parent_item = baker.make(MenuItem, parent=None)

		order_data['main_menu_items'].append({'id': parent_item.id})
		order_data['main_menu_items'].append({'id': new_parent_item.id, 'children': [{'id': child_item.id}]})

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.root_user)
		self.assertEqual(response.status_code, 200)

		updated_child_item = MenuItem.objects.filter(pk=child_item.id).first()
		self.assertEqual(new_parent_item.id, updated_child_item.parent.id)

	def test_move_to_parent_with_content(self):
		order_data = {
			'main_menu_items': [{'id': m.id} for m in list(MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU, parent_id=None))],
			'footer_items': [{'id': m.id} for m in MenuItem.objects.filter(menu_type=MenuItem.FOOTER)],
		}

		parent_item = baker.make(MenuItem, parent=None)
		child_item = baker.make(MenuItem, parent=parent_item)
		new_parent_item = baker.make(MenuItem, parent=None, link="index")

		order_data['main_menu_items'].append({'id': parent_item.id})
		order_data['main_menu_items'].append({'id': new_parent_item.id, 'children': [{'id': child_item.id}]})

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.root_user)
		self.assertEqual(response.status_code, 200)

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.root_user)
		self.assertEqual(response.status_code, 200)

		updated_child_item = MenuItem.objects.filter(pk=child_item.id).first()
		# it is forbidden for a MenuItem to have content and children, so it should not be moved
		self.assertEqual(parent_item.id, updated_child_item.parent.id)

	def test_update_order_as_non_superuser(self):
		def test_root_menu_order(root_menu_items):
			# check that order of root menu items has been preserved
			root_menu_iterator = zip(
				MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU, parent_id=None),
				root_menu_items
			)
			for possibly_changed_root_item, old_root_item in root_menu_iterator:
				self.assertEqual(possibly_changed_root_item.order, old_root_item.order)

		assign_perm(MenuItem.CHANGE_CHILDREN_PERMISSION_NAME, self.user, self.root_menu_item)
		root_menu_items = MenuItem.objects.filter(menu_type=MenuItem.MAIN_MENU, parent_id=None)

		# move subsub item to sub item position
		children_data = [{'id': menu_item.id} for menu_item in [self.sub_item, self.sub_sub_item]]
		order_data = {
			'main_menu_items': [
				{
					'id': self.root_menu_item.id,
					'children': children_data,
				},
			],
			'footer_items': [],
		}
		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.user)
		self.assertEqual(response.status_code, 200)

		root_menu_children = MenuItem.objects.filter(parent_id=self.root_menu_item.id)
		self.assertEqual(root_menu_children.count(), 2)
		test_root_menu_order(root_menu_items)

		# change order of children
		children_data = [{'id': menu_item.id} for menu_item in reversed(root_menu_children)]
		order_data['main_menu_items'][0]['children'] = children_data

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.user)
		self.assertEqual(response.status_code, 200)
		# check that order has indeed changed
		for changed_child, old_child in zip(reversed(MenuItem.objects.filter(parent_id=self.root_menu_item.id)), root_menu_children):
			self.assertNotEqual(changed_child.order, old_child.order)
		test_root_menu_order(root_menu_items)

		# put one child as child of another
		children_data = [
			{
				'id': root_menu_children[0].id,
				'children': [{'id': root_menu_children[1].id}],
			},
		]
		order_data['main_menu_items'][0]['children'] = children_data

		response = self.app.post(reverse('menu_items_update_order'), params=json.dumps(order_data), user=self.user)
		self.assertEqual(response.status_code, 200)

		self.assertEqual(MenuItem.objects.filter(parent_id=root_menu_children[0].id).count(), 1)
		test_root_menu_order(root_menu_items)

	def test_only_subitems_with_change_children_permission_are_visible(self):
		other_sub_item = baker.make(MenuItem, parent=self.root_menu_item)
		response = self.app.get(reverse('menu_items_index'), user=self.user)
		self.assertEqual(response.status_code, 200)
		self.assertIn(self.sub_item.title, response.body.decode('utf-8'))
		self.assertIn(self.root_menu_item.title, response.body.decode('utf-8'))
		self.assertIn(self.sub_sub_item.title, response.body.decode('utf-8'))
		self.assertNotIn(other_sub_item.title, response.body.decode('utf-8'))

	def test_menu_item_language_change(self):
		document = baker.make(InformationDocument)
		title_en = 'test title'
		title_de = 'test titel'

		response = self.app.get(reverse('menu_item_create'), user=self.user)
		form = response.form
		form['title_en'] = title_en
		form['title_de'] = title_de
		form['document'].select(value=document.id)
		form['group'].select(text=self.staff_group.name)
		form['parent'].select(text=self.sub_item.title)

		response = form.submit().maybe_follow()
		self.assertEqual(200, response.status_code)
		self.assertIn("Successfully created menu item.", response.body.decode('utf-8'))
		self.assertEqual(title_en, MenuItem.objects.get(title_en=title_en).title)

		response = self.app.post(reverse('set_lang'), params={'language': 'de'}, user=self.user).follow()
		self.assertEqual(response.status_code, 200)
		self.user.refresh_from_db()
		self.assertEqual(self.user.language, 'de')

		self.assertEqual(title_de, MenuItem.objects.get(title_en=title_en).title)


class TestSendRemindersCommand(TestCase):

	def test_remind_users_about_due_unpublished_minutes_documents(self):
		author_1 = baker.make(UserProfile, email='foo@example.com')
		author_2 = baker.make(UserProfile, email='bar@example.com')
		baker.make(
			MinutesDocument,
			date=datetime.date.today() - datetime.timedelta(days=settings.MINUTES_PUBLISH_REMINDER_DAYS),
			author=author_1
		)
		baker.make(
			MinutesDocument,
			date=datetime.date.today() - datetime.timedelta(days=settings.MINUTES_PUBLISH_REMINDER_DAYS),
			author=author_2
		)
		# don't send a reminder for this one
		baker.make(
			MinutesDocument,
			date=datetime.date.today() - datetime.timedelta(days=settings.MINUTES_PUBLISH_REMINDER_DAYS + 1),
			author=author_1
		)

		management.call_command('send_reminders')
		self.assertEqual(len(mail.outbox), 2)


class TestMissingMigrations(TestCase):
	def test_for_missing_migrations(self):
		output = StringIO()
		try:
			call_command('makemigrations', dry_run=True, check=True, stdout=output)
		except SystemExit:
			self.fail("There are model changes not reflected in migrations, please run makemigrations.")


class TestTools(TestCase):
	class DummyClass():
		title_de = "deutsch"
		title_en = "english"
		title = translate(en='title_en', de='title_de')

	def test_language_code_handling(self):
		for language_code in ['de', 'de-DE', 'de-CH']:
			with translation.override(language_code):
				dc = self.DummyClass()
				self.assertEqual('deutsch', dc.title)

		for language_code in ['en', 'en-US', 'en-AU', 'fr', 'fr-FR']:
			with translation.override(language_code):
				dc = self.DummyClass()
				self.assertEqual('english', dc.title)


class TestLanguageChange(WebTest):
	csrf_checks = False

	@classmethod
	def setUpTestData(cls):
		cls.user = baker.make(UserProfile)

	def test_language_change_for_authenticated_user(self):
		response = self.app.post(reverse('set_lang'), params={'language': 'de'}, user=self.user)
		self.assertEqual(response.status_code, 302)
		self.user.refresh_from_db()
		self.assertEqual(self.user.language, 'de')

		response = self.app.post(reverse('set_lang'), params={'language': 'en'}, user=self.user)
		self.assertEqual(response.status_code, 302)
		self.user.refresh_from_db()
		self.assertEqual(self.user.language, 'en')

	def test_language_change_for_unauthenticated_user(self):
		response = self.app.post(reverse('set_lang'), params={'language': 'de'}, user=None)
		self.assertEqual(response.status_code, 302)
		self.assertIn("setLanguage(\'en\');", response.follow().body.decode('utf-8'))

		response = self.app.post(reverse('set_lang'), params={'language': 'en'}, user=None)
		self.assertEqual(response.status_code, 302)
		self.assertIn("setLanguage(\'de\');", response.follow().body.decode('utf-8'))


@override_settings(LOGO_FILE="/static/images/logo.png")
class TestLogo(WebTest):
	def test_logo_is_shown(self):
		response = self.app.get(reverse('index'))
		self.assertEqual(response.status_code, 200)
		self.assertIn('<img src="/static/images/logo.png"', response.body.decode("utf-8"))


class TestEmailReplacement(TestCase):

	@override_settings(INSTITUTION_EMAIL_REPLACEMENTS=[("example.com", "institution.com")])
	def test_alternative_emails(self):
		email = 'name@example.com'
		other = 'name@institution.com'
		self.assertListEqual(
			[email] + list(alternative_emails(email)),
			[email, other]
		)
		self.assertListEqual(
			[other] + list(alternative_emails(other)),
			[other, email]
		)
		self.assertListEqual(
			list(alternative_emails('name@somewhereelse.org')),
			[]
		)
