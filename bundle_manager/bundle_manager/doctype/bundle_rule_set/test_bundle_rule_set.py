import frappe
from frappe.tests import IntegrationTestCase

# Item Group's own test-record chain pulls in standard ERPNext variant/item
# fixtures that conflict with item_code_generation's Item hooks on this site;
# Bundle Rule Set's tests don't need real Item Group test records.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item Group"]


class TestBundleRuleSet(IntegrationTestCase):
	def test_blank_resolver_script_does_not_require_script_manager_role(self):
		doc = frappe.get_doc(
			{
				"doctype": "Bundle Rule Set",
				"title": "Test Rule Set - No Script",
			}
		).insert()
		self.assertTrue(doc.name)
		frappe.delete_doc("Bundle Rule Set", doc.name)