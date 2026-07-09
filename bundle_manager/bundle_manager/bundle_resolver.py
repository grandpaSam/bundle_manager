import frappe
from frappe import _
from frappe.utils.safe_exec import safe_exec


def get_item_attributes(item_code: str) -> dict[str, str]:
	rows = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code},
		fields=["attribute", "attribute_value"],
	)
	return {row.attribute: row.attribute_value for row in rows}


def _attribute_compatibility_map_installed() -> bool:
	return "template_bom_exploder" in frappe.get_installed_apps()


def _lookup_compatible_value(known_attribute: str, known_value: str, target_attribute: str) -> str | None:
	"""BOM Attribute Compatibility rows are treated as a two-way mapping
	despite the source/target field names, per template_bom_exploder's design."""
	value = frappe.db.get_value(
		"BOM Attribute Compatibility",
		{
			"source_attribute": known_attribute,
			"source_value": known_value,
			"target_attribute": target_attribute,
		},
		"target_value",
	)
	if value:
		return value

	return frappe.db.get_value(
		"BOM Attribute Compatibility",
		{
			"target_attribute": known_attribute,
			"target_value": known_value,
			"source_attribute": target_attribute,
		},
		"source_value",
	)


def _get_sku_code(attribute: str, attribute_value: str) -> str | None:
	"""item_code_generation adds a "sku_code" field to Item Attribute Value -
	the short code actually spliced into generated item codes (e.g. "09" for
	a "9mm" Caliber value). bundle_manager depends on item_code_generation,
	so component item codes are built from sku_code, not the raw attribute
	value."""
	return frappe.db.get_value(
		"Item Attribute Value",
		{"parent": attribute, "attribute_value": attribute_value},
		"sku_code",
	)


class _AttributeFormatMap(dict):
	"""Backs component_item_template.format_map(). Values resolve to their
	sku_code (falling back to the raw attribute value if none is set), since
	that's what belongs in a generated item code. A placeholder attribute the
	kit item doesn't carry directly falls back to the BOM Attribute
	Compatibility map (template_bom_exploder), if installed, to translate one
	of the kit's known raw attribute values into the requested one - e.g. a
	kit's "Caliber-Conversion-Kit" value resolving a component template's
	"{Caliber-ASR}" placeholder - before the sku_code lookup runs. First match
	wins. Falls back to the plain attributes dict if that app isn't
	installed."""

	def __getitem__(self, key):
		if dict.__contains__(self, key):
			value = dict.__getitem__(self, key)
			return _get_sku_code(key, value) or value

		if _attribute_compatibility_map_installed():
			for known_attribute, known_value in self.items():
				translated = _lookup_compatible_value(known_attribute, known_value, key)
				if translated:
					return _get_sku_code(key, translated) or translated

		raise KeyError(key)


def _get_rule_set(item_code: str):
	rule_set_name = frappe.db.get_value("Item", item_code, "custom_bundle_rule_set")
	if not rule_set_name:
		frappe.throw(
			_("Item {0} requires a bundle but has no Bundle Rule Set configured.").format(
				frappe.bold(item_code)
			)
		)

	rule_set = frappe.get_doc("Bundle Rule Set", rule_set_name)
	if rule_set.disabled:
		frappe.throw(
			_("Bundle Rule Set {0} for item {1} is disabled.").format(
				frappe.bold(rule_set.name), frappe.bold(item_code)
			)
		)
	return rule_set


def _resolve_components(rule_set, item_code: str) -> list[dict]:
	attributes = get_item_attributes(item_code)
	components = []

	for row in rule_set.component_rules:
		if row.condition:
			try:
				included = frappe.safe_eval(row.condition, {"attributes": attributes, "frappe": frappe})
			except Exception as e:
				frappe.throw(
					_(
						"Bundle Rule Set {0}, row #{1}: could not evaluate condition {2} for item {3}: {4}"
					).format(
						frappe.bold(rule_set.name),
						row.idx,
						frappe.bold(row.condition),
						frappe.bold(item_code),
						e,
					)
				)
		else:
			included = True

		if not included:
			continue

		try:
			resolved_item_code = row.component_item_template.format_map(_AttributeFormatMap(attributes))
		except (KeyError, IndexError) as e:
			frappe.throw(
				_(
					"Bundle Rule Set {0}, row #{1}: could not resolve placeholder {2} in template {3} for item {4}."
				).format(
					frappe.bold(rule_set.name),
					row.idx,
					e,
					frappe.bold(row.component_item_template),
					frappe.bold(item_code),
				)
			)

		if not frappe.db.exists("Item", resolved_item_code):
			frappe.throw(
				_(
					"Bundle Rule Set {0}, row #{1}: resolved component item {2} does not exist (from template {3} for item {4})."
				).format(
					frappe.bold(rule_set.name),
					row.idx,
					frappe.bold(resolved_item_code),
					row.component_item_template,
					frappe.bold(item_code),
				)
			)

		components.append({"item_code": resolved_item_code, "qty": row.qty or 1})

	return components


@frappe.whitelist()
def resolve_bundle(item_code: str) -> str:
	"""Ensures a Product Bundle exists for item_code, creating it if missing.

	Returns the Product Bundle name (== item_code, since Product Bundle is
	keyed by parent item). Raises frappe.ValidationError with a clear message
	if it cannot resolve (no rule set, no resolver, rule evaluation error, etc).
	"""
	if frappe.db.exists("Product Bundle", item_code):
		return item_code

	rule_set = _get_rule_set(item_code)

	if rule_set.resolver_script:
		safe_exec(
			rule_set.resolver_script,
			_locals={"item_code": item_code},
			restrict_commit_rollback=False,
			script_filename=rule_set.name,
		)
		if not frappe.db.exists("Product Bundle", item_code):
			frappe.throw(
				_(
					"Resolver Script on Bundle Rule Set {0} did not create a Product Bundle for item {1}."
				).format(frappe.bold(rule_set.name), frappe.bold(item_code))
			)
		return item_code

	bundle = frappe.get_doc(
		{
			"doctype": "Product Bundle",
			"new_item_code": item_code,
			"items": _resolve_components(rule_set, item_code),
		}
	)
	bundle.insert()
	return item_code


@frappe.whitelist()
def preview_bundle(item_code: str) -> dict:
	"""Used by the Item form's "Generate Bundle" button, so the user sees an
	unsaved draft Product Bundle to review before it's actually created.

	A resolver_script is arbitrary code that's fully responsible for creating
	the Product Bundle itself (see resolve_bundle) - there's nothing to
	preview, so it's run immediately same as resolve_bundle. Otherwise the
	rule table's components are resolved WITHOUT creating anything, so the
	caller can open an unsaved Product Bundle with them prefilled.
	"""
	if frappe.db.exists("Product Bundle", item_code):
		return {"created": True, "name": item_code}

	rule_set = _get_rule_set(item_code)

	if rule_set.resolver_script:
		return {"created": True, "name": resolve_bundle(item_code)}

	return {"created": False, "components": _resolve_components(rule_set, item_code)}