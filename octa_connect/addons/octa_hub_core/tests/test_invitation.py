# -*- coding: utf-8 -*-
"""اختبارات دورة الدعوة — NOT RUN (لا Odoo متاح). انظر ملاحظة الصدق في
test_isolation.py أعلى الملف؛ نفس الشرط ينطبق هنا."""
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestInvitationLifecycle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.admin = self.env["res.users"].create({
            "name": "Identity Admin", "login": "ia@test.local",
        })
        # إصلاح بعد تشغيل فعلي حقيقي: كان الإعداد هنا يمنح `group_ids`
        # مباشرة، متجاوزًا نموذج octa.hub.membership كليًا — لكن فحص
        # invitation.py::create() الأمني يتحقق من **سجل عضوية فعلي**
        # (مصدر الحقيقة للأدوار)، لا من مجموعة Odoo مباشرة. مستخدم بمجموعة
        # ممنوحة يدويًا بلا عضوية فعلية كان يُرفَض بحق من invitation.py —
        # هذا سلوك أمني صحيح اكتشفناه بالتشغيل الفعلي، والخطأ كان في إعداد
        # الاختبار نفسه لا في الكود المُختبَر. أُصلح بإنشاء عضوية فعلية،
        # التي تُزامن المجموعة تلقائيًا الآن (إصلاح membership.py في نفس
        # الجلسة) — يُحاكي التدفق الحقيقي لتعيين أول مدير هوية.
        self.env["octa.hub.membership"].create({
            "user_id": self.admin.id, "party_type": "octatech",
            "role_code": "octatech_identity_admin", "granted_by_user_id": self.env.user.id,
        })

    def test_issue_then_consume_once(self):
        Invitation = self.env["octa.hub.invitation"].with_user(self.admin)
        rec, raw_token = Invitation.issue("new_owner@test.local", "initial_invite", created_by_user=self.admin)
        consumed = rec.consume(raw_token)
        self.assertTrue(consumed.consumed_at)

    def test_second_consume_of_same_token_fails(self):
        Invitation = self.env["octa.hub.invitation"].with_user(self.admin)
        rec, raw_token = Invitation.issue("x@test.local", "initial_invite", created_by_user=self.admin)
        rec.consume(raw_token)
        with self.assertRaises(ValidationError):
            rec.consume(raw_token)

    def test_reissue_invalidates_previous_token(self):
        Invitation = self.env["octa.hub.invitation"].with_user(self.admin)
        _rec1, raw_token_1 = Invitation.issue("y@test.local", "initial_invite", created_by_user=self.admin)
        _rec2, _raw_token_2 = Invitation.issue("y@test.local", "initial_invite", created_by_user=self.admin)
        with self.assertRaises(ValidationError):
            Invitation.consume(raw_token_1)

    def test_expired_token_is_rejected(self):
        Invitation = self.env["octa.hub.invitation"].with_user(self.admin)
        rec, raw_token = Invitation.issue("z@test.local", "initial_invite", created_by_user=self.admin)
        rec.write({"expires_at": "2000-01-01 00:00:00"})
        with self.assertRaises(ValidationError):
            rec.consume(raw_token)

    def test_preview_does_not_consume(self):
        Invitation = self.env["octa.hub.invitation"].with_user(self.admin)
        rec, raw_token = Invitation.issue("w@test.local", "initial_invite", created_by_user=self.admin)
        info = rec.preview_only(raw_token)
        self.assertTrue(info["valid"])
        rec.invalidate_recordset()
        self.assertFalse(rec.consumed_at)  # GET وحدها لم تستهلك الرمز
