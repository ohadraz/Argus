## ADDED Requirements

### Requirement: A metric bucket reports how much of its work the cache served
The system SHALL carry, on every metric bucket, the share of lookups served from
cache over that minute, as `cache_hit_ratio`. It SHALL be a ratio rather than a
pair of counts, because unlike memory against its limit there is no threshold to
forecast a crossing of - what a reader asks of it is how much of the work the
cache is carrying, and the ratio answers that directly. It SHALL be reported on
every bucket, whether or not the service is under a cache condition, for the
reason the memory fields are: a field that appears when it matters is a signal
by its presence.

#### Scenario: The hit ratio reaches the model
- **WHEN** a metrics summary is retrieved for a window
- **THEN** every bucket in it carries `cache_hit_ratio`

#### Scenario: A service with no cache reports its absence rather than zero
- **GIVEN** a deployment whose service consults no cache
- **WHEN** a metrics summary is retrieved
- **THEN** `cache_hit_ratio` is absent, rather than reported as zero - which
  would be indistinguishable from a cache that is answering nothing

### Requirement: The hit ratio is aggregated per minute as a share of that minute
The system SHALL derive a minute's `cache_hit_ratio` as the share of that
minute's lookups that were served from cache, rather than as the last observed
value or the mean of finer-grained ratios. It is a rate over the minute, as
`error_rate` is, and averaging ratios computed over unequal numbers of lookups
would weight a quiet instant as heavily as a busy one.

#### Scenario: A minute in which the cache became unreachable partway
- **GIVEN** a minute whose first half was served from cache and whose second
  half was not
- **WHEN** the bucket for that minute is produced
- **THEN** `cache_hit_ratio` reports the share over the whole minute rather than
  the value at its end
