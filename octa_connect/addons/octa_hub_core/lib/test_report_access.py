"""اختبارات RUN فعليًا لإعادة فحص صلاحيات المستندات المجمّعة (القسم 6)."""
import pytest
from report_access import (
    GeneratedReport, PermissionCheckPoint, ReportAccessDeniedError,
    check_report_access_or_raise, generate_report_with_access_check,
)


def test_branch_manager_downloading_multi_branch_report_is_denied_exact_required_scenario():
    """السيناريو المطلوب حرفيًا في شروط التسليم: 'محاولة مستخدم فرع تنزيل
    تقرير يشمل فروعًا غير مصرح بها'. مدير فرع 'فرع-1' فقط يحاول تنزيل تقرير
    يغطي 'فرع-1' و'فرع-2' معًا — يُرفَض، رغم أنه ربما 'اختار فرعه' في الواجهة."""
    report = GeneratedReport(report_id="rep-multi", covered_branch_ids=frozenset({"فرع-1", "فرع-2"}),
                              generated_by_user_id=99)
    branch_manager_access = {42: {"فرع-1"}}  # المستخدم 42 مخوَّل لفرع-1 فقط
    with pytest.raises(ReportAccessDeniedError) as exc:
        check_report_access_or_raise(report, user_id=42, user_branch_access=branch_manager_access,
                                      checkpoint=PermissionCheckPoint.DOWNLOAD)
    assert "فرع-2" in str(exc.value)


def test_single_branch_report_matching_user_access_succeeds():
    report = GeneratedReport(report_id="rep-single", covered_branch_ids=frozenset({"فرع-1"}),
                              generated_by_user_id=99)
    check_report_access_or_raise(report, user_id=42, user_branch_access={42: {"فرع-1"}},
                                  checkpoint=PermissionCheckPoint.DOWNLOAD)  # لا استثناء


def test_generation_itself_is_denied_not_only_download_no_silent_partial_report():
    """التوليد نفسه يُرفَض فورًا لو تجاوز نطاق المستخدم — لا مستند جزئي
    صامت يُسقط الفروع غير المصرح بها بهدوء."""
    with pytest.raises(ReportAccessDeniedError):
        generate_report_with_access_check(
            requested_branch_ids={"فرع-1", "فرع-2"}, user_id=42,
            user_branch_access={42: {"فرع-1"}})


def test_permission_revoked_between_generation_and_download_is_caught_at_download():
    """القبول حرفيًا: 'أعد فحص الصلاحيات عند توليد التقرير وعند تنزيله' —
    فحصان مستقلان فعليًا، لا فحص واحد يُعاد استخدام نتيجته. يثبت هذا
    باختبار: التوليد نجح وقت كانت الصلاحية موجودة، ثم أُلغيت (سُحبت عضوية
    الفرع)، فيُرفَض التنزيل رغم أن التوليد نفسه نجح سابقًا."""
    user_access_at_generation_time = {42: {"فرع-1", "فرع-2"}}
    report = generate_report_with_access_check(
        requested_branch_ids={"فرع-1", "فرع-2"}, user_id=42,
        user_branch_access=user_access_at_generation_time)

    # لاحقًا: صلاحية فرع-2 سُحبت (تعديل عضوية، تفويض شريك انتهى، إلخ)
    user_access_at_download_time = {42: {"فرع-1"}}
    with pytest.raises(ReportAccessDeniedError):
        check_report_access_or_raise(report, user_id=42, user_branch_access=user_access_at_download_time,
                                      checkpoint=PermissionCheckPoint.DOWNLOAD)


def test_selecting_own_branch_in_ui_does_not_expand_access_to_multi_branch_document():
    """يثبت الجملة الحرفية في المتطلب: 'المستند الذي يشمل عدة فروع لا يصبح
    متاحًا لمدير فرع لمجرد اختيار فرعه في الواجهة' — التقرير مُولَّد أصلًا
    ليغطي فرعين، اختيار المستخدم لفرعه في الواجهة (لو حاول لاحقًا) لا يُنشئ
    نسخة مقيَّدة تلقائيًا؛ نفس المستند بنفس النطاق يبقى مرفوضًا له."""
    report = GeneratedReport(report_id="rep-x", covered_branch_ids=frozenset({"فرع-1", "فرع-2", "فرع-3"}),
                              generated_by_user_id=1)
    with pytest.raises(ReportAccessDeniedError):
        check_report_access_or_raise(report, user_id=42, user_branch_access={42: {"فرع-1"}},
                                      checkpoint=PermissionCheckPoint.DOWNLOAD)
