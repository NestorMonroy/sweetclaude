# WI-017 S1 — Detector hardening
# characterize_project.py must stop manufacturing false blockers and must see the
# shapes the migrator will need to act on. Read-only behavior only.

Feature: Project characterization ignores tool/editor backups and classifies shapes correctly
  As the SweetClaude recovery system
  I want characterization to exclude derived backup files and distinguish documents,
  work items, and bespoke epic/story shapes
  So that projects are not parked in compatibility mode by self-inflicted false blockers
  and so the migrator has an accurate inventory to act on

  Background:
    Given a temporary project with a resolvable product base

  Scenario: Tool backups are excluded from work-item and duplicate counting
    Given a product file "milestones/MS-001-core.md" with frontmatter id "MS-001"
    And a product file "milestones/MS-001-core.bold-backup-20260614-113230.md" with frontmatter id "MS-001"
    When the project is characterized
    Then the duplicate id count is 0
    And "MS-001-core.bold-backup-20260614-113230.md" is not counted as a work item
    And the backup file is reported under an excluded/derived-files inventory

  Scenario Outline: Editor and VCS backup variants are excluded
    Given a product file "backlog/stories/STORY-024-x.md" with frontmatter id "STORY-024"
    And a product file "<backup>" with frontmatter id "STORY-024"
    When the project is characterized
    Then the duplicate id count is 0
    And "<backup>" is not counted as a work item

    Examples:
      | backup                                        |
      | backlog/stories/STORY-024-x.md.bak            |
      | backlog/stories/STORY-024-x.md~               |
      | backlog/stories/STORY-024-x.md.orig           |
      | backlog/stories/STORY-024-x.bold-backup-1.md  |

  Scenario: Genuine duplicates (no backup involved) are still flagged
    Given a product file "backlog/stories/STORY-007-a.md" with frontmatter id "STORY-007"
    And a product file "backlog/stories/STORY-007-b.md" with frontmatter id "STORY-007"
    When the project is characterized
    Then the duplicate id count is 1
    And the duplicate group for "STORY-007" lists both real files

  Scenario: Supporting documents are not counted as migratable work items
    Given a product file "FOUNDATION.md" with no frontmatter
    And a product file "backlog/BACKLOG-INDEX.md" with no frontmatter
    And a product file "epic-034-prd-draft-v1.0-20260525.md" with no frontmatter
    And a product file "test-harness-user-personas-draft-v1.0.md" with no frontmatter
    When the project is characterized
    Then none of those files are counted as work items
    And they are reported under a documents inventory

  Scenario: Bespoke epic/story tree is recognized
    Given a product file "stories/EPIC-003/EPIC-003.md" with no frontmatter
    And a product file "stories/EPIC-003/US-DM-002.md" with no frontmatter
    And a product file "stories/EPIC-003/US-DM-002.feature"
    When the project is characterized
    Then "EPIC-003" is recognized as an epic-shaped item
    And "US-DM-002" is recognized as a story-shaped item whose parent epic is "EPIC-003"
    And "US-DM-002" records a paired feature file "stories/EPIC-003/US-DM-002.feature"

  Scenario: A project whose only duplicates are backups characterizes as clean
    Given a product tree where every duplicate id is caused only by a backup file
    When the project is characterized
    Then the duplicate id count is 0
    And v4_compliance reports no_duplicates as true

  Scenario: Backup exclusion does not change counts when there are no backups
    Given a product tree with no backup or derived files
    When the project is characterized
    Then the work-item and duplicate counts are identical to the pre-change behavior
