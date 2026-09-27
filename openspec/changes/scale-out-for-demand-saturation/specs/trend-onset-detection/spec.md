## ADDED Requirements

### Requirement: Utilisation is retrieved and not judged
The system SHALL NOT date an onset from CPU utilisation, and SHALL NOT hold a
recovery open on it. The series an onset is found in stay the error rate, the
median, the 95th, the 99th and the memory in use.

Stated rather than left as an omission, because the memory precedent reads as an
argument for judging every gauge and it is not one. Utilisation tracks traffic,
so a departure in it dates the onset at the minute the load arrived - minutes
before anything was wrong, and in a busy stretch where nothing ever was. A heap
that departs its baseline departs it for a reason no traffic pattern explains,
which is why that gauge is judged and this one is not. The incident a saturated
service causes is the latency it causes, which the five judged series already
see, and the minute they date is the minute customers were hurt.

CPU therefore joins `request_volume` and `cache_hit_ratio`: on the bucket,
retrieved with it, read by whoever is diagnosing, and no part of the judgement
that there is an incident at all.

#### Scenario: A busy hour with headroom is not an onset
- **GIVEN** a window in which CPU rose substantially while the error rate, the
  quantiles and memory stayed at their baselines
- **WHEN** the window is judged
- **THEN** no onset is dated

#### Scenario: A saturated service is dated from its latency
- **GIVEN** a window in which CPU pinned at capacity and the quantiles climbed
  two minutes later
- **WHEN** the window is judged
- **THEN** the onset is the minute the quantiles departed, not the minute CPU
  reached its ceiling

#### Scenario: Recovery is not held open by utilisation that stayed high
- **GIVEN** a mitigated incident whose quantiles have returned to baseline while
  CPU remains above its own
- **WHEN** recovery is judged
- **THEN** the service is found to have recovered
