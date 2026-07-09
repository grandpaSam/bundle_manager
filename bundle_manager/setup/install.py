import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": "custom_requires_bundle",
			"label": "Requires Bundle",
			"fieldtype": "Check",
			"insert_after": "has_variants",
			"description": "If checked, this item must have a Product Bundle before it can be sold.",
		},
		{
			"fieldname": "custom_bundle_rule_set",
			"label": "Bundle Rule Set",
			"fieldtype": "Link",
			"options": "Bundle Rule Set",
			"insert_after": "custom_requires_bundle",
			"depends_on": "eval:doc.custom_requires_bundle",
		},
	]
}


VARIANT_COPY_FIELDS = ["custom_requires_bundle", "custom_bundle_rule_set"]


def after_migrate():
	create_custom_fields(CUSTOM_FIELDS)
	add_fields_to_variant_copy_list()


def add_fields_to_variant_copy_list():
	"""Item Variant creation only copies template fields listed in Item Variant
	Settings' "Fields to Copy" table (see erpnext.controllers.item_variant.
	copy_attributes_to_variant). Without this, custom_requires_bundle and
	custom_bundle_rule_set are silently dropped when variants are created.
	"""
	settings = frappe.get_single("Item Variant Settings")
	existing = {row.field_name for row in settings.fields}
	missing = [f for f in VARIANT_COPY_FIELDS if f not in existing]
	if not missing:
		return

	for fieldname in missing:
		settings.append("fields", {"field_name": fieldname})
	settings.save()