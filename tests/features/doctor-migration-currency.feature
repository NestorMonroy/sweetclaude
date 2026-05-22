Feature: Doctor migration_currency checks
  The check_migration_currency function validates SweetClaude migration state:
  stale drift markers, schema drift via migration runner, taxonomy drift
  (old-prefixed files), and orphan scan via migrate-v3-to-v4.py.

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no migration_currency findings
    When check_migration_currency runs against the project state
    Then the result contains 0 findings

  # --- Stale drift marker ---

  Scenario: pending-drift-decision.yaml exists produces info finding
    Given pending-drift-decision.yaml exists in state directory
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:stale-drift-marker:pending-drift-decision.yaml"
    And the finding with id "migration-currency:stale-drift-marker:pending-drift-decision.yaml" has severity "info"
    And the finding with id "migration-currency:stale-drift-marker:pending-drift-decision.yaml" has fix_type "auto"
    And the finding with id "migration-currency:stale-drift-marker:pending-drift-decision.yaml" fix_recipe action is "delete_file"

  Scenario: No drift marker produces no stale-drift finding
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:stale-drift-marker"

  # --- Schema drift via migration runner ---

  Scenario: Migration runner absent skips schema drift check
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner reports schema drift produces warning
    Given migration runner exists and returns drift findings
    When check_migration_currency runs against the project state
    Then the result contains at least 1 finding with id prefix "migration-currency:schema-drift"
    And the first schema-drift finding has severity "warning"
    And the first schema-drift finding has fix_type "prompted"

  Scenario: Migration runner returns empty findings list
    Given migration runner exists and returns zero drift findings
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner subprocess times out is silently skipped
    Given migration runner exists and will timeout
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner returns invalid JSON is silently skipped
    Given migration runner exists and returns invalid JSON
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner exits non-zero is silently skipped
    Given migration runner exists and exits non-zero
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner returns JSON list directly
    Given migration runner exists and returns drift findings as a JSON list
    When check_migration_currency runs against the project state
    Then the result contains at least 1 finding with id prefix "migration-currency:schema-drift"

  Scenario: Migration runner returns valid JSON of unexpected type is silently skipped
    Given migration runner exists and returns a JSON string
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner OSError is silently skipped
    Given migration runner path is set but script raises OSError
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"

  Scenario: Migration runner timeout does not prevent orphan scan
    Given migration runner exists and will timeout
    And migrate-v3-to-v4.py exists and returns orphans
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:schema-drift"
    And the findings include id "migration-currency:orphans:scan"

  # --- Taxonomy drift (old-prefixed files) ---

  Scenario: STORY-prefixed file in backlog produces taxonomy drift warning
    Given a backlog file "STORY-001-old.md" with content "# Old story"
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:taxonomy-drift:old-prefixes"
    And the finding with id "migration-currency:taxonomy-drift:old-prefixes" has severity "warning"
    And the finding with id "migration-currency:taxonomy-drift:old-prefixes" has fix_type "prompted"

  Scenario: BUG-prefixed file in backlog produces taxonomy drift warning
    Given a backlog file "BUG-001-old.md" with content "# Old bug"
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:taxonomy-drift:old-prefixes"

  Scenario: DEBT-prefixed file in backlog produces taxonomy drift warning
    Given a backlog file "DEBT-001-old.md" with content "# Old debt"
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:taxonomy-drift:old-prefixes"

  Scenario: CHORE-prefixed file in backlog produces taxonomy drift warning
    Given a backlog file "CHORE-001-old.md" with content "# Old chore"
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:taxonomy-drift:old-prefixes"

  Scenario: ISSUE-prefixed file does not produce taxonomy drift
    Given a backlog file "ISSUE-001-test.md" with frontmatter id "ISSUE-001"
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:taxonomy-drift"

  Scenario: Mid-filename prefix does not match taxonomy drift
    Given a backlog file "old-STORY-001.md" with content "# Not a match"
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:taxonomy-drift"

  Scenario: Backlog directory absent produces no taxonomy drift finding
    Given the backlog directory does not exist
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:taxonomy-drift"

  Scenario: Old-prefixed file in backlog subdirectory detected by rglob
    Given a backlog file "stories/STORY-001-old.md" with content "# Old story in subdir"
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:taxonomy-drift:old-prefixes"

  Scenario: Multiple old-prefixed files produce single taxonomy drift finding
    Given a backlog file "STORY-001-old.md" with content "# Old story"
    And a backlog file "BUG-002-old.md" with content "# Old bug"
    When check_migration_currency runs against the project state
    Then the result contains exactly 1 finding with id "migration-currency:taxonomy-drift:old-prefixes"

  # --- Orphan scan ---

  Scenario: Orphan scan script absent skips orphan check
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:orphans"

  Scenario: Orphan scan finds orphans produces warning
    Given migrate-v3-to-v4.py exists and returns orphans
    When check_migration_currency runs against the project state
    Then the findings include id "migration-currency:orphans:scan"
    And the finding with id "migration-currency:orphans:scan" has severity "warning"
    And the finding with id "migration-currency:orphans:scan" has fix_type "prompted"

  Scenario: Orphan scan finds no orphans produces no finding
    Given migrate-v3-to-v4.py exists and returns empty orphans
    When check_migration_currency runs against the project state
    Then no finding has id "migration-currency:orphans:scan"

  Scenario: Orphan scan subprocess timeout is silently skipped
    Given migrate-v3-to-v4.py exists and will timeout
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:orphans"

  Scenario: Orphan scan returns invalid JSON is silently skipped
    Given migrate-v3-to-v4.py exists and returns invalid JSON
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:orphans"

  Scenario: Orphan scan exits non-zero is silently skipped
    Given migrate-v3-to-v4.py exists and exits non-zero
    When check_migration_currency runs against the project state
    Then no finding has id prefix "migration-currency:orphans"

  # --- Interaction: multiple check blocks fire together ---

  Scenario: Drift marker and taxonomy drift findings accumulate
    Given pending-drift-decision.yaml exists in state directory
    And a backlog file "STORY-001-old.md" with content "# Old story"
    When check_migration_currency runs against the project state
    Then the result contains at least 2 findings
    And the findings include id "migration-currency:stale-drift-marker:pending-drift-decision.yaml"
    And the findings include id "migration-currency:taxonomy-drift:old-prefixes"
