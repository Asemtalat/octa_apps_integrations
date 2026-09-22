{
    "name": "Octa Hub UI",
    "version": "19.0.1.1.0",
    "summary": "بوابة التاجر - نظرة عامة وقائمة الطلبات وتفاصيلها (Gate C) - أساس فقط، غير مكتمل",
    "category": "Octa Connect",
    "author": "Octa-Tech",
    "license": "OPL-1",
    "depends": ["octa_hub_core", "web"],
    "data": [
        "views/ui_actions.xml",
        "views/merchant_portal.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "octa_hub_ui/static/src/scss/design_tokens.scss",
            "octa_hub_ui/static/src/js/components/shared_components.js",
            "octa_hub_ui/static/src/js/dashboard.js",
            "octa_hub_ui/static/src/js/order_list.js",
            "octa_hub_ui/static/src/js/order_detail.js",
            "octa_hub_ui/static/src/xml/components.xml",
            "octa_hub_ui/static/src/xml/dashboard.xml",
            "octa_hub_ui/static/src/xml/order_list.xml",
            "octa_hub_ui/static/src/xml/order_detail.xml",
        ],
    },
    "installable": True,
}
