# automated-sync-suspension Specification

## Purpose
How Argus switches the deployment platform's automated sync off before an
action that changes live state, and back on in that action's undo: by the
switch alone, leaving everything else the application declares as the operator
declared it, and reading whether an application syncs itself exactly as the
platform reads it.
## Requirements
### Requirement: Suspension switches automated sync off and changes nothing else
The system SHALL suspend the deployment platform's automated sync, before an
action that changes live state, by patching the application with a JSON merge
patch that sets `spec.syncPolicy.automated.enabled` to `false`, through
`PATCH /api/v1/applications/{name}` with `patchType` `merge`. It SHALL NOT send
the application's spec, or any part of it, as a replacement: the platform's
spec route takes its body as the whole spec, and a sync policy sent there
erases every other field the application declares.

Everything else the sync policy carries - `prune`, `selfHeal`, `allowEmpty`,
`syncOptions`, `retry` - SHALL be as it was found once sync is suspended.

#### Scenario: Suspending sends a merge patch of the switch alone
- **GIVEN** an application whose automated sync is enabled
- **WHEN** a rollback, a scale-out or an autoscaler pin suspends its sync
- **THEN** one `PATCH` reaches the application's route, with `patchType`
  `merge` and a patch of `{"spec":{"syncPolicy":{"automated":{"enabled":false}}}}`
- **AND** no request is made to the spec route

#### Scenario: The rest of the sync policy survives a suspension
- **GIVEN** an application whose automated sync has `selfHeal` and `prune` on
- **WHEN** its sync is suspended
- **THEN** it reports automated sync disabled, with `selfHeal` and `prune` still on

### Requirement: Restoring removes the switch Argus set
The system SHALL restore automated sync, in an undo, by a merge patch that
removes `spec.syncPolicy.automated.enabled`, which the platform reads as enabled.
It SHALL NOT write an `automated` object of its own: the one the operator
declared is still in place, and writing one would replace it.

Where sync was already off when Argus found it, the undo SHALL leave it off,
exactly as before.

#### Scenario: Restoring sends a merge patch removing the switch
- **GIVEN** an undo record of an action taken while the application synced itself
- **WHEN** it is undone
- **THEN** one `PATCH` reaches the application's route with a patch of
  `{"spec":{"syncPolicy":{"automated":{"enabled":null}}}}`

#### Scenario: A suspension and its undo leave the policy as found
- **GIVEN** an application whose automated sync has `selfHeal` on
- **WHEN** its sync is suspended and then restored
- **THEN** it syncs itself again, with `selfHeal` still on

### Requirement: Whether an application syncs itself is read as the platform reads it
The system SHALL treat an application as syncing itself where its sync policy
carries an `automated` object whose `enabled` is absent or `true`. An `automated`
object with `enabled: false` SHALL read as not syncing itself, and an action
taken against it SHALL neither suspend nor, in its undo, restore sync.

#### Scenario: An automated policy switched off is not syncing
- **GIVEN** an application whose `automated` carries `enabled: false`
- **WHEN** a rollback reads it
- **THEN** sync is not suspended, and the undo record says it was not syncing

#### Scenario: An automated policy with no switch is syncing
- **GIVEN** an application whose `automated` is `{}`
- **WHEN** a rollback reads it
- **THEN** sync is suspended before the rollback is asked for

### Requirement: The Target Service's Argo CD stand-in answers the patch
The demo Target Service's Argo CD stand-in SHALL answer
`PATCH /argocd/{application}` as a real Argo CD answers
`PATCH /api/v1/applications/{name}` for a merge patch of the sync policy, and
report the resulting policy from its application route. Its application SHALL
start with automated sync enabled and `selfHeal` on. It SHALL refuse a rollback
only while automated sync is enabled, `enabled: false` included as disabled. It
SHALL NOT offer the spec route.

#### Scenario: The stand-in suspends and reports it
- **GIVEN** the stand-in's application, syncing itself
- **WHEN** a merge patch sets `automated.enabled` to `false`
- **THEN** its application route reports `enabled: false` with `selfHeal` on
- **AND** a rollback is accepted

