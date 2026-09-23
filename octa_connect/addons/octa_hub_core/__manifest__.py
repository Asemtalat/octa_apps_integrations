{
    "name": "Octa Hub Core",
    "version": "19.0.1.0.1",
    "summary": "الهيئات والفروع والعضويات والصلاحيات وتفويضات الشركاء - Octa Connect Gate A/B core",
    "description": """
Octa Hub Core
=============
النموذج التنظيمي الأساسي لمنصة Octa Connect: Organization/Tenant/Branch/
Membership/Role/PartnerGrant/Invitation/AuditLog/Order، منفصل عمدًا عن
res.company وعن point_of_sale/sale/stock/account (القسم 1 و6 من ملف
Octa_Connect_Claude_Phase_1.md). لا اعتماد وظيفي على تلك الموديولات.

حالة هذا الموديول: مكتوب لكن NOT RUN — لا يوجد Odoo 19 حقيقي في بيئة
التطوير الحالية (لا PostgreSQL ولا صلاحيات تثبيت نظام). راجع
docs/requirements-coverage.md وdocs/test-report.md للتفاصيل الدقيقة.
""",
    "category": "Octa Connect",
    "author": "Octa-Tech",
    "license": "OPL-1",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/auth_templates.xml",
        "data/demo_data.xml",
    ],
    "installable": True,
    "application": True,
}
