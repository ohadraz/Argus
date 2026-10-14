## ADDED Requirements

### Requirement: The PDF says what the page says

The system SHALL produce, for any incident with a written postmortem, a PDF
carrying the same sections as the postmortem page, in the same order, in the
same words: the title, the header, every section the template names, and a
person's resolution where there is one. The page and the PDF SHALL be worked
out from one set of values, so that neither can say something the other does
not.

#### Scenario: The sections arrive in the page's order
- **GIVEN** an incident with a written postmortem
- **WHEN** its PDF is produced
- **THEN** its text carries every section heading the page shows, in the
  page's order

#### Scenario: The title is the page's title
- **GIVEN** a postmortem whose symptom and confirmed trigger give the page its
  title
- **WHEN** its PDF is produced
- **THEN** the PDF opens with that title, word for word

#### Scenario: A cited label leads to its row
- **GIVEN** a postmortem whose prose - a paragraph, a list item, a contributing
  factor's items or an action item - cites a label the document has a row for
- **WHEN** its PDF is produced
- **THEN** the label is a link inside the file that lands on that row, as it is
  on the page

#### Scenario: A person's resolution is carried
- **GIVEN** a postmortem written before a person resolved the incident
- **WHEN** its PDF is produced after the resolution
- **THEN** it says who resolved the incident, from where, when, and what they
  wrote

### Requirement: The PDF is readable away from Argus

Every time in the PDF SHALL be in UTC and SHALL say so. Every address SHALL be
written in full. Every amount SHALL be shown to two decimal places with its
currency. Text in Latin, Greek or Cyrillic script, and the punctuation and
symbols the page uses, SHALL be printed as written; a character no bundled font
carries SHALL NOT fail the download.

#### Scenario: A time names its zone
- **WHEN** a PDF is produced
- **THEN** every time it states is followed by UTC, and no time is given on any
  other clock

#### Scenario: The proposed fix is written in full
- **GIVEN** a postmortem with a draft pull request
- **WHEN** its PDF is produced
- **THEN** it carries the pull request's full address

#### Scenario: Prose outside Latin-1 is printed
- **GIVEN** a summary containing an em dash and a lead written by a person
  named in Cyrillic
- **WHEN** its PDF is produced
- **THEN** both are printed as written

#### Scenario: A character no font carries
- **GIVEN** a lead containing a character in a script no bundled font covers
- **WHEN** its PDF is produced
- **THEN** the PDF is produced, with the rest of the lead printed

### Requirement: The PDF is served as a download

The system SHALL serve an incident's postmortem PDF at
`/incidents/{id}/postmortem.pdf` as an attachment, named for the incident. It
SHALL answer not-found where there is no such incident, and where the incident
has no postmortem yet.

#### Scenario: A written postmortem is downloaded
- **GIVEN** an incident with a written postmortem
- **WHEN** its PDF address is requested
- **THEN** the answer is a PDF, sent as an attachment whose file name carries
  the incident's ID

#### Scenario: No postmortem yet
- **GIVEN** an incident with no postmortem
- **WHEN** its PDF address is requested
- **THEN** the answer is not-found

#### Scenario: No such incident
- **WHEN** the PDF address of an incident that does not exist is requested
- **THEN** the answer is not-found

### Requirement: The postmortem page offers the download

The postmortem page SHALL carry a button that downloads the PDF, where a
postmortem has been written, and SHALL carry none where one has not.

#### Scenario: A button beside a written document
- **GIVEN** an incident with a written postmortem
- **WHEN** its postmortem page is shown
- **THEN** it carries a download button pointing at the incident's PDF address

#### Scenario: No button where there is nothing to download
- **GIVEN** an incident with no postmortem
- **WHEN** its postmortem page is shown
- **THEN** it carries no download button
