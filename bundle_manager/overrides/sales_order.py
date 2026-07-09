import frappe

from bundle_manager.bundle_manager.bundle_resolver import resolve_bundle


def validate_bundle_requirements(doc, method=None):
	for item in doc.items:
		if not frappe.db.get_value("Item", item.item_code, "custom_requires_bundle"):
			continue
		resolve_bundle(item.item_code)