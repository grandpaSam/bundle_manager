### Bundle Manager
This app is hard dependant on my item_sku_generation app. 

It also uses the attribute compatibility map doc type from the template_bom_exploder app but it is not a hard depandency. You will have to just live with 1 to 1 mapping with item attributes.

Rule-driven Product Bundle generation

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app bundle_manager
```



### License

gpl-3.0
