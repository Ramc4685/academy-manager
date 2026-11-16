## backend/v2/contexts/crm/README.md

L9 items only (pre-existing drift is out of this lane's scope).

- [undocumented] `application/use_cases/submit_website_inquiry.py` (`SubmitWebsiteInquiry`, `WebsiteInquiryResult`, `RepeatInquiryWriter`): the public form's validation and write entry point is absent from the Layout table.
- [undocumented] `domain/models.py` constants `clean_attribution`, `ATTRIBUTION_FIELDS`, `MAX_ATTRIBUTION_LEN`, `REPEAT_INQUIRY_AFTER` are not named; the record table and Semantics section describe their rules.
