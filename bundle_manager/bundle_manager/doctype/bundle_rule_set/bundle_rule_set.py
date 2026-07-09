import frappe
from frappe.model.document import Document


class BundleRuleSet(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from bundle_manager.bundle_manager.doctype.bundle_component_rule.bundle_component_rule import (
			BundleComponentRule,
		)

		applies_to_item_group: DF.Link | None
		component_rules: DF.Table[BundleComponentRule]
		disabled: DF.Check
		resolver_script: DF.Code | None
		title: DF.Data
	# end: auto-generated types

	def validate(self):
		if self.resolver_script and self.has_value_changed("resolver_script"):
			frappe.only_for("Script Manager", True)
			self.check_resolver_script_compiles()

	def check_resolver_script_compiles(self):
		"""Check compilation errors and surface them as a non-blocking warning, mirroring
		core Frappe's Server Script.check_if_compilable_in_restricted_context()."""
		from RestrictedPython import compile_restricted
		from frappe.utils.safe_exec import FrappeTransformer

		try:
			compile_restricted(self.resolver_script, policy=FrappeTransformer)
		except Exception as e:
			frappe.msgprint(str(e), title=frappe._("Compilation warning"))