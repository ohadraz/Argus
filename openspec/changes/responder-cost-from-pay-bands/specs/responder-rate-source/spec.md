## ADDED Requirements

### Requirement: A job title's worth comes from a pay band, never from a person
The system SHALL obtain what a responder's time is worth from the HR source's
pay bands - a range attached to a compensation level that job titles are
assigned to - and SHALL NOT read any individual's compensation. The credential
the deployment uses SHALL NOT require access to employee pay.

#### Scenario: A title resolves to the band of the level it is assigned to
- **GIVEN** an HR source whose levels carry bands and job-title assignments
- **WHEN** a title is asked about
- **THEN** the band of the level that title is assigned to is returned, with
  its minimum, midpoint, maximum and currency

#### Scenario: No individual's pay is read
- **WHEN** the rate for any title is obtained
- **THEN** no employee's compensation is requested from the source

### Requirement: A title the bands do not cover is unpriced, not free
The system SHALL report a title absent from the bands as having no rate, and
SHALL NOT substitute another level's band, an average, or zero.

#### Scenario: An unassigned title has no rate
- **GIVEN** a title no level lists
- **WHEN** it is asked about
- **THEN** no rate is returned, and the title is reported as unpriced

### Requirement: A source that cannot be read says so
The system SHALL distinguish an HR source that could not be reached or refused
the request from one that answered with no band for a title. A failure to read
SHALL NOT be reported as an absence of bands.

#### Scenario: An unreachable source is not read as an empty one
- **GIVEN** an HR source that cannot be reached
- **WHEN** rates are asked for
- **THEN** the answer says the source could not be read, distinguishably from
  the source having no band for a title
