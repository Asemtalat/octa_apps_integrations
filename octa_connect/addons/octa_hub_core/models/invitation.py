# -*- coding: utf-8 -*-
"""
octa.hub.invitation — دورة الحساب: pending_invitation → verified/active أو
suspended/revoked (القسم 7). NOT RUN — لا Odoo متاح؛ راجع docs/security.md
لكل بند غير مؤكد (NOT VERIFIED) يحتاج تحققًا مباشرًا من واجهات Odoo 19.

قواعد ملزمة مطبَّقة هنا حرفيًا من القسم 7:
- لا كلمة مرور تُرسل بالبريد؛ المستخدم يضعها بنفسه بعد قبول الدعوة.
- رابط التفعيل: عشوائي آمن، محدود العمر، لمرة واحدة، مرتبط بالحساب والغرض.
- لا يُستهلك الرمز بمجرد GET (مسح بريد)؛ الاستهلاك بفعل POST صريح فقط.
- إعادة الإصدار تُبطل الرمز السابق فورًا.
- نخزن بصمة (hash) الرمز فقط، لا الرمز نفسه، ولا نطبعه في اللوج.
- الاستهلاك ذرّي أمام التزامن (نفس الرمز لا يُستهلك مرتين بالتوازي).
"""
import hashlib
import logging
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

TOKEN_BYTES = 32           # عشوائية كافية (256-bit) لرابط التفعيل/الاستعادة
TOKEN_TTL_HOURS = 48       # عمر افتراضي — قابل للتعديل عبر إعداد نظام موثّق


def _hash_token(raw_token: str) -> str:
    # بصمة فقط تُخزَّن؛ الرمز الخام لا يُحفظ ولا يظهر في أي لوج
    return hashlib.sha256(raw_token.encode()).hexdigest()


class OctaHubInvitation(models.Model):
    _name = "octa.hub.invitation"
    _description = "Account invitation / verification / password-reset token lifecycle"
    _order = "create_date desc"

    email = fields.Char(required=True, index=True)
    purpose = fields.Selection([
        ("initial_invite", "دعوة أولى"),
        ("email_verification", "تحقق بريد"),
        ("password_reset", "استعادة كلمة مرور"),
        ("factor_change", "تغيير عامل مصادقة"),
    ], required=True)
    membership_id = fields.Many2one("octa.hub.membership", ondelete="cascade")
    token_hash = fields.Char(required=True, readonly=True)
    created_by_user_id = fields.Many2one(
        "res.users", required=True, readonly=True,
        help="فقط مستخدم أوكتاتيك مخوّل ينشئ دعوة أولى؛ يُتحقق في create() أدناه")
    expires_at = fields.Datetime(required=True)
    consumed_at = fields.Datetime(readonly=True)
    superseded_by_id = fields.Many2one("octa.hub.invitation", readonly=True)
    account_state_before = fields.Selection([
        ("pending_invitation", "بانتظار الدعوة"),
        ("verified", "تم التحقق"),
        ("active", "نشط"),
        ("suspended", "موقوف"),
        ("revoked", "ملغى"),
    ])

    @api.model_create_multi
    def create(self, vals_list):
        """إصلاح حرج مكتشف بتشغيل فعلي حقيقي لأول مرة (لم تكتشفه أي قراءة
        كود أو مراجعة عبر 20 جولة، بما فيها مراجعتان مستقلتان خارجيتان):
        كانت مُزيَّنة بـ`@api.model` وتأخذ `vals` كقاموس واحد — نمط Odoo
        قديم بائد. Odoo 19 يستدعي `create()` دائمًا بقائمة قواميس فعليًا
        (حتى لإنشاء سجل واحد)، والتزيين الصحيح لهذا هو `@api.model_create_multi`
        — بدونه، `vals` كانت تصل فعليًا كـ**قائمة** لا قاموسًا، و`vals.get(...)`
        كانت ترفع `AttributeError: 'list' object has no attribute 'get'`
        **في كل استدعاء create() على هذا الموديل بلا استثناء** — يعني نظام
        الدعوات بأكمله كان معطوبًا بالكامل، لا يعمل إطلاقًا، منذ الجولة
        الأولى. فشل آمن (يمنع الإنشاء بدل تجاوز الفحص الأمني)، لكنه عطل
        وظيفي كامل لا مجرد ثغرة جانبية."""
        for vals in vals_list:
            if vals.get("purpose") == "initial_invite":
                creator = self.env["res.users"].browse(vals.get("created_by_user_id") or self.env.uid)
                is_authorized_octatech = bool(
                    creator.env["octa.hub.membership"].sudo().search_count([
                        ("user_id", "=", creator.id),
                        ("party_type", "=", "octatech"),
                        ("role_code", "=", "octatech_identity_admin"),
                        ("active", "=", True),
                    ])
                )
                if not is_authorized_octatech:
                    # القسم 6: "يمنح أدوار إنشاء الحسابات فقط مستخدم أوكتاتيك مخول"
                    raise AccessError(_("فقط مدير هوية معتمد من أوكتاتيك يمكنه إنشاء دعوة أولى"))
        return super().create(vals_list)

    @api.model
    def issue(self, email, purpose, membership=None, created_by_user=None):
        """يُصدر رمزًا جديدًا ويُبطل أي رمز سابق لنفس (email, purpose) فورًا."""
        raw_token = secrets.token_urlsafe(TOKEN_BYTES)
        rec = self.create({
            "email": email,
            "purpose": purpose,
            "membership_id": membership.id if membership else False,
            "token_hash": _hash_token(raw_token),
            "created_by_user_id": (created_by_user or self.env.user).id,
            "expires_at": fields.Datetime.now() + __import__("datetime").timedelta(hours=TOKEN_TTL_HOURS),
        })
        # إصلاح بعد مراجعة قبول نهائية (فحص ملف-بملف): حقل superseded_by_id
        # كان مُعرَّفًا في الموديل لكن **لا يُكتب في أي مكان إطلاقًا** — وجود
        # الحقل لا يثبت أن الربط يعمل. الآن يُسجَّل صراحة أي الدعوة القديمة
        # التي أبطلتها هذه الدعوة الجديدة، بدل الاكتفاء بوسم consumed_at
        # الذي لا يميّز "استُهلك فعليًا" عن "أُبطل بإعادة إصدار".
        previous = self.search([("email", "=", email), ("purpose", "=", purpose),
                                 ("consumed_at", "=", False), ("id", "!=", rec.id)])
        previous.write({"consumed_at": fields.Datetime.now(), "superseded_by_id": rec.id})
        # الرمز الخام يُعاد للمُصدِر فقط (ليُرسَل بالبريد الاختباري)؛ لا يُطبع في اللوج أبدًا
        _logger.info("invitation issued id=%s purpose=%s (token not logged)", rec.id, purpose)
        return rec, raw_token

    def preview_only(self, raw_token):
        """مسار GET (فتح الرابط من ماسح بريد) — للعرض فقط، لا استهلاك هنا.
        القسم 7: 'لا تستهلكه بمجرد GET من ماسح بريد؛ القبول بفعل صريح'.

        إصلاح حرج بعد مراجعة مستقلة خارجية (R07)، مُتحقَّق منه بمصدر Odoo 19
        الحقيقي: `odoo/orm/fields.py::Field.convert_to_record` يحوّل صراحة
        `None` إلى `False` قبل وصول القيمة لكود بايثون
        (`return False if value is None else value`) — يعني `rec.consumed_at`
        سيكون `False` دائمًا لحقل Datetime فارغ، **ليس `None` أبدًا**.
        الفحص السابق `rec.consumed_at is None` كان سيُقيَّم دائمًا كـ`False`
        (لأن `False is None` == `False` في بايثون)، فتظهر كل دعوة — حتى
        الصادرة للتو دون استهلاك — كـ"غير صالحة" دائمًا. أُصلح بفحص truthy
        عادي (`not rec.consumed_at`) بدل مقارنة الهوية بـ`None`.
        """
        rec = self._find_by_raw_token(raw_token)
        if not rec:
            return None
        return {
            "valid": (not rec.consumed_at) and rec.expires_at > fields.Datetime.now(),
            "purpose": rec.purpose,
            "email": rec.email,
        }

    def consume(self, raw_token, allowed_purposes=None):
        """الاستهلاك الفعلي — يجب أن يُستدعى فقط من فعل POST صريح (زر
        'تأكيد' وليس مجرد فتح الصفحة).

        إصلاحان بعد مراجعة V2 المستقلة:

        1. **R07 — ذرية حقيقية الآن**: كان التعليق يدّعي حماية SELECT FOR
           UPDATE "معلَّقة" بينما لا قفل فعليًا في الكود — تعارض بين التوثيق
           والتنفيذ رصدته المراجعة بحق. أُصلح فعليًا عبر `rec.lock_for_update()`
           (مُتحقَّقة من `odoo/orm/models.py` في مصدر Odoo 19 الحقيقي — تستخدم
           `FOR UPDATE SKIP LOCKED` وترفع `LockError` فورًا بدل الانتظار
           اللانهائي). القفل يُطلَب **قبل** إعادة فحص consumed_at/expires_at
           (نمط double-check) — طلبان متزامنان لنفس الرمز: أحدهما يحصل على
           القفل وينجح، والآخر يفشل بـLockError فورًا (بلا حظر/تعليق).
        2. **R06 — تقييد الغرض (purpose)**: لم يكن هناك أي تحقق من أن الرمز
           المُستهلَك مخصص فعلًا لتعيين كلمة مرور — رمز `email_verification`
           أو `factor_change` كان يمكن استهلاكه عبر نفس هذا المسار وكأنه
           `initial_invite`/`password_reset`. أُضيف معامل `allowed_purposes`
           صريح؛ الاستدعاء من auth_controller.py يمرره الآن.
        """
        rec = self._find_by_raw_token(raw_token)
        if not rec:
            raise ValidationError(_("رابط غير صالح"))

        try:
            rec.lock_for_update()
        except Exception as e:  # LockError الحقيقية من Odoo، NOT VERIFIED نوعها الدقيق هنا بدون تشغيل فعلي
            raise ValidationError(_("جارٍ معالجة هذا الرابط في طلب آخر متزامن — أعد المحاولة")) from e

        # إعادة الفحص بعد الحصول على القفل (double-check) — قيمة rec قد تكون
        # تغيّرت بين القراءة الأولى وهذه اللحظة في طلب متزامن آخر سبق وحصل
        # على القفل وأتمّ عمله قبل أن يصل هذا الطلب لدوره.
        rec.invalidate_recordset()
        if allowed_purposes and rec.purpose not in allowed_purposes:
            raise ValidationError(_("هذا الرابط غير صالح لهذا الإجراء"))
        if rec.consumed_at:
            raise ValidationError(_("تم استخدام هذا الرابط من قبل"))
        if rec.expires_at <= fields.Datetime.now():
            raise ValidationError(_("انتهت صلاحية هذا الرابط"))
        rec.consumed_at = fields.Datetime.now()
        return rec

    def _find_by_raw_token(self, raw_token):
        token_hash = _hash_token(raw_token)
        return self.sudo().search([("token_hash", "=", token_hash)], limit=1)
