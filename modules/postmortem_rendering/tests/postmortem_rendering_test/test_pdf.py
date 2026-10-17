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
from pypdf.generic import ContentStream

from postmortem_rendering_test.framework.builders import (
    SOME_DEPLOYED_REVISION,
    SOME_REPOSITORY_ADDRESS,
    a_change_read,
    a_deploy_read,
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
                               "Requests failed on the account page.", "Evidence:",
                               "The flag went on.",
                               "Nothing reviewed the divisor.",
                               "monthly-spend flag went from OFF to ON",
                               "Turned the flag off",
                               "HighErrorRate fired at",
                               "Guard the divisor.",
                               "The alert fired at once.", "Nobody reviewed it.",
                               "It was a quiet hour.",
                               "The flag went on.",
                               "42 min", "12,345",
                               "Changes to production read", "A deploy switched the model.",
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
@pytest.mark.parametrize("marker", list(TimelineMarker),
                         ids=lambda marker: marker.value.replace(" ", "-"))
def test_every_marker_is_printed_on_one_line(marker: TimelineMarker) -> None:
    # A marker is what a reader runs down the timeline looking for, and one
    # broken over two lines reads as two.
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(timeline=[a_marker(marker, SOME_ONSET)]),
                                    an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _set_on_one_line(marker.value.upper()))


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
def test_a_change_read_links_out_to_its_commit_its_repository_and_its_directory() -> None:
    # The row says where the change came from, and a reader of the file opens
    # it there.
    Scenario() \
        .given(
            some_rendered := render(a_postmortem(changes_read=[a_deploy_read()]), an_alert(), [],
                                    SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_links_out_to(f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}",
                             SOME_REPOSITORY_ADDRESS,
                             f"{SOME_REPOSITORY_ADDRESS}/tree/{SOME_DEPLOYED_REVISION}/deploy"))


@pytest.mark.unit
def test_a_revision_the_prose_names_links_out_to_its_commit() -> None:
    # "The deploy of revision 7c3ca00": a reader of the file opens the commit
    # from the prose that names it, not only from the row listing the change -
    # which links it already, so the claim is one link more than without it.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"

    Scenario() \
        .given(
            unnamed := as_pdf(render(a_postmortem(root_cause="A deploy broke it.",
                                                  changes_read=[a_deploy_read()]),
                                     an_alert(), [], SOME_ADDRESS)),
            some_rendered := render(
                a_postmortem(root_cause=f"The deploy of revision {SOME_DEPLOYED_REVISION[:7]} "
                                        f"broke it.",
                             changes_read=[a_deploy_read()]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _one_more_link_out_to(commit, than=unnamed))


@pytest.mark.unit
def test_a_citation_of_what_the_alert_said_leads_to_its_row() -> None:
    some_detection = Detection(alerted_at=SOME_ONSET, rule="dont care", onset_at=None, gap=None,
                               said=CitedEvidence(label="AL1", text="240 totals are off"))

    Scenario() \
        .given(
            some_rendered := render(a_postmortem(root_cause="AL1 tells it.",
                                                 detection=some_detection),
                                    an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("AL1 240 totals are off"))


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
    some_change = a_change_read("P2", summary="A deploy switched the model.")
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
            _a_link_lands_on("A deploy switched the model."),
            _a_link_lands_on("G3fa2 The divisor was zero."),
            _a_link_lands_on("The flag was flipped.")))


@pytest.mark.unit
def test_what_a_deployment_changed_the_prose_cites_leads_to_its_row() -> None:
    # A diff is a row of Supporting information too, under the label the prose
    # cites it by.
    some_diff = CitedEvidence(label="D1", text="Deployment of revision some-revision.\n"
                                               "  -  model: v1\n"
                                               "  +  model: v2")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(root_cause="D1 tells it.", deployment_changes_read=[some_diff]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("D1 Deployment of revision some-revision."))


@pytest.mark.unit
def test_what_code_fix_read_the_prose_cites_leads_to_its_row() -> None:
    some_reading = CitedEvidence(label="F1", text="The categoriser does not lowercase.")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(root_cause="F1 tells it.", code_read=[some_reading]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("F1 The categoriser does not lowercase."))


@pytest.mark.unit
def test_a_row_taller_than_a_page_goes_on_onto_the_next_and_still_lands() -> None:
    # What Code-Fix read in the source has run to thirteen thousand characters:
    # a row no page holds. It goes on onto the next, and a citation of it still
    # lands where it begins.
    some_reading = CitedEvidence(label="F1",
                                 text="The categoriser does not lowercase. "
                                      + "It reads the vocabulary as written. " * 400)

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(root_cause="F1 tells it.", code_read=[some_reading]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("F1 The categoriser does not lowercase."))


@pytest.mark.unit
def test_a_hypothesis_taller_than_a_page_goes_on_onto_the_next_and_still_lands() -> None:
    # A cell of plain text, under a heading repeated on the page it goes on to.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages. "
                                                   + "It divided by zero. " * 700,
                                           confidence=0.8, result="confirmed", label="C1")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(root_cause="C1 was right.", hypotheses=[some_hypothesis]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("C1 A flag change on account pages."))


@pytest.mark.unit
def test_a_row_taller_than_a_page_keeps_every_line_and_every_link_it_had() -> None:
    # A deployment's diff, its revision named in its first line and its last -
    # a page apart. Each line is still there, and the revision opens from both.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"
    some_diff = CitedEvidence(label="D1", text="\n".join([
        f"Deployment of revision {SOME_DEPLOYED_REVISION}.",
        *(f"  +  key{line}: value" for line in range(150)),
        f"End of {SOME_DEPLOYED_REVISION}."]))
    without_the_diff = as_pdf(render(a_postmortem(changes_read=[a_deploy_read("P2")]),
                                     an_alert(), [], SOME_ADDRESS))

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(changes_read=[a_deploy_read("P2")],
                             deployment_changes_read=[some_diff]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(all_of(
            _it_says_all("key0: value", "key75: value", "key149: value"),
            _more_links_out_to(commit, more=2, than=without_the_diff)
        ))


@pytest.mark.unit
def test_a_row_taller_than_a_page_keeps_each_word_once_however_it_is_spaced() -> None:
    # A model can write a non-breaking space or a soft hyphen, which the PDF
    # prints as a plain space or not at all. A row cut across pages still keeps
    # every word it held, once each.
    some_words = [f"w{number:04d}" for number in range(700)]
    some_reading = CitedEvidence(
        label="F1", text=" ".join(f"{word}\u00a0ok hy\u00adphen" for word in some_words))

    Scenario() \
        .given(
            some_rendered := render(a_postmortem(code_read=[some_reading]),
                                    an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says_each_once(*some_words))


@pytest.mark.unit
def test_a_soft_hyphen_in_a_cited_line_is_not_printed() -> None:
    # A soft hyphen only says where a word may break. The font draws it as a
    # hyphen, so a line written into its cell character by character would
    # print one in the middle of the word.
    some_reading = CitedEvidence(label="F1", text="The two services co\u00adoperate.")

    Scenario() \
        .given(
            some_rendered := render(a_postmortem(code_read=[some_reading]),
                                    an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _it_says("The two services cooperate."))


@pytest.mark.unit
def test_an_item_the_chain_rests_on_leads_to_its_row() -> None:
    # Cited nowhere in the prose: the link is the chain's own.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages.",
                                           confidence=0.8, result="confirmed", label="C1")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(hypotheses=[some_hypothesis],
                             causal_chain=[ChainStep(text="dont care", cites=[
                                 CitedEvidence(label="C1", text="as briefed")])]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("C1 A flag change on account pages."))


@pytest.mark.unit
def test_a_revision_in_an_item_the_chain_rests_on_opens_its_commit() -> None:
    # Said the way the change's own row says it, the revision linked as there,
    # in the reference and in what the deploy did.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"
    without_the_chain = as_pdf(render(a_postmortem(changes_read=[a_deploy_read("P2")]),
                                      an_alert(), [], SOME_ADDRESS))

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(changes_read=[a_deploy_read("P2")],
                             causal_chain=[ChainStep(text="dont care", cites=[
                                 CitedEvidence(label="P2", text="as briefed")])]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _at_least_more_links_out_to(commit, more=2, than=without_the_chain))


@pytest.mark.unit
def test_a_candidate_a_line_of_the_timeline_names_leads_to_its_row() -> None:
    # The line that formed the candidates names them by label, and a reader of
    # the file follows each to what it was.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages",
                                           confidence=0.8, result="dont care", label="C7")
    some_line = TimelineEntry(at=SOME_ONSET, who="Investigator Agent",
                              text="Formed 1 candidate cause, best first: C7", label="T1")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(hypotheses=[some_hypothesis], timeline=[some_line]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("C7 A flag change on account pages"))


@pytest.mark.unit
def test_a_candidate_named_by_a_label_its_row_also_goes_by_leads_to_that_row() -> None:
    # The row stands for two candidates and is labelled with both, and a
    # reader following the second lands on it.
    some_hypothesis = HypothesisConsidered(summary="A flag change on account pages",
                                           confidence=0.8, result="dont care", label="C7",
                                           also=["C8"])
    some_line = TimelineEntry(at=SOME_ONSET, who="Investigator Agent",
                              text="Formed 2 candidate causes, best first: C8", label="T1")

    Scenario() \
        .given(
            some_rendered := render(
                a_postmortem(hypotheses=[some_hypothesis], timeline=[some_line]),
                an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _a_link_lands_on("C7, C8 A flag change on account pages"))


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
def test_no_cell_is_painted_over_the_words_written_into_it() -> None:
    # An action item's text is written into the cell the table leaves for it;
    # a table that then fills the cell paints the words out, and the column
    # reads empty while the file still holds every word of it.
    Scenario() \
        .given(
            some_rendered := render(_every_section_filled(), an_alert(), [], SOME_ADDRESS)
        ) \
        .when(
            lambda: as_pdf(some_rendered)
        ) \
        .then(
            _nothing_set_is_painted_over())


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
        changes_read=[a_change_read("P1", summary="A deploy switched the model.")],
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


def _it_says_each_once(*expected: str) -> Assertion[bytes]:
    """Each is said exactly once - none lost, none said twice."""
    def assertion(pdf: bytes) -> bool:
        text = _text(pdf)
        wrong = {said: text.count(said) for said in expected if text.count(said) != 1}

        if wrong:
            raise AssertionError(f"Expected each of {len(expected)} words said once, and "
                                 f"{len(wrong)} are not, by how often each is: {wrong}")

        return True

    return assertion


def _it_links_out_to(*expected: str) -> Assertion[bytes]:
    """Each address is a link out of the file, to itself."""
    def assertion(pdf: bytes) -> bool:
        linked = _links_out(pdf)
        missing = [address for address in expected if address not in linked]

        if missing:
            raise AssertionError(f"Expected links out to {missing}, and the PDF links out "
                                 f"to {linked}.")

        return True

    return assertion


def _more_links_out_to(address: str, more: int, than: bytes) -> Assertion[bytes]:
    """The file links out to `address` `more` times more than `than` does."""
    def assertion(pdf: bytes) -> bool:
        expected = _links_out(than).count(address) + more
        found = _links_out(pdf).count(address)

        if found != expected:
            raise AssertionError(f"Expected {expected} links out to {address}, and the PDF "
                                 f"has {found}.")

        return True

    return assertion


def _at_least_more_links_out_to(address: str, more: int, than: bytes) -> Assertion[bytes]:
    """The file links out to `address` at least `more` times more than `than`
    does - at least, because a link wrapped across two lines is two in the
    file."""
    def assertion(pdf: bytes) -> bool:
        expected = _links_out(than).count(address) + more
        found = _links_out(pdf).count(address)

        if found < expected:
            raise AssertionError(f"Expected at least {expected} links out to {address}, "
                                 f"and the PDF has {found}.")

        return True

    return assertion


def _one_more_link_out_to(address: str, than: bytes) -> Assertion[bytes]:
    """The file links out to `address` once more than `than` does."""
    def assertion(pdf: bytes) -> bool:
        expected = _links_out(than).count(address) + 1
        found = _links_out(pdf).count(address)

        if found != expected:
            raise AssertionError(f"Expected {expected} links out to {address}, and the PDF "
                                 f"has {found}.")

        return True

    return assertion


def _links_out(pdf: bytes) -> list[str]:
    """Where each link out of the file goes, once for every link."""
    return [link.get_object()["/A"]["/URI"]
            for page in PdfReader(io.BytesIO(pdf)).pages
            for link in page.get("/Annots", [])
            if "/A" in link.get_object()]


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


def _nothing_set_is_painted_over() -> Assertion[bytes]:
    """No filled shape is drawn, later in a page, over where a piece of text
    was set on it - which the text read back cannot show, since words painted
    out are still in the file.

    Where each piece of text is set is where `Td` moves to; a filled shape is
    each rectangle `re` lays out before the fill that paints them."""
    def assertion(pdf: bytes) -> bool:
        reader = PdfReader(io.BytesIO(pdf))
        covered: list[tuple[int, float, float]] = []

        for number, page in enumerate(reader.pages, start=1):
            texts: list[tuple[float, float]] = []
            rectangles: list[tuple[float, float, float, float]] = []
            for operands, operator in ContentStream(page.get_contents(), reader).operations:
                if operator == b"Td":
                    texts.append((float(operands[0]), float(operands[1])))
                elif operator == b"re":
                    x, y, width, height = (float(each) for each in operands)
                    rectangles.append((min(x, x + width), max(x, x + width),
                                       min(y, y + height), max(y, y + height)))
                elif operator in (b"f", b"F", b"f*", b"B", b"B*"):
                    covered += [(number, x, y) for x, y in texts
                                for left, right, bottom, top in rectangles
                                if left <= x <= right and bottom <= y <= top]
                    rectangles = []
                elif operator in (b"S", b"n"):
                    rectangles = []

        if covered:
            raise AssertionError(f"Expected no text painted over once set, and text set at "
                                 f"(page, x, y) {covered} is.")

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


def _set_on_one_line(expected: str) -> Assertion[bytes]:
    """`expected` is written whole by one piece of the PDF's text - a cell
    that wraps it writes each of its lines apart."""
    def assertion(pdf: bytes) -> bool:
        pieces: list[str] = []
        for page in PdfReader(io.BytesIO(pdf)).pages:

            def visit(text: str, *_: object) -> None:
                pieces.append(text)

            page.extract_text(visitor_text=visit)

        if not any(expected in piece for piece in pieces):
            raise AssertionError(f"Expected [{expected}] set on one line, and no piece of "
                                 f"the PDF's text holds it whole: {pieces}.")

        return True

    return assertion


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
