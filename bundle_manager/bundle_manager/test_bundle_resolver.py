import frappe
from frappe.tests import IntegrationTestCase

from bundle_manager.bundle_manager.bundle_resolver import preview_bundle, resolve_bundle


class TestBundleResolver(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(self._cleanup)
		self._docs_to_delete = []

		self.attribute = self._make_item_attribute(
			"Test BM Caliber", ["9mm", "45 ACP"]
		)
		self.magazine = self._make_item("TEST-BM-MAGAZINE")
		self.barrel_9mm = self._make_item("TEST-BM-BARREL-9MM")
		self.lower = self._make_item("TEST-BM-LOWER")

	def _cleanup(self):
		for doctype, name in reversed(self._docs_to_delete):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	def _make_item_attribute(self, name, values, sku_codes=None):
		if frappe.db.exists("Item Attribute", name):
			return name
		sku_codes = sku_codes or {}
		doc = frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": name,
				"item_attribute_values": [
					{"attribute_value": v, "abbr": v[:3].upper(), "sku_code": sku_codes.get(v)} for v in values
				],
			}
		).insert(ignore_permissions=True)
		self._docs_to_delete.append(("Item Attribute", doc.name))
		return doc.name

	def _make_item(self, item_code, attributes=None, requires_bundle=False, rule_set=None):
		if frappe.db.exists("Item", item_code):
			frappe.delete_doc("Item", item_code, force=True, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": "All Item Groups",
				"stock_uom": "Each",
				"is_stock_item": 0 if requires_bundle else 1,
				"custom_requires_bundle": 1 if requires_bundle else 0,
				"custom_bundle_rule_set": rule_set,
			}
		).insert(ignore_permissions=True)
		self._docs_to_delete.append(("Item", doc.name))

		# Inserted as standalone child rows (not via doc.attributes on the Item
		# itself) to bypass item_code_generation's before_save hook, which
		# demands item_code placeholders for any Item saved with populated
		# variant attributes — unrelated to what's under test here.
		for attr in attributes or []:
			frappe.get_doc(
				{
					"doctype": "Item Variant Attribute",
					"parent": doc.name,
					"parenttype": "Item",
					"parentfield": "attributes",
					**attr,
				}
			).insert(ignore_permissions=True)

		return doc.name

	def _make_rule_set(self, **kwargs):
		doc = frappe.get_doc({"doctype": "Bundle Rule Set", **kwargs}).insert(ignore_permissions=True)
		self._docs_to_delete.append(("Bundle Rule Set", doc.name))
		return doc

	def test_returns_existing_bundle_without_touching_rule_set(self):
		kit = self._make_item("TEST-BM-KIT-EXISTS", requires_bundle=True)
		bundle = frappe.get_doc(
			{
				"doctype": "Product Bundle",
				"new_item_code": kit,
				"items": [{"item_code": self.magazine, "qty": 1}],
			}
		).insert(ignore_permissions=True)
		self._docs_to_delete.append(("Product Bundle", bundle.name))

		result = resolve_bundle(kit)
		self.assertEqual(result, kit)

	def test_missing_rule_set_throws_clear_error(self):
		kit = self._make_item("TEST-BM-KIT-NO-RULESET", requires_bundle=True)
		with self.assertRaises(frappe.ValidationError):
			resolve_bundle(kit)

	def test_disabled_rule_set_throws(self):
		rule_set = self._make_rule_set(title="Test BM Rule Set - Disabled", disabled=1)
		kit = self._make_item("TEST-BM-KIT-DISABLED", requires_bundle=True, rule_set=rule_set.name)
		with self.assertRaises(frappe.ValidationError):
			resolve_bundle(kit)

	def test_condition_true_false_and_placeholder_resolution(self):
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Conditions",
			component_rules=[
				{"condition": "", "component_item_template": "TEST-BM-MAGAZINE", "qty": 1},
				{
					"condition": 'attributes["Test BM Caliber"] == "9mm"',
					"component_item_template": "TEST-BM-BARREL-9MM",
					"qty": 1,
				},
				{
					"condition": 'attributes["Test BM Caliber"] == "45 ACP"',
					"component_item_template": "TEST-BM-LOWER",
					"qty": 2,
				},
			],
		)
		kit = self._make_item(
			"TEST-BM-KIT-9MM",
			attributes=[{"attribute": self.attribute, "attribute_value": "9mm"}],
			requires_bundle=True,
			rule_set=rule_set.name,
		)

		result = resolve_bundle(kit)
		self._docs_to_delete.append(("Product Bundle", result))

		bundle = frappe.get_doc("Product Bundle", result)
		included = {row.item_code: row.qty for row in bundle.items}
		self.assertEqual(included, {self.magazine: 1, self.barrel_9mm: 1})
		self.assertNotIn(self.lower, included)

	def test_sku_code_used_for_component_placeholder(self):
		attribute = self._make_item_attribute("Test BM Caliber SKU", ["9mm"], sku_codes={"9mm": "09"})
		component = self._make_item("TEST-BM-BARREL-09")

		rule_set = self._make_rule_set(
			title="Test BM Rule Set - SKU Code",
			component_rules=[
				{
					# condition still evaluates against the raw attribute value,
					# not the sku_code, even though the placeholder below resolves
					# to the sku_code.
					"condition": 'attributes["Test BM Caliber SKU"] == "9mm"',
					"component_item_template": "TEST-BM-BARREL-{Test BM Caliber SKU}",
					"qty": 1,
				},
			],
		)
		kit = self._make_item(
			"TEST-BM-KIT-SKUCODE",
			attributes=[{"attribute": attribute, "attribute_value": "9mm"}],
			requires_bundle=True,
			rule_set=rule_set.name,
		)

		result = resolve_bundle(kit)
		self._docs_to_delete.append(("Product Bundle", result))

		bundle = frappe.get_doc("Product Bundle", result)
		self.assertEqual({row.item_code for row in bundle.items}, {component})

	def test_attribute_compatibility_map_translates_placeholder(self):
		if "template_bom_exploder" not in frappe.get_installed_apps():
			self.skipTest("template_bom_exploder not installed")

		alt_attribute = self._make_item_attribute("Test BM Caliber Alt", ["ALT9"])
		compat = frappe.get_doc(
			{
				"doctype": "BOM Attribute Compatibility",
				"source_attribute": self.attribute,
				"source_value": "9mm",
				"target_attribute": alt_attribute,
				"target_value": "ALT9",
			}
		).insert(ignore_permissions=True)
		self._docs_to_delete.append(("BOM Attribute Compatibility", compat.name))

		component = self._make_item("TEST-BM-BARREL-ALT9")

		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Attribute Map",
			component_rules=[
				{
					"condition": "",
					"component_item_template": "TEST-BM-BARREL-{Test BM Caliber Alt}",
					"qty": 1,
				},
			],
		)
		kit = self._make_item(
			"TEST-BM-KIT-ATTRMAP",
			attributes=[{"attribute": self.attribute, "attribute_value": "9mm"}],
			requires_bundle=True,
			rule_set=rule_set.name,
		)

		result = resolve_bundle(kit)
		self._docs_to_delete.append(("Product Bundle", result))

		bundle = frappe.get_doc("Product Bundle", result)
		self.assertEqual({row.item_code for row in bundle.items}, {component})

	def test_bad_condition_raises_row_identifying_error(self):
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Bad Condition",
			component_rules=[
				{"condition": "attributes[undefined_name]", "component_item_template": "TEST-BM-MAGAZINE", "qty": 1},
			],
		)
		kit = self._make_item(
			"TEST-BM-KIT-BADCOND",
			attributes=[{"attribute": self.attribute, "attribute_value": "9mm"}],
			requires_bundle=True,
			rule_set=rule_set.name,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "row #1"):
			resolve_bundle(kit)

	def test_unresolvable_placeholder_raises_clear_error(self):
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Bad Placeholder",
			component_rules=[
				{"condition": "", "component_item_template": "TEST-BM-{Nonexistent Attribute}", "qty": 1},
			],
		)
		kit = self._make_item(
			"TEST-BM-KIT-BADPLACEHOLDER",
			attributes=[{"attribute": self.attribute, "attribute_value": "9mm"}],
			requires_bundle=True,
			rule_set=rule_set.name,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "placeholder"):
			resolve_bundle(kit)

	def test_missing_component_item_raises_clear_error(self):
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Missing Component",
			component_rules=[
				{"condition": "", "component_item_template": "TEST-BM-DOES-NOT-EXIST", "qty": 1},
			],
		)
		kit = self._make_item("TEST-BM-KIT-MISSINGCOMP", requires_bundle=True, rule_set=rule_set.name)
		with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
			resolve_bundle(kit)

	def test_resolver_script_escape_hatch(self):
		script = (
			"item = frappe.get_doc('Item', item_code)\n"
			"item.is_stock_item = 0\n"
			"frappe.get_doc({\n"
			"    'doctype': 'Product Bundle',\n"
			"    'new_item_code': item_code,\n"
			"    'items': [{'item_code': 'TEST-BM-MAGAZINE', 'qty': 1}],\n"
			"}).insert(ignore_permissions=True)\n"
		)
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Script",
			resolver_script=script,
		)
		kit = self._make_item("TEST-BM-KIT-SCRIPT", requires_bundle=True, rule_set=rule_set.name)

		result = resolve_bundle(kit)
		self._docs_to_delete.append(("Product Bundle", result))
		self.assertEqual(result, kit)
		self.assertTrue(frappe.db.exists("Product Bundle", kit))

	def test_preview_bundle_resolves_components_without_creating(self):
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Preview",
			component_rules=[
				{"condition": "", "component_item_template": "TEST-BM-MAGAZINE", "qty": 1},
			],
		)
		kit = self._make_item("TEST-BM-KIT-PREVIEW", requires_bundle=True, rule_set=rule_set.name)

		result = preview_bundle(kit)

		self.assertEqual(result, {"created": False, "components": [{"item_code": self.magazine, "qty": 1}]})
		self.assertFalse(frappe.db.exists("Product Bundle", kit))

	def test_preview_bundle_runs_resolver_script_immediately(self):
		script = (
			"frappe.get_doc({\n"
			"    'doctype': 'Product Bundle',\n"
			"    'new_item_code': item_code,\n"
			"    'items': [{'item_code': 'TEST-BM-MAGAZINE', 'qty': 1}],\n"
			"}).insert(ignore_permissions=True)\n"
		)
		rule_set = self._make_rule_set(
			title="Test BM Rule Set - Preview Script",
			resolver_script=script,
		)
		kit = self._make_item("TEST-BM-KIT-PREVIEWSCRIPT", requires_bundle=True, rule_set=rule_set.name)

		result = preview_bundle(kit)
		self._docs_to_delete.append(("Product Bundle", kit))

		self.assertEqual(result, {"created": True, "name": kit})
		self.assertTrue(frappe.db.exists("Product Bundle", kit))