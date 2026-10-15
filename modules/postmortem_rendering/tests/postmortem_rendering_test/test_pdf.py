"""The postmortem printed: the same words as the page, in the same order, in a
file a reader keeps away from Argus.

Each case prints one postmortem and reads its text back, whitespace collapsed -
a line the PDF wrapped is still the line it was - and checks what the file says
rather than how it looks; where a link is the claim, where it lands.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChainStep,
    ChangeKind,
    CitedEvidence,
    ContributingFactor,
    Detection,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    Lessons,
    OpenedPullRequest,
    Postmortem,
    PostmortemLead,
    ResolutionStep,
    ReviewCriterion,
    TimelineEntry,
    TimelineMarker,
    Trigger,
)
from argus_testkit import Assertion, Scenario, all_of
from postmortem_rendering.pdf import as_pdf
from postmortem_rendering.rendering import render
from pypdf import PageObject, PdfReader

from postmortem_rendering_test.framework.builders import (
    a_marker,
    a_person_resolved_it,
    a_postmortem,
    an_alert,
)

SOME_ADDRESS = "http://argus.example/incidents/0b1c"
SOME_ONSET = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)


@pytest.mark.unit
def test_the_title_comes_first_then_every_section_in_the_page_s_order() -> None:
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(symptom=None, leads=[_a_lead("dont care")]),
                                    an_alert("HighErrorRate", "io-shop"), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_reads_in_order("HighErrorRate on io-shop", "Summary", "Impact",
                               "Root cause and contributing factors", "Hypotheses considered",
                               "Trigger", "Resolution", "Detection", "Action items",
                               "Lessons learned", "Timeline", "What people told Argus",
                               "Cost of the response", "Supporting information",
                               "Review checklist"))


@pytest.mark.unit
def test_every_section_says_what_the_document_holds() -> None:
    Scenario() \
        .given(
            some_rendered := render(_every_section_filled(), an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_reads_in_order("The divisor was never guarded.",
                               "Requests failed on the account page.", "Evidence:", "errors rose",
                               "Nothing reviewed the divisor.",
                               "monthly-spend flag went from OFF to ON",
                               "Turned the flag off",
                               "HighErrorRate fired at",
                               "Guard the divisor.",
                               "The alert fired at once.", "Nobody reviewed it.",
                               "It was a quiet hour.",
                               "The flag went on.",
                               "42 min", "12,345",
                               "Changes to production read (UTC)", "A deploy switched the model.",
                               "Log messages read (UTC)", "The divisor was zero.",
                               "The flag was the only change.",
                               "✓", "Key incident data collected",
                               "✗", "Document reviewed and shared"))


@pytest.mark.unit
def test_a_person_s_resolution_is_carried_into_the_head_and_the_resolution() -> None:
    # Read off the record each time the file is made, so a resolution reported
    # after the document was written is in the copy downloaded since.
    Scenario() \
        .given(
            some_events := [a_person_resolved_it("Kuki Buki", note="Turned it off by hand.")]
        ) \
        .when(
            lambda: as_pdf(render(a_postmortem(), an_alert(), some_events, SOME_ADDRESS))
        ) \
        .then(
            _it_reads_in_order("Ended by Kuki Buki", "Turned it off by hand.",
                               "Resolved by Kuki Buki", "Turned it off by hand."))


@pytest.mark.unit
def test_the_head_says_the_incident_s_window_in_utc() -> None:
    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(timeline=[a_marker(TimelineMarker.IMPACT_BEGINS, SOME_ONSET),
                                       a_marker(TimelineMarker.IMPACT_ENDS,
                                                SOME_ONSET + timedelta(minutes=9))]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says("Oct 11, 2026, 14:03 to 14:12 UTC"))


@pytest.mark.unit
def test_the_timeline_names_the_zone_its_times_are_in() -> None:
    # Its rows say a clock time alone, so the zone is said once, over them.
    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(timeline=[a_marker(TimelineMarker.IMPACT_BEGINS, SOME_ONSET)]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says("Timeline (UTC)"))


@pytest.mark.unit
def test_the_proposed_fix_and_the_incident_are_written_with_their_full_addresses() -> None:
    # Written out, for a reader of paper; and links, for a reader of the file.
    some_fix = OpenedPullRequest(number=7, url="https://github.com/acme/shop/pull/7",
                                 branch="dont care")

    Scenario() \
        .given(
            some_rendered := render(a_postmortem(pull_request=some_fix), an_alert(), [],
                                    SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _it_says_all(some_fix.url, SOME_ADDRESS),
            _it_links_out_to(some_fix.url, SOME_ADDRESS)))


@pytest.mark.unit
def test_a_label_the_prose_cites_leads_to_the_row_it_names() -> None:
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages",
                                           confidence=0.8, result="dont care", label="C7")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(executive_summary="Account pages failed, as C7 says.",
                             hypotheses=[some_hypothesis]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("C7 A flag change on account pages"))


@pytest.mark.unit
def test_a_citation_lands_on_its_row_in_every_table_that_has_one() -> None:
    # A step taken, an action item - the last of eighty, on a later page than
    # the citation - and a line of the timeline.
    some_items = [ActionItem(number=f"AI-{number}", text=f"Item {number}.",
                             type=ActionItemType.PROCESS, owner=None, tracking=None,
                             status=ActionItemStatus.OPEN)
                  for number in range(1, 81)]
    some_step = ResolutionStep(at=SOME_ONSET, action="Turned the flag off", by="Argus",
                               reversible=True, outcome="dont care", label="M1")
    some_line = TimelineEntry(at=SOME_ONSET, who=None, text="The flag went on.", label="T1")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(executive_summary="M1, AI-80 and T1 tell it.",
                             resolution=[some_step], action_items=some_items,
                             timeline=[some_line]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _a_link_lands_on("Turned the flag off"),
            _a_link_lands_on("AI-80 Item 80."),
            _a_link_lands_on("The flag went on.")))


@pytest.mark.unit
def test_a_change_a_log_message_and_a_lead_the_prose_cites_lead_to_their_rows() -> None:
    # The three kinds with no table of their own: the changes and log messages
    # read are rows of Supporting information, and a lead an item of What
    # people told Argus.
    some_change = CitedEvidence(label="P2", text="A deploy switched the model.")
    some_message = CitedEvidence(label="G3fa2", text="The divisor was zero.")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(root_cause="P2, G3fa2 and L1 tell it.",
                             changes_read=[some_change], log_messages_read=[some_message],
                             leads=[_a_lead("dont care", text="The flag was flipped.")]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _a_link_lands_on("P2 A deploy switched the model."),
            _a_link_lands_on("G3fa2 The divisor was zero."),
            _a_link_lands_on("The flag was flipped.")))


@pytest.mark.unit
def test_the_items_a_contributing_factor_names_lead_to_their_rows() -> None:
    some_factor = ContributingFactor(text="Nothing reviewed the divisor.", addressed_by=["AI-1"])
    some_item = ActionItem(number="AI-1", text="Guard the divisor.", type=ActionItemType.PREVENT,
                           owner=None, tracking=None, status=ActionItemStatus.OPEN)

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(contributing_factors=[some_factor], action_items=[some_item]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("AI-1 Guard the divisor."))


@pytest.mark.unit
def test_a_label_an_action_item_cites_leads_to_the_row_it_names() -> None:
    # The item is written into its cell run by run, so its citation can be a
    # link, and still says every word of the item.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages",
                                           confidence=0.8, result="dont care", label="C7")
    some_item = ActionItem(number="AI-1", text="Guard the divisor C7 found unguarded.",
                           type=ActionItemType.PROCESS, owner=None, tracking=None,
                           status=ActionItemStatus.OPEN)

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(hypotheses=[some_hypothesis], action_items=[some_item]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _a_link_lands_on("C7 A flag change on account pages"),
            _it_says("AI-1 Guard the divisor C7 found unguarded.")))


@pytest.mark.unit
def test_an_action_item_too_long_for_one_line_wraps_inside_its_cell() -> None:
    # Written in by hand rather than by the table, so it has to break where the
    # table would have - with its citation, on the last line, still a link.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages",
                                           confidence=0.8, result="dont care", label="C7")
    some_item = ActionItem(number="AI-1",
                           text="Add a deploy-time check that every scrape selector still "
                                "names a port the service exposes, so a rename fails the "
                                "rollout instead of silently blinding monitoring, as C7 warned.",
                           type=ActionItemType.PREVENT, owner=None, tracking=None,
                           status=ActionItemStatus.OPEN)

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(hypotheses=[some_hypothesis], action_items=[some_item]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _set_lower_than("warned.", "Add a deploy-time check"),
            _a_link_lands_on("C7 A flag change on account pages")))


@pytest.mark.unit
def test_money_is_printed_to_the_cent_with_its_currency() -> None:
    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(impact=Impact(duration=timedelta(minutes=9),
                                           extent=ImpactExtent.MEASURED, peak_error_rate=0.2),
                             customer_loss_estimate=Decimal("1736.68485900091116011163646"),
                             estimate_currency="usd"),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says("1,736.68 USD"))


@pytest.mark.unit
def test_an_em_dash_and_a_name_in_cyrillic_are_printed_as_written() -> None:
    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(executive_summary="Account pages failed — all of them.",
                             leads=[_a_lead("Иван Петров")]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(_it_says_all("Account pages failed — all of them.",
                          "Иван Петров"))


@pytest.mark.unit
def test_a_character_no_font_carries_does_not_stop_the_rest_being_printed() -> None:
    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(leads=[_a_lead("dont care", text="看 the checkout flag")]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says("the checkout flag"))


@pytest.mark.unit
def test_a_table_running_onto_another_page_names_its_columns_there_too() -> None:
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(action_items=_eighty_items()), an_alert(), [],
                                    SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _the_page_with("AI-80", also_says="Tracking"))


@pytest.mark.unit
def test_every_page_names_the_incident_it_belongs_to() -> None:
    # A page separated from the rest can still be traced to its incident.
    some_postmortem = a_postmortem(action_items=_eighty_items())

    Scenario() \
        .given(
            some_rendered := render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _every_page_says(some_postmortem.incident_id))


@pytest.mark.unit
def test_every_page_says_which_page_of_how_many_it_is() -> None:
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(action_items=_eighty_items()), an_alert(), [],
                                    SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _every_page_numbered())


@pytest.mark.unit
def test_a_title_too_long_for_the_running_header_is_shortened_there() -> None:
    # The header is one line, and the incident's ID at its end is the part a
    # page separated from the rest is traced by.
    some_postmortem = a_postmortem(
        symptom="Account pages failed for every shopper in every region while the monthly "
                "spend summary divided by a total nobody had guarded against being zero",
        action_items=_eighty_items())

    Scenario() \
        .given(
            some_rendered := render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _the_second_page_says("…", some_postmortem.incident_id))


@pytest.mark.unit
def test_the_first_page_carries_argus_s_mark_and_no_other_does() -> None:
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(action_items=_eighty_items()), an_alert(), [],
                                    SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _only_the_first_page_has_an_image())


def _a_lead(person_name: str, text: str = "dont care") -> PostmortemLead:
    return PostmortemLead(label="L1", person_id="dont care", person_name=person_name,
                          text=text, written_at=SOME_ONSET, weighing=None, effect=None)


def _eighty_items() -> list[ActionItem]:
    """Enough action items to run their table onto another page."""
    return [ActionItem(number=f"AI-{number}", text="dont care", type=ActionItemType.PROCESS,
                       owner=None, tracking=None, status=ActionItemStatus.OPEN)
            for number in range(1, 81)]


def _every_section_filled() -> Postmortem:
    """A postmortem with something in every section, each worded so it can be
    found in the file and nowhere else in it."""
    return a_postmortem(
        root_cause="The divisor was never guarded.",
        causal_chain=[ChainStep(text="Requests failed on the account page.",
                                cites=[CitedEvidence(label="T1", text="errors rose")])],
        contributing_factors=[ContributingFactor(text="Nothing reviewed the divisor.",
                                                 addressed_by=["AI-1"])],
        trigger=Trigger(subject="monthly-spend", from_state="off", to_state="on",
                        changed_at=SOME_ONSET, kind=ChangeKind.FLAG_TOGGLE, actor="dana"),
        resolution=[ResolutionStep(at=SOME_ONSET + timedelta(minutes=5),
                                   action="Turned the flag off", by="Argus", reversible=True,
                                   outcome="recovered", label="M1")],
        detection=Detection(alerted_at=SOME_ONSET + timedelta(minutes=1), rule="HighErrorRate",
                            onset_at=SOME_ONSET, gap=timedelta(minutes=1)),
        action_items=[ActionItem(number="AI-1", text="Guard the divisor.",
                                 type=ActionItemType.PREVENT, owner=None, tracking=None,
                                 status=ActionItemStatus.OPEN)],
        lessons=Lessons(went_well=["The alert fired at once."],
                        went_wrong=["Nobody reviewed it."],
                        got_lucky=["It was a quiet hour."]),
        timeline=[TimelineEntry(at=SOME_ONSET, who="Argus", text="The flag went on.",
                                label="T1")],
        changes_read=[CitedEvidence(label="P1", text="A deploy switched the model.")],
        log_messages_read=[CitedEvidence(label="G3fa2", text="The divisor was zero.")],
        engineer_minutes=42,
        tokens_spent=12345,
        assumptions=["The flag was the only change."],
        review=[ReviewCriterion(criterion="Key incident data collected", met=True),
                ReviewCriterion(criterion="Document reviewed and shared", met=None)])


def _pages(pdf: bytes) -> list[str]:
    """Each page's text, its whitespace collapsed to single spaces."""
    return [re.sub(r"\s+", " ", page.extract_text())
            for page in PdfReader(io.BytesIO(pdf)).pages]


def _text(pdf: bytes) -> str:
    return " ".join(_pages(pdf))


def _it_says(expected: str) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        text = _text(pdf)

        if expected not in text:
            raise AssertionError(f"Expected the PDF to say [{expected}], and it reads: {text}")

        return True

    return assertion


def _it_says_all(*expected: str) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        text = _text(pdf)
        missing = [said for said in expected if said not in text]

        if missing:
            raise AssertionError(f"Expected the PDF to say {missing}, and it reads: {text}")

        return True

    return assertion


def _it_links_out_to(*expected: str) -> Assertion[bytes]:
    """Each address is a link out of the file, to itself."""
    def assertion(pdf: bytes) -> bool:
        linked = [link.get_object()["/A"]["/URI"]
                  for page in PdfReader(io.BytesIO(pdf)).pages
                  for link in page.get("/Annots", [])
                  if "/A" in link.get_object()]
        missing = [address for address in expected if address not in linked]

        if missing:
            raise AssertionError(f"Expected links out to {missing}, and the PDF links out "
                                 f"to {linked}.")

        return True

    return assertion


def _every_page_says(expected: str) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        pages = _pages(pdf)
        missing = [number for number, page in enumerate(pages, start=1) if expected not in page]

        if len(pages) < 2 or missing:
            raise AssertionError(f"Expected each of more than one page to say [{expected}]; "
                                 f"{len(pages)} pages, pages {missing} do not.")

        return True

    return assertion


def _every_page_numbered() -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        pages = _pages(pdf)
        unnumbered = [number for number, page in enumerate(pages, start=1)
                      if f"Page {number} of {len(pages)}" not in page]

        if len(pages) < 2 or unnumbered:
            raise AssertionError(f"Expected each of more than one page to say which page of "
                                 f"{len(pages)} it is; pages {unnumbered} do not.")

        return True

    return assertion


def _the_second_page_says(*expected: str) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        pages = _pages(pdf)
        second = pages[1] if len(pages) > 1 else ""
        missing = [said for said in expected if said not in second]

        if missing:
            raise AssertionError(f"Expected the second page to say {missing}, and it reads: "
                                 f"{second or 'no such page'}")

        return True

    return assertion


def _only_the_first_page_has_an_image() -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        imaged = [number for number, page in enumerate(PdfReader(io.BytesIO(pdf)).pages, start=1)
                  if page.images]

        if imaged != [1]:
            raise AssertionError(f"Expected an image on the first page alone, "
                                 f"got one on pages {imaged}.")

        return True

    return assertion


def _it_reads_in_order(*expected: str) -> Assertion[bytes]:
    """Each in turn, found after the one before - so a heading the title
    happens to contain is not mistaken for the heading itself."""
    def assertion(pdf: bytes) -> bool:
        text = _text(pdf)
        position = 0

        for said in expected:
            found = text.find(said, position)
            if found < 0:
                raise AssertionError(f"Expected [{said}] after position {position} in the "
                                     f"order {expected}, and the PDF reads: {text}")
            position = found + len(said)

        return True

    return assertion


def _a_link_lands_on(expected: str) -> Assertion[bytes]:
    """Some link inside the file lands where `expected` is set: the text in
    the band just under where it lands, whitespace collapsed, says it."""
    def assertion(pdf: bytes) -> bool:
        reader = PdfReader(io.BytesIO(pdf))
        landed_on = [_text_under(reader.pages[page], top) for page, top in _landings(reader)]

        if not any(expected in text for text in landed_on):
            raise AssertionError(f"Expected a link inside the PDF to land on [{expected}], "
                                 f"and its links land on {landed_on}.")

        return True

    return assertion


def _landings(reader: PdfReader) -> list[tuple[int, float]]:
    """Where each link inside the file lands: the page, and the height up it
    in points."""
    landings: list[tuple[int, float]] = []
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            link = annotation.get_object()
            if link.get("/Subtype") != "/Link" or "/Dest" not in link:
                continue
            # `[page /XYZ left top zoom]`, as fpdf2 writes a link inside the file.
            destination = link["/Dest"].get_object()
            page_number = reader.get_page_number(destination[0].get_object())
            if page_number is not None:
                landings.append((page_number, float(destination[3])))
    return landings


def _text_under(page: PageObject, top: float, depth: float = 20.0) -> str:
    """The text set between `top` and `depth` points under it - a row of a
    table, where `top` is the row's top edge."""
    pieces: list[str] = []

    def visit(text: str, cm: list[float], tm: list[float], *_: object) -> None:
        if top - depth <= _baseline(cm, tm) <= top + 2:
            pieces.append(text)

    page.extract_text(visitor_text=visit)
    return re.sub(r"\s+", " ", " ".join(pieces)).strip()


def _set_lower_than(later: str, earlier: str) -> Assertion[bytes]:
    """`later` is set on a line under the one `earlier` is set on, on the same
    page - so the words between them broke onto a line of their own."""
    def assertion(pdf: bytes) -> bool:
        heights: dict[str, list[float]] = {later: [], earlier: []}
        for page in PdfReader(io.BytesIO(pdf)).pages:

            def visit(text: str, cm: list[float], tm: list[float], *_: object) -> None:
                for said, found in heights.items():
                    if said in text:
                        found.append(_baseline(cm, tm))

            page.extract_text(visitor_text=visit)

        if not heights[later] or not heights[earlier] or \
                not min(heights[later]) < max(heights[earlier]):
            raise AssertionError(f"Expected [{later}] set below [{earlier}], got their "
                                 f"baselines at {heights[later]} and {heights[earlier]} "
                                 f"points up the page.")

        return True

    return assertion


def _baseline(cm: list[float], tm: list[float]) -> float:
    """How far up the page a piece of text sits, in points."""
    return tm[4] * cm[1] + tm[5] * cm[3] + cm[5]


def _the_page_with(marker: str, also_says: str) -> Assertion[bytes]:
    """Whichever case the layout sets it in: a table's headings are set in
    capitals, and the words are what is asked after."""
    def assertion(pdf: bytes) -> bool:
        pages = _pages(pdf)
        holding = [page for page in pages if marker in page]

        if len(pages) < 2:
            raise AssertionError(f"Expected the table to run onto another page, "
                                 f"and the PDF has {len(pages)}.")

        if not holding or also_says.casefold() not in holding[-1].casefold():
            raise AssertionError(f"Expected the page with [{marker}] to say [{also_says}], "
                                 f"and it reads: {holding[-1] if holding else 'no such page'}")

        return True

    return assertion
