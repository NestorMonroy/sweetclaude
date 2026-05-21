Feature: Source file scanning
  Discover all legacy taxonomy files across known locations.

  Background:
    Given a project directory with product base ".sweetclaude/product"

  Scenario: Scan finds BL files in backlog
    Given BL-001-foo.md exists in backlog/
    And BL-042-bar.md exists in backlog/
    When scan_sources() is called
    Then it returns 2 sources
    And each source has entity_type "BL"

  Scenario: Scan finds STORY files in done directory
    Given STORY-015-alpha.md exists in backlog/done/
    And STORY-016-beta.md exists in backlog/done/
    When scan_sources() is called
    Then it returns 2 sources with entity_type "STORY"

  Scenario: Scan finds spike reports
    Given spike-BL-016-gstack.md exists in backlog/spike-reports/
    And spike-BL-017-voice.md exists in backlog/spike-reports/
    When scan_sources() is called
    Then it returns 2 sources with entity_type "spike-BL"

  Scenario: Scan finds I-N files in issues directory
    Given I-001-duplicate.md exists in issues/
    When scan_sources() is called
    Then it returns 1 source with entity_type "I"

  Scenario: Scan finds RM files in roadmap
    Given RM-001-mvp.md exists in roadmap/
    When scan_sources() is called
    Then it returns 1 source with entity_type "RM"

  Scenario: Scan finds MS files in milestones
    Given MS-007-tracked-workflows.md exists in milestones/
    When scan_sources() is called
    Then it returns 1 source with entity_type "MS"

  Scenario: Scan finds EP files in backlog
    Given EP-001-taxonomy.md exists in backlog/
    When scan_sources() is called
    Then it returns 1 source with entity_type "EP"

  Scenario: Non-matching files are ignored
    Given README.md exists in backlog/
    And ISSUE-090-already-migrated.md exists in backlog/
    When scan_sources() is called
    Then it returns 0 sources

  Scenario: Index files are not scanned
    Given BACKLOG-INDEX.md exists in backlog/
    And ISSUES-INDEX.md exists in issues/
    And MILESTONES-INDEX.md exists in milestones/
    When scan_sources() is called
    Then it returns 0 sources

  Scenario: Files in wrong subdirectory are ignored
    Given BL-001.md exists in backlog/done/ (wrong location for BL)
    And BL-002.md exists in backlog/spike-reports/ (not a spike-BL file)
    When scan_sources() is called
    Then it returns 0 sources

  Scenario: CHORE, BUG, DEBT files are not source types
    Given CHORE-010.md exists in backlog/
    And BUG-003.md exists in backlog/
    And DEBT-005.md exists in backlog/
    When scan_sources() is called
    Then it returns 0 sources

  Scenario: Scan respects non-default product base
    Given artifact-privacy.yaml has product base_path ".sweetclaude/custom-product"
    And BL-001.md exists in .sweetclaude/custom-product/backlog/
    When scan_sources() is called
    Then it returns 1 source
    And the source path is under .sweetclaude/custom-product/

  Scenario: BL file with leading zeros in number is scanned
    Given BL-007-spy.md exists in backlog/
    When scan_sources() is called
    Then it returns 1 source with raw_id "007"
