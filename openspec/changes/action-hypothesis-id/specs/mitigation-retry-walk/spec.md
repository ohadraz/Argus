## MODIFIED Requirements

### Requirement: Each attempt is recorded against its own candidate
Every attempt SHALL mark its candidate as tested and record what the attempt did. The action recorded for an attempt SHALL name the hypothesis it was taken for, so the association between a decision and the act carried out for it is stored rather than inferred. The incident's timeline SHALL show which candidates were tried, in what order, and with what result.

#### Scenario: The timeline reads as an ordered set of attempts
- **GIVEN** an incident where two candidates were tried and refuted and a third confirmed
- **WHEN** the incident is read back
- **THEN** three candidates are marked tested, each with its own result, in the order they were attempted

#### Scenario: An action names the candidate it was taken for
- **GIVEN** an attempt on a ranked candidate
- **WHEN** the action taken for it is recorded
- **THEN** the action row names that hypothesis, and a reader follows that reference rather than matching on the subject the two happen to share

#### Scenario: Two candidates naming the same subject
- **GIVEN** two candidates in one incident that name the same flag
- **WHEN** an action is taken for each
- **THEN** each action is still attributable to its own candidate, because the association does not depend on the subject being unique
