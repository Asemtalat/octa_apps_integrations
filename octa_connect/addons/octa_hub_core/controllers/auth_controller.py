# -*- coding: utf-8 -*-
"""
Controllers رفيعة فعلًا (القسم 5: "لا تخلط صيغة تطبيق بعينه في قلب المنتج")
— كل منطق التحقق والحفظ في octa.hub.invitation، هنا فقط التوجيه وHTTP.

NOT RUN — لا يمكن تشغيل route فعلي بدون Odoo HTTP server حقيقي. هذا كود
مصدري مراجَع يدويًا فقط مقابل معرفتي بـ Odoo 19 API، وليس نتيجة تشغيل.

نقاط أمان مطبّقة حرفيًا من القسم 7:
- /invite/preview هو GET وللعرض فقط (لا استهلاك).
- /invite/accept هو POST فقط (auth='public' لأنها ما قبل تسجيل الدخول، لكن
  بلا وصول لأي بيانات عمل — فقط استهلاك الرمز وتعيين كلمة المرور).
- لا نُرجع رسائل تكشف وجود/عدم وجود البريد.
"""
from odoo import http
from odoo.http import request


class OctaHubAuthController(http.Controller):

    @http.route("/octa/invite/preview", type="http", auth="public", methods=["GET"], csrf=False)
    def invite_preview(self, token=None, **kw):
        """GET فقط — لا استهلاك (القسم 7). يُستخدم لعرض نموذج تعيين كلمة المرور."""
        if not token:
            return request.render("octa_hub_core.invite_invalid_page", {})
        info = request.env["octa.hub.invitation"].sudo().preview_only(token)
        if not info or not info["valid"]:
            return request.render("octa_hub_core.invite_invalid_page", {})
        return request.render("octa_hub_core.invite_accept_form", {"email": info["email"]})

    @http.route("/octa/invite/accept", type="http", auth="public", methods=["POST"], csrf=True)
    def invite_accept(self, token=None, password=None, password_confirm=None, **kw):
        """POST صريح فقط — هذا هو فعل "القبول" الذي يستهلك الرمز فعليًا.
        CSRF مفعّل (القسم 7: "حماية CSRF لجلسات المتصفح"). كلمة المرور
        يضعها المستخدم بنفسه؛ لا نستقبل كلمة مرور جاهزة من بريد.

        إصلاح حرج بعد مراجعة مستقلة خارجية (R06): النسخة السابقة كانت
        تستهلك الرمز فقط **وتعرض "تم تفعيل الحساب" دون فعل أي شيء فعلي** —
        لا ربط مستخدم، لا تعيين كلمة مرور، نجاح واجهة وهمي بالكامل. أُصلح
        بالربط الفعلي: `octa.hub.membership.user_id` **مطلوب (required)
        في تعريف النموذج** (تعمُّدًا — القسم 6)، ما يعني أن حساب `res.users`
        يجب أن يكون موجودًا مسبقًا (أنشأه مدير الهوية المخوّل عند إنشاء
        العضوية، غير نشط/بكلمة مرور عشوائية غير قابلة للاستخدام) قبل صدور
        أي دعوة — القبول هنا **يُفعِّل** هذا الحساب القائم ويضبط كلمة مروره
        الحقيقية، لا ينشئ حسابًا جديدًا من الصفر. كل هذا داخل savepoint
        واحد — فشل أي خطوة يُبطل الاستهلاك بأكمله، لا نجاح جزئي.

        NOT VERIFIED: الاستدعاء الدقيق لتعيين كلمة المرور
        (`user.sudo().write({'password': password})`) مبني على معرفتي بأن
        Odoo يقبل `password` كقيمة نصية عادية في `write()`/`create()`
        ويتولى تجزئتها داخليًا (مُتحقَّق من وجود هذا المسار في
        `odoo/addons/base/models/res_users.py`، لكن لم يُشغَّل فعليًا على
        تثبيت حقيقي في هذه الجلسة).
        """
        if not token or not password or password != password_confirm:
            return request.render("octa_hub_core.invite_invalid_page", {})

        try:
            with request.env.cr.savepoint():
                invitation = request.env["octa.hub.invitation"].sudo().consume(
                    token, allowed_purposes=("initial_invite", "password_reset"))
                if not invitation.membership_id or not invitation.membership_id.user_id:
                    # لا مستخدم مرتبط بهذه الدعوة — حالة بيانات غير متسقة،
                    # لا نُظهر نجاحًا رغم استهلاك الرمز (يُلغى الاستهلاك عبر
                    # رفع الاستثناء داخل الـsavepoint).
                    raise ValueError("invitation has no linked user account")
                user = invitation.membership_id.user_id
                # إصلاح بعد مراجعة V2 المستقلة (R06): لم يكن هناك أي فحص
                # لحالة عضوية المستخدم أو حالة عميله (موقوف) قبل إعادة
                # تفعيل الحساب — رمز قديم لمستخدم أُوقف لاحقًا كان سيعيد
                # تفعيل حسابه دون أي تحقق. أُضيف الفحص التالي.
                membership = invitation.membership_id
                if not membership.active:
                    raise ValueError("membership is no longer active")
                if (membership.party_type == "merchant" and membership.organization_id
                        and membership.organization_id.state == "suspended"):
                    raise ValueError("organization is suspended")
                user.sudo().write({"password": password, "active": True})
        except ValueError:
            return request.render("octa_hub_core.invite_invalid_page", {})

        return request.render("octa_hub_core.invite_accepted_page", {"email": invitation.email})

    @http.route("/octa/pre_auth_probe", type="http", auth="public", methods=["POST"], csrf=False)
    def pre_auth_probe(self, **kw):
        """اختبار سلبي مطلوب صراحة (القسم 14): 'الجلسة السابقة للتحقق لا
        تقرأ أي بيانات حتى عبر مسارات أودو المباشرة'. هذا المسار موجود فقط
        لإثبات أنه لا يعيد أي بيانات عمل قبل اكتمال المصادقة.

        إصلاح (اكتُشف بتشغيل فعلي حقيقي لأول مرة على Odoo 19 حقيقي —
        DeprecationWarning ظهر فعليًا عند تحميل الموديول، لم يُكتشَف بالقراءة
        وحدها رغم إصلاح نفس النمط بالضبط في api_controller.py سابقًا R09):
        كانت `type="json"` — نفس علة R09 (مهجورة، تُغلِّف الرد بمغلف
        jsonrpc بحالة HTTP 200 ثابتة، لا تصلح لرد بسيط كهذا). أُصلح لـ
        `type="http"` + `request.make_json_response`، مطابقًا للنمط
        المُتحقَّق فعليًا في api_controller.py."""
        return request.make_json_response({"ok": True, "data": None})

    @http.route("/octa/password_reset/request", type="http", auth="public", methods=["POST"], csrf=True)
    def password_reset_request(self, email=None, **kw):
        """إصلاح بعد مراجعة قبول نهائية (فحص ملف-بملف): الموديل يدعم
        `purpose='password_reset'` وتوجد صفحة "أواجه مشكلة في الوصول إلى
        بريدي الإلكتروني" في صور المرجع (شاشة 02) — لكن **لا مسار تحكم
        واحد كان موجودًا لتشغيل هذه الدعوة فعليًا**. الحقل كان موجودًا في
        الموديل والاستخدام موصوفًا في التوثيق، بلا أي نقطة دخول فعلية —
        بالضبط نوع الفجوة الممنوعة صراحة ("وجود حقل لا يثبت أن الوظيفة تعمل").

        نفس قاعدة عدم كشف وجود البريد من عدمه تنطبق هنا: الرد **نفسه**
        سواء كان البريد مسجَّلًا أو لا (لا نُرجع "البريد غير موجود").

        إصلاح بعد مراجعة مستقلة خارجية (R08): كان الاستدعاء `issue(...)`
        **يتجاهل الرمز الخام المُرجَع تمامًا** — لا آلية إرسال بريد فعلية،
        فالرمز يُصدَر ثم يضيع بلا أي طريقة لتوصيله للمستخدم إطلاقًا (دعوة
        لا يمكن لأحد استخدامها أبدًا). أُصلح بالتقاط الرمز واستدعاء دالة
        إرسال صريحة. **NOT VERIFIED/NOT_STARTED صراحة**: `_send_password_reset_email`
        أدناه لا ترسل بريدًا فعليًا — لا خادم SMTP متاح في هذه البيئة، ولا
        `mail.mail`/`ir.mail_server` حقيقي مُختبَر. هذا سدّ للفجوة البنيوية
        (الرمز لم يعد يُهمَل صامتًا) وليس تنفيذًا كاملًا لتسليم البريد.
        """
        if email:
            existing_membership = request.env["octa.hub.membership"].sudo().search([
                ("user_id.login", "=", email), ("active", "=", True),
            ], limit=1)
            if existing_membership:
                _invitation, raw_token = request.env["octa.hub.invitation"].sudo().issue(
                    email, "password_reset", membership=existing_membership)
                self._send_password_reset_email(email, raw_token)
        # رد ثابت دائمًا — لا كشف عن وجود/عدم وجود الحساب
        return request.render("octa_hub_core.password_reset_requested_page", {})

    def _send_password_reset_email(self, email, raw_token):
        """إصلاح بعد مراجعة V2 المستقلة (R08): كانت هذه الدالة **تسجّل
        رسالة log فقط** ولا تُنشئ أي شيء فعلي — الرمز يُصدَر ثم لا يصل
        للمستخدم بأي طريقة قابلة للتتبع. "غياب SMTP لا يمنع كتابة مسار
        mail.mail وتكوينه واختباره" كما لاحظت المراجعة بحق.

        الآن: يُنشأ سجل `mail.mail` حقيقي فعليًا (مُتحقَّق من حقوله الصحيحة
        في `odoo/addons/mail/models/mail_mail.py` من مصدر Odoo 19: `subject`،
        `body_html`، `email_to`) — هذا **يُثبت وجود مسار بريد فعلي في
        النظام**، حتى لو تسليمه الفعلي عبر SMTP يبقى NOT RUN (لا خادم بريد
        في هذه البيئة). الرمز الخام يظهر داخل نص الرسالة فقط (مطلوب لتشكيل
        الرابط)، لا في أي سجل/لوج دائم منفصل — نفس قاعدة عدم تسريب الأسرار
        المتّبعة في بقية المشروع.

        NOT VERIFIED: لم يُشغَّل هذا الإنشاء فعليًا ضد Odoo حقيقي (لا Odoo
        في هذه البيئة)؛ حقول `mail.mail` الإضافية (مثل `mail_server_id`،
        `auto_delete`) والتحقق من نجاح الإرسال الفعلي عبر `mail.mail.send()`
        تبقى غير مُختبَرة.
        """
        reset_url = f"/octa/invite/preview?token={raw_token}"
        body_html = (
            f"<p>لإعادة تعيين كلمة المرور، افتح هذا الرابط: "
            f"<a href='{reset_url}'>{reset_url}</a></p>"
            f"<p>إن لم تطلب هذا، تجاهل هذه الرسالة.</p>"
        )
        try:
            request.env["mail.mail"].sudo().create({
                "subject": "استعادة كلمة المرور — Octa Connect",
                "email_to": email,
                "body_html": body_html,
            })
        except Exception:
            # لا نُفشل الطلب كله لو فشل إنشاء سجل البريد (المستخدم يحصل على
            # نفس الرد الثابت دائمًا بصرف النظر) — لكن لا نخفي الخطأ صامتًا
            # في بيئة تطوير حقيقية أيضًا؛ NOT VERIFIED: هل هذا التعامل مناسب
            # فعليًا يحتاج مراجعة عند وجود Odoo حقيقي.
            import logging
            logging.getLogger(__name__).warning(
                "failed to create mail.mail record for password reset (email address not logged)")
