## backend/v2/contexts/crm/README.md

Scope of this pass: the not-billed change (README:440-446 against `family_index.py`, `people_reports.py`, `ports.py` and the read models) plus a recheck of the earlier L9 findings. The rest of the 966-line README was not re-audited line by line. The not-billed text matches the code: `FamilyChild.not_billed`, `FamilyIndexSummary.not_billed_families`, `RiskStudent.not_billed` and `AttendanceRisk.not_billed` all exist.

- [undocumented] `application/use_cases/submit_website_inquiry.py` (`SubmitWebsiteInquiry`, `WebsiteInquiryResult`, `RepeatInquiryWriter`) is not in the Layout table. README:134 mentions `SubmitWebsiteInquiry` in prose only.
- [undocumented] `domain/models.py:90,92` constants `MAX_ATTRIBUTION_LEN` and `ATTRIBUTION_FIELDS` are not named. README:62 and :255 give the rule (80 chars, `clean_attribution`).
- [undocumented] README:440-446 describes `not_billed_families` and the at-risk `not_billed` count. It does not mention the `ChildLifecycle.not_billed` port property (`application/ports.py:85-86`). It also does not mention `FamilyChild.not_billed` (`domain/family_index.py:47`), which the Layout and domain sections would need to list for the new field.
