frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.custom_requires_bundle) {
			return;
		}

		frappe.db.exists("Product Bundle", frm.doc.name).then((exists) => {
			if (exists) {
				return;
			}

			frm.add_custom_button(__("Generate Bundle"), () => {
				if (!frm.doc.custom_bundle_rule_set) {
					// new_item_code is marked no_copy in Product Bundle, so
					// frappe.route_options (the `opts` argument) can't set it —
					// set it directly on the new doc via the init_callback instead.
					frappe.new_doc("Product Bundle", null, (doc) => {
						doc.new_item_code = frm.doc.name;
					});
					return;
				}

				frappe.call({
					method: "bundle_manager.bundle_manager.bundle_resolver.preview_bundle",
					args: { item_code: frm.doc.name },
					freeze: true,
					freeze_message: __("Resolving Bundle Components..."),
				}).then((r) => {
					if (!r.message) return;

					if (r.message.created) {
						frappe.show_alert({
							message: __("Product Bundle {0} created.", [r.message.name]),
							indicator: "green",
						});
						frm.reload_doc();
						return;
					}

					// Rule table resolved successfully but nothing was created —
					// open it as an unsaved draft so the user can review before saving.
					frappe.new_doc("Product Bundle", null, (doc) => {
						doc.new_item_code = frm.doc.name;
						// get_new_doc() auto-adds a blank row for the mandatory
						// "items" table before this callback runs — drop it before
						// adding the resolved components.
						doc.items = [];
						for (const component of r.message.components) {
							const row = frappe.model.add_child(doc, "items");
							row.item_code = component.item_code;
							row.qty = component.qty;
						}
					});
				});
			});
		});
	},
});