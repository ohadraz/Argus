"""The write-up's times and broken-stretch figures, worked out again from the
minutes and the stored events, and checked against what the document stored and
what the page prints. Run it on every capture.

usage: check_figures.py <capture dir>
(run as `.venv/Scripts/python.exe -X utf8`: it imports argus_core's detector)

The stretch is every minute from the onset up to the first minute that reads
normal: onset <= minute start < first normal minute. The first normal minute is
- the end itself, where the end is a whole minute;
- the minute holding the end, where the end is the instant an action was
  applied: Argus moves the end there only when that minute already reads
  normal (measuring.py `_found_back_before`);
- the minute after the one holding the end, where the end is any other instant,
  such as a person's report: that minute still holds the incident.

Minutes come from `metrics_after.json` - the minutes read again once the
write-up was done, which read as they did then, since an elapsed minute reads
the same each time it is fetched - or else from the Investigator's reads (the
`metrics-retrieved` events). Those stop near the alert, and the minute in
progress at each read is provisional, so a check resting on either says so
rather than passing.

Times: each marker against the event it stands for; the onset against
argus_core's own `find_onset` over the Investigator's first read; the end
against `find_back_to_normal` from the recovery minute Mitigation recorded,
where the minutes reach past it; each marker's minute and its reading; the
stored duration; and the page's summary and detection times.

Figures: how many minutes the stored figures span (requests failed / volume /
rate while broken, where every minute read carries one volume) against the
stretch; and before, while broken, at its worst, requests failed, the rule
series' three levels, each latency level the brief tells and the load a
confirmed demand-saturation's R rows tell - requests a minute and CPU as a share
of its limit, the hour's median before, the stretch's mean and highest
(`write_up_request.json`) - worked out again where every minute needed was read
in full. An end inside a minute that reads normal passes only where one of
those shows the figures leave that minute out.

Where no postmortem was written - a replay that stopped at the write-up - the
stretch is the one the brief tells, to the second, its end taken as the action
applied in that second where one was; and only the brief's own figures are
checked: the onset, the latency and the load it tells.

Prints OK, NOTE and FLAG lines; exits 1 on any FLAG.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from statistics import median, median_high, median_low

from argus_core import Settings
from argus_core.anomaly import AnomalyThresholds, find_back_to_normal, find_onset
from argus_core.models import MetricBucket

A_MINUTE = timedelta(minutes=1)
AN_HOUR = timedelta(hours=1)
CLOSE = 1e-9


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def minute_of(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def iso_duration(text: str) -> timedelta:
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", text)
    if match is None:
        raise ValueError(f"cannot read the duration {text!r}")
    days, hours, minutes, seconds = (float(part) if part else 0.0 for part in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def a_gap(span: timedelta) -> str:
    """A span as the page says one: "6 minutes 2 seconds", "7 minutes"."""
    whole = int(span.total_seconds())
    minutes, seconds = divmod(whole, 60)
    parts = [f"{minutes} minute{'s' if minutes != 1 else ''}"] if minutes else []
    parts += [f"{seconds} second{'s' if seconds != 1 else ''}"] if seconds else []
    return " ".join(parts) or "0 seconds"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def the_thresholds() -> AnomalyThresholds:
    """The stack's lines: Settings' own defaults, which no compose file or
    .env.example overrides."""
    fields = Settings.model_fields
    return AnomalyThresholds(
        deviations_from_baseline=fields["anomaly_deviations_from_baseline"].default,
        persistence_minutes=fields["anomaly_persistence_minutes"].default,
        recovery_fraction_of_the_rise=fields["recovery_fraction_of_the_rise"].default
    )


def loaded(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return rows if isinstance(rows, list) else [rows]


def the_events(capture: Path) -> list[dict]:
    events = []
    for row in loaded(capture / "db" / "incident_event.json"):
        payload = row.get("payload")
        events.append(json.loads(payload) if isinstance(payload, str) else payload or {})
    return sorted(events, key=lambda event: event.get("at", ""))


def the_minutes(capture: Path,
                events: list[dict]) -> tuple[dict[datetime, dict], set[datetime], str]:
    """Each minute read, by its start; those read while still in progress; and
    where they came from."""
    after = capture / "metrics_after.json"
    if after.exists():
        read = json.loads(after.read_text(encoding="utf-8"))
        buckets = read["buckets"] if isinstance(read, dict) else read
        return {instant(bucket["bucket_id"]): bucket for bucket in buckets}, set(), after.name

    minutes: dict[datetime, dict] = {}
    provisional: set[datetime] = set()
    for event in events:
        if event.get("kind") != "metrics-retrieved":
            continue
        read_at = instant(event["at"])
        for bucket in event.get("buckets") or []:
            minute = instant(bucket["bucket_id"])
            in_progress = minute <= read_at < minute + A_MINUTE
            if in_progress and minute in minutes and minute not in provisional:
                continue
            minutes[minute] = bucket
            if in_progress:
                provisional.add(minute)
            else:
                provisional.discard(minute)
    return minutes, provisional, "the Investigator's reads (metrics-retrieved events)"


def page_text(capture: Path) -> str:
    html = (capture / "postmortem_page.html").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))


def the_brief(capture: Path) -> str:
    """The write-up's brief as the model was handed it - empty where no
    write-up request was captured."""
    request = capture / "write_up_request.json"
    if not request.exists():
        return ""
    return json.loads(request.read_text(encoding="utf-8"))["transcript"][0]["text"]


# The stretch as the brief tells it, each instant to the second: "Broken from
# 2026-11-06T01:07:00Z {began} (the onset) to 2026-11-06T01:15:55Z {back_to_normal}".
STRETCH_TOLD = re.compile(r"Broken from (\S+) \{began\}[^\n]*? to (\S+) \{back_to_normal\}")


def the_stretch_told(capture: Path,
                     taken: list[datetime]) -> tuple[datetime, datetime] | None:
    """The onset and the end the brief tells - the end as the instant of the
    action taken in that second, where one was - or none where it tells neither."""
    found = STRETCH_TOLD.search(the_brief(capture))
    if found is None:
        return None
    ended = instant(found[2])
    return instant(found[1]), next(
        (moment for moment in taken if moment.replace(microsecond=0) == ended), ended)


# A latency level as the brief gives it: "44.9 ms {latency_p50_before}".
LATENCY_TOLD = re.compile(r"([\d.]+) ms \{latency_(p50|p95|p99)_(before|while_broken|at_worst)\}")


def the_latency_told(capture: Path) -> dict[tuple[str, str], float]:
    """Each latency level the brief tells, by quantile and level - none where it
    tells none, or where no write-up request was captured."""
    return {(quantile, level): float(value)
            for value, quantile, level in LATENCY_TOLD.findall(the_brief(capture))}


# The load a confirmed demand-saturation's R rows tell, each figure perhaps
# followed by its name: "Requests: 1200/min {R1.1} before it began, ...". Captures
# from before the volumes carried their unit say "Requests a minute: 1200 {R1.1}".
_NAMED = r"(?: \{R\d+\.\d+\})?"
_PER_MINUTE = r"(?:/min)?"
LOAD_TOLD = {
    "requests": re.compile(
        r"Requests(?: a minute)?: ([\d.,]+)" + _PER_MINUTE + _NAMED + r" before it began, "
        + r"([\d.,]+)" + _PER_MINUTE + _NAMED + r" on average while it was broken, "
        + r"([\d.,]+)" + _PER_MINUTE + _NAMED + r" at its highest"),
    "cpu share": re.compile(
        r"CPU in use, as a share of the service's CPU limit: ([\d.]+)%" + _NAMED
        + r" before it began, ([\d.]+)%" + _NAMED + r" on average while it was broken, "
        + r"([\d.]+)%" + _NAMED + r" at its highest")
}


def the_load_told(capture: Path) -> dict[str, tuple[float, ...]]:
    """The load the brief's R rows tell, by series: before, while broken and at
    its highest - none where it tells none, or where no write-up request was
    captured."""
    brief = the_brief(capture)
    told = {}
    for series, pattern in LOAD_TOLD.items():
        found = pattern.search(brief)
        if found:
            told[series] = tuple(float(value.replace(",", "")) for value in found.groups())
    return told


def the_load_of(series: str, bucket: dict) -> float | None:
    """A minute's reading of `series`, as the R rows say it: requests a minute,
    or the CPU in use as a percentage of its limit (none where no limit was read)."""
    if series == "requests":
        return float(bucket["request_volume"])
    limit = bucket.get("cpu_limit_cores")
    return 100 * bucket["cpu_used_cores"] / limit if limit else None


def main() -> None:
    capture = Path(sys.argv[1])
    lines: list[str] = []

    def say(kind: str, text: str) -> None:
        lines.append(f"{kind:4} {text}")

    documents = loaded(capture / "db" / "postmortem.json")
    written = bool(documents)
    document = documents[0] if written else {}
    for field in ("impact", "timeline"):
        if isinstance(document.get(field), str):
            document[field] = json.loads(document[field])
    impact = document.get("impact") or {}
    markers: dict[str, list[datetime]] = {}
    for entry in document.get("timeline") or []:
        if entry.get("marker"):
            markers.setdefault(entry["marker"], []).append(instant(entry["at"]))
    events = the_events(capture)
    kinds: dict[str, list[dict]] = {}
    for event in events:
        kinds.setdefault(event.get("kind", ""), []).append(event)
    taken = [instant(event["at"]) for event in kinds.get("action-taken", [])]
    if not written:
        told_stretch = the_stretch_told(capture, taken)
        if told_stretch is None:
            print("NOTE no postmortem was written, nor a brief telling the stretch: nothing to "
                  "check")
            return
        say("NOTE", "no postmortem was written: the brief's own figures, against the stretch "
            "it tells")
        markers = {"impact begins": [told_stretch[0]], "impact ends": [told_stretch[1]],
                   "mitigation applied": [moment for moment in taken
                                          if moment == told_stretch[1]]}
    minutes, provisional, source = the_minutes(capture, events)
    thresholds = the_thresholds()
    text = page_text(capture) if written else ""

    began = (markers.get("impact begins") or [None])[0]
    ended = (markers.get("impact ends") or [None])[0]
    if began is None or ended is None:
        say("NOTE", "no impact-begins or impact-ends marker: no measured stretch to check")
        print("\n".join(lines))
        return
    applied = markers.get("mitigation applied") or []

    # The times.
    onsets = [instant(event["onset"]) for event in kinds.get("onset-detected", [])
              if event.get("onset")]
    if onsets:
        say("OK" if began == onsets[0] else "FLAG",
            f"impact begins {began:%H:%M:%S}, the onset recorded {onsets[0]:%H:%M:%S}")
    first_read = next((event for event in kinds.get("metrics-retrieved", [])), None)
    if first_read and onsets:
        found = find_onset([MetricBucket.model_validate(bucket)
                            for bucket in first_read.get("buckets") or []], thresholds)
        say("OK" if found and instant(found) == onsets[0] else "FLAG",
            f"find_onset over the Investigator's first read: {found}, recorded {onsets[0]:%H:%M}")

    alerts = kinds.get("alert-acknowledged", [])
    fired = instant(alerts[0]["alert"]["started_at"]) if alerts else None
    for detected in markers.get("detected", []):
        if fired is not None:
            say("OK" if detected == fired else "FLAG",
                f"detected {detected:%H:%M:%S}, the alert fired {fired:%H:%M:%S}")
        if detected < began:
            say("NOTE", f"detected {detected:%H:%M:%S} is before the onset {began:%H:%M}")
        gap = a_gap(detected - began)
        say("OK" if f"{gap} later" in text else "NOTE",
            f"the page's detection gap: \"{gap} later\""
            + ("" if f"{gap} later" in text else " not found as written"))

    for moment in applied:
        found_it = moment in taken
        say("OK" if found_it else "FLAG",
            f"mitigation applied {moment:%H:%M:%S.%f}: "
            + ("an action-taken event's instant" if found_it else "no action-taken event at it"))
        if not began <= moment <= ended + A_MINUTE:
            say("NOTE", f"mitigation applied {moment:%H:%M:%S} is outside the stretch")

    whole = ended == minute_of(ended)
    if whole:
        first_normal, why = ended, "the end is a whole minute"
    elif ended in applied:
        first_normal, why = minute_of(ended), "the end is the instant an action was applied"
    else:
        first_normal = minute_of(ended) + A_MINUTE
        why = "the end is an instant no action was applied at"
    stretch = int((first_normal - began) / A_MINUTE)
    say("NOTE", f"stretch {began:%H:%M} up to {first_normal:%H:%M}: {stretch} minutes ({why})")

    recovered = [instant(event["recovered_minute"]) for event in kinds.get("recovery-checked", [])
                 if event.get("recovered") and event.get("recovered_minute")]
    if recovered:
        since = recovered[-1]
        read_after = [minute for minute in minutes if minute > since]
        if read_after and not any(minute in provisional for minute in read_after):
            back = find_back_to_normal(
                [MetricBucket.model_validate(minutes[minute]) for minute in sorted(minutes)
                 if minute >= began - AN_HOUR], thresholds, since=since.isoformat())
            say("OK" if back and instant(back) == first_normal else "FLAG",
                f"find_back_to_normal from the recovery minute {since:%H:%M}: {back}, "
                f"the stretch's first normal minute {first_normal:%H:%M}")
        else:
            say("NOTE", f"the end is not checked against the minutes: none read in full after "
                f"the recovery minute {since:%H:%M} (capture metrics_after.json)")

    for name, moments in sorted(markers.items()):
        for moment in moments:
            minute = minute_of(moment)
            bucket = minutes.get(minute)
            reading = ("not read" if bucket is None else
                       f"errors {percent(bucket['error_rate'])}"
                       + (" (in progress)" if minute in provisional else ""))
            say("NOTE", f"{name} {moment:%H:%M:%S} is in minute {minute:%H:%M}: {reading}")

    if impact.get("duration"):
        stored = iso_duration(impact["duration"])
        say("OK" if abs(stored - (ended - began)) < timedelta(milliseconds=1) else "FLAG",
            f"duration stored {stored}, end less onset {ended - began}")
    # The page gives the seconds where a time has any, as a time of day says them,
    # and says a person's report as resolved rather than back to normal.
    at_the_end = f"{ended:%H:%M:%S} UTC" if ended.second else f"{ended:%H:%M} UTC"
    page_says = (f"broke at {began:%H:%M} UTC", f"back to normal at {at_the_end}")
    for said in page_says if written else ():
        found = said in text or (said.startswith("back") and f"resolved at {at_the_end}" in text)
        say("OK" if found else "NOTE",
            f"the page says \"{said}\"" + ("" if found else ": not found as written"))

    # The figures.
    say("NOTE", f"minutes from {source}: {len(minutes)}")
    rates = impact.get("error_rates") or {}
    while_stored = rates.get("while_broken")
    failed_stored = impact.get("requests_failed")
    volumes = {bucket.get("request_volume") for bucket in minutes.values()}
    leaves_it_out: bool | None = None

    if len(volumes) == 1 and while_stored and failed_stored:
        volume = next(iter(volumes))
        spanned = failed_stored / (volume * while_stored)
        leaves_it_out = abs(spanned - stretch) < 0.5
        say("OK" if leaves_it_out else "FLAG",
            f"the stored figures span {spanned:.2f} minutes ({failed_stored} failed / {volume} "
            f"a minute / {percent(while_stored)}), the stretch {stretch}")

    hour = sorted(minute for minute in minutes if began - AN_HOUR <= minute < began)
    broken = [began + position * A_MINUTE for position in range(stretch)]
    missing = [minute for minute in broken if minute not in minutes]
    unsure = sorted(minute for minute in broken + hour if minute in provisional)
    hour_short = len(hour) < int(AN_HOUR / A_MINUTE)

    if missing or unsure or hour_short:
        if missing:
            say("NOTE", f"not read: {', '.join(f'{minute:%H:%M}' for minute in missing)}")
        if unsure:
            say("NOTE", f"read in progress: {', '.join(f'{minute:%H:%M}' for minute in unsure)}")
        if hour_short:
            say("NOTE", f"the hour before the onset has {len(hour)} minutes read")
        say("NOTE", "the stretch's figures are not worked out again (capture metrics_after.json)")
    else:
        in_it = [minutes[minute] for minute in broken]
        before_it = [minutes[minute] for minute in hour]
        worked_out = {
            "before": sum(bucket["error_rate"] for bucket in before_it) / len(before_it),
            "while broken": sum(bucket["error_rate"] for bucket in in_it) / len(in_it),
            "at its worst": max(bucket["error_rate"] for bucket in in_it),
            "requests failed": round(sum(bucket["request_volume"] * bucket["error_rate"]
                                         for bucket in in_it))
        }
        stored = {"before": rates.get("before"), "while broken": while_stored,
                  "at its worst": impact.get("peak_error_rate"), "requests failed": failed_stored}
        agree = True
        for name, value in worked_out.items() if written else ():
            if stored[name] is None:
                say("NOTE", f"{name}: worked out {value}, none stored")
                continue
            matches = abs(stored[name] - value) < CLOSE
            agree = agree and matches
            say("OK" if matches else "FLAG", f"{name}: stored {stored[name]}, worked out {value}")
        leaves_it_out = agree if leaves_it_out is None else leaves_it_out and agree

        series = impact.get("rule_series_harm")
        readings_before = [bucket["rule_reading"]["value"] for bucket in before_it
                           if bucket.get("rule_reading")]
        readings_in_it = [bucket["rule_reading"] for bucket in in_it if bucket.get("rule_reading")]
        if series and readings_before and readings_in_it:
            values = [reading["value"] for reading in readings_in_it]
            below = readings_in_it[0].get("worse_when") == "below"
            for name, value in (("before", sum(readings_before) / len(readings_before)),
                                ("while_broken", sum(values) / len(values)),
                                ("at_its_worst", min(values) if below else max(values))):
                say("OK" if abs(series[name] - value) < CLOSE else "FLAG",
                    f"rule series {name}: stored {series[name]}, worked out {value}")

        told = the_latency_told(capture)
        if not told:
            say("NOTE", "the brief tells no latency")
        for (quantile, level), value in sorted(told.items()):
            field = f"{quantile}_ms"
            readings_in_it = [bucket[field] for bucket in in_it]
            worked = {"before": sum(bucket[field] for bucket in before_it) / len(before_it),
                      "while_broken": sum(readings_in_it) / len(readings_in_it),
                      "at_worst": max(readings_in_it)}[level]
            say("OK" if abs(value - worked) < 1e-6 else "FLAG",
                f"latency {quantile} {level}: told {value}, worked out {worked}")

        # Before is the hour's median - the load climbs minutes before the
        # latency departs - so any of the median's three readings passes; the
        # brief says a share to a tenth of a percent and a volume to the request.
        load_told = the_load_told(capture)
        if not load_told:
            say("NOTE", "the brief tells no load")
        for series, levels in sorted(load_told.items()):
            before_values = [the_load_of(series, bucket) for bucket in before_it]
            in_values = [the_load_of(series, bucket) for bucket in in_it]
            if None in before_values or None in in_values:
                say("FLAG", f"load {series}: told, though a minute read no CPU limit")
                continue
            close = 0.5 if series == "requests" else 0.05
            worked_load = {
                "before": (median_low(before_values), median(before_values),
                           median_high(before_values)),
                "while broken": (sum(in_values) / len(in_values),),
                "at its highest": (max(in_values),)
            }
            for (level, candidates), value in zip(worked_load.items(), levels, strict=True):
                matches = any(abs(value - candidate) <= close for candidate in candidates)
                say("OK" if matches else "FLAG",
                    f"load {series} {level}: told {value}, worked out "
                    f"{candidates[len(candidates) // 2]}")

    if written and not whole and ended in applied:
        say("OK" if leaves_it_out else "FLAG",
            f"the end {ended:%H:%M:%S.%f} is inside minute {minute_of(ended):%H:%M}, which reads "
            f"normal: the figures "
            + ("leave it out" if leaves_it_out
               else "count it" if leaves_it_out is False else "cannot be shown to leave it out"))

    # Failed requests and the error rate's worst are printed only where the error
    # rate rose and is what the alert watches; otherwise the page says "no rise"
    # and its cards are the rule series'.
    printed = rates.get("rose") and (impact.get("rule_series_harm") or {}).get(
        "is_the_error_rate", True)
    for name, shown in (("while broken", percent(while_stored) if while_stored else None),
                        ("requests failed", f"{failed_stored:,}"
                         if failed_stored and printed else None),
                        ("at its worst", percent(impact["peak_error_rate"])
                         if impact.get("peak_error_rate") and printed else None)):
        if shown is not None:
            say("OK" if shown in text else "NOTE", f"the page prints {name} as {shown}"
                + ("" if shown in text else ": not found as written"))

    print("\n".join(lines))
    sys.exit(1 if any(line.startswith("FLAG") for line in lines) else 0)


if __name__ == "__main__":
    main()
