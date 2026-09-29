## ADDED Requirements

### Requirement: A fix may carry the repair of what the fault already wrote

The system SHALL allow a proposed fix to contain, beside the change that stops
the fault, a second file that repairs the data the fault has already written.

Some faults leave a residue. A write path that stopped keeping two values in step
is fixed by a patch, and every value it already wrote stays wrong afterwards -
so a pull request holding only the patch is a pull request that closes an
incident while leaving the damage in place. Both belong in one pull request,
because they are one change: a reviewer approving the fix is approving what has
to happen to the rows behind it.

#### Scenario: The repair is proposed beside the fix
- **GIVEN** a cause whose fault has already written wrong values
- **WHEN** a fix is proposed for it
- **THEN** one pull request carries both the change that stops the fault and a
  script that repairs what it wrote

#### Scenario: An ordinary fix is unchanged
- **GIVEN** a cause whose fault left nothing behind
- **WHEN** a fix is proposed for it
- **THEN** the pull request carries the change alone

### Requirement: A repair is proposed and never run

The system SHALL NOT execute a repair it proposes, and SHALL hold no capability
that could. A repair rewrites stored data and cannot be undone by putting a value
back, which places it outside what Argus may do unasked by the same rule that
keeps it from merging its own pull requests (§13).

#### Scenario: Nothing in the binding can run a repair
- **WHEN** the functions available to the Code-Fix agent are enumerated
- **THEN** none of them executes a script against the target's data

#### Scenario: The pull request says the repair is owed
- **GIVEN** a pull request carrying a repair script
- **WHEN** its body is read
- **THEN** it says the repair has not been run and that a person must run it
