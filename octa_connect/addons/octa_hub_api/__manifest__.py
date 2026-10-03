{
    "name": "Octa Hub API",
    "version": "19.0.1.0.1",
    "summary": "عقد API/Webhooks الموحد، منع التكرار، حدود الطلب - Gate B",
    "category": "Octa Connect",
    "author": "Octa-Tech",
    "license": "OPL-1",
    "depends": ["octa_hub_core"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/outbox_cron.xml",
    ],
    "installable": True,
}
