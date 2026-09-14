"""Structure-preserving eForms and legacy reader. No optional field is invented."""

import re

from defusedxml import ElementTree as ET

from app.requirements import extract


def parse_xml(data, publication=None):
    from app.ted import source_datetime

    if len(data) > 25 * 1024 * 1024:
        raise ValueError("XML size limit exceeded")
    root = ET.fromstring(data)

    def name(n):
        return n.tag.rsplit("}", 1)[-1]

    def children(n, tag):
        return [c for c in n if name(c) == tag]

    def desc(n, tags):
        return [c for c in n.iter() if name(c) in tags]

    def text(n):
        return " ".join(n.itertext()).strip()

    def find(n, tags):
        nodes = desc(n, tags)
        return text(nodes[0]) if nodes else None

    def direct(n, tag):
        nodes = children(n, tag)
        return text(nodes[0]) if nodes else None

    def attribute(n, tags, attr):
        nodes = desc(n, tags)
        return nodes[0].get(attr) if nodes else None

    def codes(n, tags, attr=None):
        return list(
            dict.fromkeys(v for c in desc(n, tags) if (v := (c.get(attr) if attr else text(c))))
        )

    def amount(n):
        nodes = desc(n, {"EstimatedOverallContractAmount", "VAL_ESTIMATED_TOTAL", "VAL_OBJECT"})
        if not nodes:
            return None, None
        try:
            return float(text(nodes[0])), nodes[0].get("currencyID") or nodes[0].get("CURRENCY")
        except ValueError:
            return None, None

    def deadline(n):
        periods = desc(n, {"TenderSubmissionDeadlinePeriod", "DEADLINE_RECEIPT_TENDERS"})
        if periods:
            return source_datetime(
                find(periods[0], {"EndDate", "DATE"}), find(periods[0], {"EndTime", "TIME"})
            )
        return source_datetime(find(n, {"DATE_RECEIPT_TENDERS"}), find(n, {"TIME_RECEIPT_TENDERS"}))

    legacy = "}" not in root.tag
    identity = direct(root, "ID") or find(root, {"NOTICE_ID", "NO_DOC_OJS"}) or publication
    if not identity:
        raise ValueError("Authoritative notice identifier missing")
    publication = publication or find(root, {"NoticePublicationID", "NO_DOC_OJS"}) or identity
    projects = children(root, "ProcurementProject") or desc(root, {"OBJECT_CONTRACT"})
    project = projects[0] if projects else root
    buyer_nodes = desc(root, {"ContractingParty", "CONTRACTING_BODY"})
    buyer_node = buyer_nodes[0] if buyer_nodes else root
    value, currency = amount(project)
    title = direct(project, "Name") or find(project, {"TITLE"}) or "Untitled procurement notice"
    lots, requirements = [], []
    containers = desc(root, {"ProcurementProjectLot", "OBJECT_DESCR"})
    parent_map = {child: parent for parent in root.iter() for child in parent}

    def lot_of(node):
        while node in parent_map:
            node = parent_map[node]
            if name(node) in {"ProcurementProjectLot", "OBJECT_DESCR"}:
                return direct(node, "ID") or find(node, {"LOT_NO"}) or node.get("ITEM")
        return None

    for i, node in enumerate(containers):
        lot_id = direct(node, "ID") or find(node, {"LOT_NO"}) or node.get("ITEM") or str(i + 1)
        lot_value, lot_currency = amount(node)
        lots.append(
            {
                "id": lot_id,
                "title": find(node, {"Name", "TITLE"}) or f"Lot {lot_id}",
                "deadline": deadline(node),
                "value": lot_value,
                "currency": lot_currency,
                "requirements_complete": False,
                "languages": codes(node, {"LanguageID"}),
                "duration": find(node, {"DurationMeasure", "DURATION"}),
                "renewal_options": find(node, {"Renewal", "RENEWAL"}),
                "award_criteria": [
                    text(c) for c in desc(node, {"AwardingCriterion", "AC_QUALITY", "AC_PRICE"})
                ],
            }
        )
    criterion_tags = {
        "SelectionCriteria",
        "ExclusionGrounds",
        "ECONOMIC_FINANCIAL_INFO",
        "TECHNICAL_PROFESSIONAL_INFO",
        "SUITABILITY",
    }
    for i, node in enumerate(desc(root, criterion_tags)):
        descriptions = children(node, "Description")
        source_text = "\n".join(text(n) for n in descriptions) if descriptions else text(node)
        req = extract(source_text, f"XML/{name(node)}[{i + 1}]", lot_of(node))
        if any(n.get("languageID", "ENG").upper() != "ENG" for n in descriptions):
            req.ambiguous, req.verification_state, req.confidence = True, "REVIEW_REQUIRED", 0.4
        if name(node) == "ExclusionGrounds":
            req.category = "EXCLUSION"
        requirements.append(req.model_dump())
    deadlines = list(dict.fromkeys(lot["deadline"] for lot in lots if lot["deadline"]))
    overall_deadline = deadlines[0] if len(deadlines) == 1 else deadline(root) if not lots else None
    changed = find(root, {"ChangedNoticeIdentifier", "ChangeNoticeVersionID"})
    # Explicitly only known cancellation signals, not arbitrary occurrences of 'cancelled'.
    cancelled = (
        find(root, {"ProcedureCancelledIndicator", "CompetitionTerminatedIndicator"}) == "true"
    )
    buyer = find(buyer_node, {"RegistrationName", "OFFICIALNAME"})
    return {
        "source_id": identity,
        "source_version": direct(root, "VersionID") or "1",
        "publication_number": publication,
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{publication}",
        "title": title,
        "description": direct(project, "Description") or find(project, {"SHORT_DESCR"}) or "",
        "buyer": buyer or "Not provided",
        "buyer_identifiers": codes(buyer_node, {"CompanyID"}),
        "buyer_type": find(buyer_node, {"ContractingPartyTypeCode"}),
        "country": find(buyer_node, {"IdentificationCode"})
        or attribute(buyer_node, {"COUNTRY"}, "VALUE")
        or "",
        "cpv_codes": codes(project, {"ItemClassificationCode"})
        or codes(project, {"CPV_CODE"}, "CODE"),
        "nuts_codes": codes(project, {"CountrySubentityCode"}) or codes(project, {"NUTS"}, "CODE"),
        "value": value,
        "currency": currency,
        "deadline": overall_deadline,
        "published": (direct(root, "IssueDate") or find(root, {"DATE_PUBLICATION"}) or "")[:10],
        "notice_type": find(root, {"NoticeTypeCode"}),
        "procedure": find(root, {"ProcedureCode", "PT_OPEN"}),
        "procedure_identifier": find(root, {"ContractFolderID"}),
        "status": "CANCELLED"
        if cancelled
        else "AWARDED"
        if name(root) == "ContractAwardNotice"
        else "ACTIVE",
        "lots": lots,
        "requirements": requirements,
        "requirements_complete": False,
        "languages": codes(root, {"LanguageID"}),
        "official_languages": codes(root, {"NoticeLanguageCode"}),
        "submission_method": find(root, {"SubmissionMethodCode"}),
        "document_links": [u for u in codes(root, {"URI"}) if re.match(r"^https://", u)],
        "duration": find(project, {"DurationMeasure"}),
        "renewal_options": find(project, {"Renewal"}),
        "framework": bool(desc(root, {"FrameworkAgreement"})),
        "award_information": [
            {
                "value": find(n, {"PayableAmount"}),
                "currency": attribute(n, {"PayableAmount"}, "currencyID"),
                "supplier": find(n, {"RegistrationName"}),
            }
            for n in desc(root, {"AwardedTenderedProject"})
        ],
        "change_reference": changed,
        "source_format": "LEGACY_XML" if legacy else "EFORMS_XML",
        "parser_confidence": 0.8,
        "completeness_score": 70 if requirements else 45,
        "extraction_warnings": [
            "Full dossier review required. Unsupported clauses, languages, missing values and unassociated lots remain UNKNOWN."
        ],
    }
