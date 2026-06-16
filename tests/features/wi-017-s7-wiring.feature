# WI-017 S7 — Wiring: close the dead-end at the system level
# Make the migrator a supported capability, route the typed-legacy shape to OFFER
# migration (instead of permanent compatibility mode), stop hard-blocking taxonomy
# migration, and let a migrated project graduate via the existing path (no flag-write exit).

Feature: A typed-legacy project is offered the migrator instead of being parked
  As a SweetClaude user whose project was trapped in compatibility mode
  I want update/doctor/recover/bootstrap to offer a real migration action
  So that no project shape is a permanent dead-end

  Scenario: The typed-legacy migrator is a supported capability in the manifest
    Given the capability manifest
    Then capability "migrate.typed_legacy_backlog" is supported
    And it declares a command entrypoint and supports the "typed_legacy_backlog" project shape
    And the "typed_legacy_backlog" project shape has migrate_allowed true

  Scenario: A fresh typed-legacy project's guard offers migration, not a dead-end
    Given a project with backlog/stories/STORY-* and backlog/debt/DEBT-* and old-prefix files
    And no recovery state has been written yet
    When the recovery guard runs
    Then the guard status routes to a migration-offering action
    And the action names a runnable migrate command or capability
    And the status is not a no-action permanent compatibility-mode

  Scenario: Taxonomy migration is no longer a hard-blocked action
    Given a typed-legacy project diagnosed by recover_project
    When the diagnosis is produced
    Then "taxonomy-migration" is not listed among blocked actions
    And the typed-backlog failure offers a migrate recovery strategy

  Scenario: A project already stabilized in compatibility mode is offered migration
    Given a project whose state has recovery.taxonomy.status "stabilized-without-migration"
    And its product tree still has typed-backlog dirs and old-prefix files
    When the recovery guard runs
    Then the guard offers the migrator as the resolving action

  Scenario: After migration the project becomes graduation-eligible (the sanctioned exit)
    Given a stabilized typed-legacy project
    When the migration is executed successfully
    And the recovery guard runs again
    Then the project is reported as v4-compliant / graduation-available
    And graduation clears the compatibility state

  Scenario: No flag-write shortcut exit is introduced
    Given the recovery scan and maintenance route
    Then no exit recipe of type "exit_compatibility_mode" is offered
    And status is never derived from a "compatibility_exited" flag
    # i.e. the existing dead-end-totality invariant still holds

  Scenario: Every guard status routes to an offered action (no-dead-end invariant)
    Given each project shape the guard can classify
    Then every resulting status has a routed action — migrate, recover, graduate, fix-blockers, or a documented manual review
    And no status leaves the user with no available next action

  Scenario: The maintenance route names migration for a typed-legacy project
    Given a typed-legacy project
    When the doctor maintenance route is computed
    Then the route offers the migration capability
