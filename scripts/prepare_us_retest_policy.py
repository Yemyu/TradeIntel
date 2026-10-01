"""Prepare an isolated disabled CBP document; never confirm on a user's behalf."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

from tradeintel_ai.announcement_flow import candidate_template, save_announcement_store, load_announcement_store
from tradeintel_ai.policy_documents import build_document, build_document_store
from tradeintel_ai.policy_search import set_required_dependencies
from scripts.run_us_agent_retest import GateError, write_new
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS, build_candidates

SOURCE_SHA = "be5b9ba0e9091e171731c878ed4d7e1bf57d210565631883212787982fe9f6f9"
POLICY_ID = "us_301_review2025_tungsten_solar"


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def normalize(text):
    return " ".join(text.split())


def review_candidate(store):
    """Propose fields with verbatim quotes; never manufacture confirmation."""
    document = store["documents"][0]
    sections = {section["id"]: section["text"] for section in document["sections"]}
    version = document["doc_version"]
    def known(name, value, ids):
        return {"field": name, "status": "known", "value": value,
                "evidence": [{"doc_version": version, "section_id": name,
                              "quote": sections[name]} for name in ids]}
    p8 = ["cbp63577329:p8:para1"]
    origins = ["cbp63577329:p9:para1", "cbp63577329:p12:para1"]
    goods = ["cbp63577329:p9:para2", "cbp63577329:p9:para3",
             "cbp63577329:p12:para2", "cbp63577329:p12:para3", "cbp63577329:p12:para4"]
    fields = [known("effective_date", "2025-01-01", p8),
              known("clock_24h", "00:01", p8), known("timezone", "EST", p8),
              known("entry_events", ["entered for consumption", "withdrawn from warehouse for consumption"], p8),
              known("origin", "China", origins),
              known("hts_codes", [{"code": code, "precision": "text_limited"} for code in
                    ("28046100", "38180000", "81019400", "81019910", "81019980")], goods),
              known("rates", [{"hts8": ["28046100", "38180000"], "additional_percent": 50},
                              {"hts8": ["81019400", "81019910", "81019980"], "additional_percent": 25}], origins),
              known("rate_meaning", "archived additional duty, not current total tariff", origins),
              known("conditions", [sections[name] for name in goods], goods)]
    for name in REQUIRED_FIELDS:
        if not any(field["field"] == name for field in fields):
            fields.append({"field": name, "status": "unknown", "value": None,
                           "reason": "已登记p8/p9/p12未完整提供该字段；不代表整份公告或其他法规不存在。"})
    return build_candidates(fields, store, allowed_statuses=("disabled",))


def prepare_policy(project, runtime):
    target = runtime / ".local/announcement-docs" / (POLICY_ID + ".json")
    if target.exists() or (runtime / "policy-review.json").exists():
        raise GateError("Policy preparation exists; refusing overwrite")
    raw = (project / "data/raw/policy/review2025/cbp-63577329.html").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise GateError("Official source hash changed")
    parser = VisibleText()
    parser.feed(raw.decode("utf-8"))
    original = normalize("".join(parser.parts))
    corpus = json.loads((project / "data/processed/policy_exposure/policy_corpus.json").read_text())
    chunks = corpus["chunks"]
    if {chunk["id"] for chunk in chunks} != {"cbp63577329:p8", "cbp63577329:p9", "cbp63577329:p12"}:
        raise GateError("Unexpected registered source set")
    for chunk in chunks:
        if chunk["sha256"] != SOURCE_SHA:
            raise GateError("Corpus source identity changed")
        # Each registered line must be present in the archived official HTML.
        for line in chunk["text"].splitlines():
            if normalize(line) not in original:
                raise GateError("Registered text absent from official HTML: " + chunk["id"])
    document = build_document({"policy_id": POLICY_ID, "data_version": "us-retest-cbp-20261001",
        "sources": [{"id": c["id"], "url": c["url"], "text": c["text"],
                     "document_sha256": SOURCE_SHA} for c in chunks]},
        doc_id="cbp63577329", publication_time="2024-12-31", status="disabled")
    set_required_dependencies(document, {
        "effective_date": {"status": "known", "section_ids": ["cbp63577329:p8:para1"],
                           "evidence": "Archived effective-date and entry-event sentence"},
        "origin": {"status": "known", "section_ids": ["cbp63577329:p9:para1", "cbp63577329:p12:para1"],
                   "evidence": "Both source paragraphs say products of China"},
        "conditions": {"status": "known", "section_ids": ["cbp63577329:p9:para2", "cbp63577329:p9:para3", "cbp63577329:p12:para2",
                          "cbp63577329:p12:para3", "cbp63577329:p12:para4"],
                       "evidence": "Registered commodity descriptions and qualifications"},
        "exceptions": {"status": "verified_absent", "note": "Only indexed p8/p9/p12; not a claim about all regulations",
                       "evidence": "No exception provision in these registered fragments"}})
    store = build_document_store([document], policy_id=POLICY_ID,
        data_version=document["data_version"], limitations=[
            "仅登记p8/p9/p12；不包含附件、其他段落、后续修订或现行综合税率。",
            "候选尚未人工确认，不进入Agent检索。"])
    template = candidate_template(store, document["doc_version"])
    save_announcement_store(runtime, POLICY_ID, store)
    write_new(runtime / "policy-review.json", {
        "status": "disabled_pending_confirmation", "source_sha256": SOURCE_SHA,
        "doc_version": document["doc_version"], "template": template,
        "boundary": "This template is not an accepted candidate or human confirmation."})
    return {"status": "disabled_pending_confirmation", "doc_version": document["doc_version"],
            "verified_chunks": len(chunks), "api_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--candidate-only", action="store_true")
    args = parser.parse_args()
    if args.candidate_only:
        candidate = review_candidate(load_announcement_store(args.runtime, POLICY_ID))
        write_new(args.runtime / "policy-field-candidate.json", {
            "status": "proposed_not_submitted_or_confirmed", "candidate": candidate,
            "boundary": "Quotes matched; human semantic approval pending; document remains disabled"})
        print(json.dumps({"fields": len(candidate["fields"]), "known": sum(field["status"] == "known" for field in candidate["fields"]),
                          "enabled": False, "api_calls": 0}))
        return
    print(json.dumps(prepare_policy(args.project, args.runtime)))


if __name__ == "__main__":
    main()
