Feature: Plan building
  Compute migration plan with correct routing, frontmatter, and safety checks.

  Background:
    Given a project directory with product base ".sweetclaude/product"
    And an empty collision map

  # --- Routing ---

  Scenario: BL with terminal status routes to roadmap/issues/done/
    Given BL-050.md with status "done" and title "Old feature"
    When build_plan() is called
    Then ISSUE-050 routes to "roadmap/issues/done/ISSUE-050-old-feature.md"
    And the action is "migrate"

  Scenario: BL with non-terminal status and epic routes to roadmap/issues/
    Given BL-042.md with status "active" and epic "EP-001"
    When build_plan() is called
    Then ISSUE-042 routes to "roadmap/issues/ISSUE-042-*.md"

  Scenario: BL with non-terminal status and milestone but no epic routes to roadmap/issues/
    Given BL-042.md with status "active" and milestone "MS-007" and no epic
    When build_plan() is called
    Then ISSUE-042 routes to "roadmap/issues/ISSUE-042-*.md"

  Scenario: BL with non-terminal status and no epic or milestone routes to backlog/
    Given BL-070.md with status "new" and no epic or milestone
    When build_plan() is called
    Then ISSUE-070 routes to "backlog/ISSUE-070-*.md"

  Scenario: BL with PROMOTED status and parseable target
    Given BL-082.md with status "promoted" and promoted_to "EP-009 (v4.1)"
    When build_plan() is called
    Then ISSUE-082 has status "superseded"
    And frontmatter contains superseded_by "EP-009"
    And the dest directory is deterministic (backlog/ since no epic/milestone on the BL itself)

  Scenario: BL with PROMOTED status and unparseable target
    Given BL-099.md with status "promoted" and promoted_to "some narrative text"
    When build_plan() is called
    Then frontmatter superseded_by is "some narrative text"
    And a warning is emitted about non-standard superseded_by value

  Scenario: BL with PROMOTED status and no promoted_to field
    Given BL-099.md with status "promoted" and no promoted_to field
    When build_plan() is called
    Then ISSUE-099 has status "superseded"
    And frontmatter does not contain superseded_by

  Scenario: STORY routes to roadmap/issues/done/
    Given STORY-015.md with status "done"
    When build_plan() is called
    Then the dest is in "roadmap/issues/done/"
    And the action is "migrate"

  Scenario: Colliding STORY uses remapped number
    Given STORY-015.md exists
    And collision map has "STORY-15" -> "ISSUE-87"
    When build_plan() is called
    Then the new_id is "ISSUE-87"
    And frontmatter contains migrated_from "STORY-15"

  Scenario: spike-BL routes to backlog with type spike
    Given spike-BL-016-gstack.md exists in spike-reports/
    When build_plan() is called
    Then it routes to "backlog/ISSUE-016-*.md"
    And frontmatter type is "spike"
    And frontmatter contains migrated_from "spike-BL-016"

  Scenario: I-N file is archived as-is without parsing frontmatter
    Given I-001-duplicate.md exists with non-standard fields (Effort, Sprint, Source)
    When build_plan() is called
    Then it routes to "backlog/archived/I-001-duplicate.md"
    And the action is "archive"
    And the frontmatter dict is empty (file copied verbatim)

  Scenario: RM-N file is retired
    Given RM-001-mvp.md exists
    When build_plan() is called
    Then the action is "retire"

  Scenario: MS-N file is restructured
    Given MS-007.md exists with markdown bold format
    When build_plan() is called
    Then it routes to "roadmap/milestones/MS-007-*.md"
    And the action is "restructure"

  Scenario: MS-N with proposed status is restructured, not done-routed
    Given MS-007.md with status "proposed"
    When build_plan() is called
    Then it routes to "roadmap/milestones/MS-007-*.md"
    And frontmatter status is "new"

  Scenario: EP-N file already in new format — restructure only
    Given EP-001.md exists with YAML frontmatter and no legacy refs in body
    When build_plan() is called
    Then it routes to "roadmap/epics/EP-001-*.md"
    And the action is "restructure"
    And no rewrite-refs move is generated for EP-001

  Scenario: EP-N file with legacy refs in body gets restructure + rewrite-refs
    Given EP-001.md with body containing "Blocks: BL-081"
    When build_plan() is called
    Then a "restructure" move and a "rewrite-refs" move are both generated for EP-001
    And the rewrite-refs move is ordered after the restructure move

  # --- Slug ---

  Scenario: Slug sanitization removes special characters
    Given BL-042.md with title "Widget builder (v2.0) — improved!"
    When build_plan() is called
    Then the slug portion of dest contains only lowercase alphanumeric and hyphens

  Scenario: Slug truncates to 60 characters with no trailing dash
    Given BL-042.md with a title that produces a 75-character slug
    When build_plan() is called
    Then the slug portion is exactly 60 characters
    And it does not end with a hyphen

  Scenario: Title exactly 60 characters passes through unchanged
    Given BL-042.md with a title that produces a 60-character slug
    When build_plan() is called
    Then the slug portion is the full 60-character string

  Scenario: Empty title falls back to new_id
    Given BL-042.md with no title
    When build_plan() is called
    Then the slug portion of dest is "issue-042"

  Scenario: Title of all special characters falls back to new_id
    Given BL-042.md with title "---!!!"
    When build_plan() is called
    Then the slug portion of dest is "issue-042"

  Scenario: Unicode-only title falls back to new_id
    Given BL-042.md with title "导航功能"
    When build_plan() is called
    Then the slug portion of dest is "issue-042"

  # --- Safety checks ---

  Scenario: Duplicate dest paths abort plan
    Given BL-001.md and BL-002.md with titles that truncate to the same 60-char slug
    When build_plan() is called
    Then it raises an error about duplicate dest paths
    And both conflicting paths are named in the error

  Scenario: Duplicate new_ids abort plan
    Given BL-016.md and spike-BL-016.md both exist
    And both would map to ISSUE-016
    When build_plan() is called
    Then it raises an error about duplicate new_id "ISSUE-016"

  Scenario: Dest path escaping project root aborts plan
    Given a crafted file that would produce a dest outside project_dir
    When build_plan() is called
    Then it raises an error about path containment

  Scenario: Source path containment is also checked
    Given a source file that resolves outside project_dir (e.g., symlink)
    When build_plan() is called
    Then it raises an error about source path containment

  # --- Frontmatter ---

  Scenario: depends_on references are remapped via id_map
    Given BL-042.md with depends_on [BL-040, STORY-015]
    And id_map has BL-040 -> ISSUE-040, STORY-15 -> ISSUE-87
    When build_plan() is called
    Then frontmatter depends_on is ["ISSUE-040", "ISSUE-087"]

  Scenario: depends_on cross-prefix collision remapping
    Given BL-015.md with depends_on [STORY-015]
    And collision map has STORY-15 -> ISSUE-87
    When build_plan() is called
    Then ISSUE-015 frontmatter depends_on is ["ISSUE-087"]

  Scenario: superseded_by is cleaned to bare ID
    Given BL-082.md with promoted_to "EP-009 (v4.1)"
    When build_plan() is called
    Then frontmatter superseded_by is "EP-009"

  Scenario: migrated_from is set when ID changes
    Given BL-042.md
    When build_plan() is called
    Then frontmatter contains migrated_from "BL-042"

  Scenario: closed_date is preserved
    Given BL-050.md with closed_date "2026-05-02"
    When build_plan() is called
    Then frontmatter closed_date is "2026-05-02"

  Scenario: Unrecognized fields from source are preserved in frontmatter
    Given STORY-015.md with extra fields shape "small" and phase "ship"
    When build_plan() is called
    Then frontmatter contains shape "small"
    And frontmatter contains phase "ship"

  # --- Reference rewriting ---

  Scenario: Milestone body refs are rewritten
    Given MS-007.md with body containing "See BL-042 and STORY-015"
    And id_map has BL-042 -> ISSUE-042, STORY-15 -> ISSUE-87
    When build_plan() is called
    Then a rewrite-refs move exists for MS-007
    And its body contains "See ISSUE-042 and ISSUE-87"

  Scenario: All legacy prefix refs in body are rewritten
    Given MS-007.md with body containing "CHORE-010, BUG-003, DEBT-005, I-001"
    And id_map has entries for all four
    When build_plan() is called
    Then a rewrite-refs move rewrites all four to ISSUE-NNN

  Scenario: Non-milestone file with body legacy refs gets rewrite-refs move
    Given BL-042.md with body containing "see BL-010 for context"
    And id_map has BL-010 -> ISSUE-010
    When build_plan() is called
    Then a rewrite-refs move exists for the migrated ISSUE-042 file

  Scenario: Refs not in id_map are left as-is with warning
    Given MS-007.md with body containing "See CHORE-999"
    And CHORE-999 is not in id_map
    When build_plan() is called
    Then the body still contains "CHORE-999"
    And a warning is added about unresolved reference CHORE-999

  Scenario: Word-boundary matching prevents partial matches
    Given MS-007.md with body containing "NOTABLE-42 should not match"
    And id_map has BL-42 -> ISSUE-042
    When build_plan() is called
    Then the body still contains "NOTABLE-42"

  Scenario: rewrite-refs moves are ordered after restructure for same file
    Given MS-007.md needs both restructure and rewrite-refs
    When build_plan() is called
    Then the restructure PlannedMove appears before the rewrite-refs PlannedMove in plan.moves
