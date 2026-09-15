"""
إعادة فحص الصلاحيات عند توليد وتنزيل المستندات المجمّعة (القسم 6، مراجعة
بوابة هنقرستيشن) — سيناريو الاختبار المطلوب حرفيًا في شروط التسليم:
"محاولة مستخدم فرع تنزيل تقرير يشمل فروعًا غير مصرح بها".

المبدأ: مستند تقرير مُولَّد يحمل **نطاق الفروع الذي وُلِّد من أجله** كبيانات
ملازمة له، مستقلة عن اختيار المستخدم الحالي في الواجهة وقت التوليد. اختيار
فرع واحد في الواجهة لا يعني أن المستند النهائي (PDF/Excel) لا يحتوي بيانات
فروع أخرى فعليًا لو كان طلب التوليد الأصلي (قبل أي تلاعب) يغطي أكثر من فرع
— لذلك يُعاد فحص الصلاحية **مرتين مستقلتين**: عند التوليد، وعند التنزيل،
لا عند التوليد فقط بافتراض أن التنزيل اللاحق آمن تلقائيًا.
"""
from __future__ import annotations

import dataclasses
import enum


class PermissionCheckPoint(str, enum.Enum):
    GENERATION = "generation"
    DOWNLOAD = "download"


class ReportAccessDeniedError(Exception):
    def __init__(self, user_id, checkpoint: PermissionCheckPoint, unauthorized_branch_ids):
        super().__init__(
            f"user {user_id} denied access to report at {checkpoint.value}: "
            f"unauthorized branches {sorted(unauthorized_branch_ids)}"
        )
        self.user_id = user_id
        self.checkpoint = checkpoint
        self.unauthorized_branch_ids = unauthorized_branch_ids


@dataclasses.dataclass(frozen=True)
class GeneratedReport:
    """مستند مُولَّد — يحمل نطاق الفروع الفعلي الذي شمله التوليد، بصرف النظر
    عمّا اختاره المستخدم في الواجهة لاحقًا أو حتى وقت الطلب."""
    report_id: str
    covered_branch_ids: frozenset
    generated_by_user_id: int


def _authorized_branch_ids_for_user(user_id, user_branch_access: dict) -> set:
    """user_branch_access: محاكاة استعلام صلاحيات المستخدم الفعلي (في Odoo
    الحقيقي: عبر membership/record rules) — هنا كقاموس مُحقَن للاختبار."""
    return set(user_branch_access.get(user_id, set()))


def check_report_access_or_raise(report: GeneratedReport, user_id, user_branch_access: dict,
                                  checkpoint: PermissionCheckPoint) -> None:
    """يُستدعى مرتين مستقلتين فعليًا (لا مرة واحدة يُعاد استخدام نتيجتها):
    مرة عند طلب التوليد، ومرة عند طلب التنزيل — لأن صلاحيات المستخدم قد
    تتغيّر بينهما (سُحبت عضوية فرع، أُلغي تفويض شريك، إلخ)."""
    authorized = _authorized_branch_ids_for_user(user_id, user_branch_access)
    unauthorized = report.covered_branch_ids - authorized
    if unauthorized:
        raise ReportAccessDeniedError(user_id, checkpoint, unauthorized)


def generate_report_with_access_check(requested_branch_ids: set, user_id, user_branch_access: dict) -> GeneratedReport:
    """توليد التقرير نفسه يُرفَض فورًا لو تضمّن الطلب فرعًا واحدًا خارج نطاق
    المستخدم — لا يُولَّد مستند جزئي صامت يُسقط الفروع غير المصرح بها، لأن
    هذا قد يوهم بأن البيانات المعروضة كاملة رغم أنها ناقصة بصمت."""
    report = GeneratedReport(report_id="rep-1", covered_branch_ids=frozenset(requested_branch_ids),
                              generated_by_user_id=user_id)
    check_report_access_or_raise(report, user_id, user_branch_access, PermissionCheckPoint.GENERATION)
    return report
