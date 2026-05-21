Feature: Reporting skills taxonomy update (ISSUE-94)

  The three reporting skills (big-picture, status, recap) must work with the
  post-migration taxonomy: .sweetclaude/product/ paths, MS/EP/ISSUE prefixes,
  cache.py queries, and milestone-based hierarchy.

  # --------------------------------------------------------------------------
  # Cache: query_summary milestone status breakdown
  # --------------------------------------------------------------------------

  Scenario: query_summary returns milestones.by_status breakdown
    Given a project with two milestones: MS-001 (status active) and MS-002 (status done)
    When I rebuild the cache and call query_summary
    Then the summary contains milestones.by_status with {"active": 1, "done": 1}

  Scenario: query_summary milestones.by_status is empty when no milestones exist
    Given a project with only backlog issues and no milestones
    When I rebuild the cache and call query_summary
    Then the summary contains milestones.by_status as an empty dict
    And milestones.total equals 0

  # --------------------------------------------------------------------------
  # big-picture: no retired prefixes or old paths
  # --------------------------------------------------------------------------

  Scenario: big-picture SKILL.md contains no references to docs/product/
    Given the file skills/big-picture/SKILL.md
    Then it must not contain the string "docs/product/"

  Scenario: big-picture SKILL.md contains no REL- prefix in rendering templates
    Given the file skills/big-picture/SKILL.md
    Then it must not contain the string "REL-"

  Scenario: big-picture SKILL.md contains no STORY- prefix in rendering templates
    Given the file skills/big-picture/SKILL.md
    Then it must not contain the string "STORY-"

  Scenario: big-picture SKILL.md renders MS- prefix for top-level roadmap nodes
    Given the file skills/big-picture/SKILL.md
    Then it must contain the string "MS-"

  Scenario: big-picture SKILL.md renders ISSUE- prefix for work items
    Given the file skills/big-picture/SKILL.md
    Then it must contain the string "ISSUE-"

  Scenario: big-picture SKILL.md uses milestones-compact query
    Given the file skills/big-picture/SKILL.md
    Then it must contain the string "milestones-compact"

  Scenario: big-picture SKILL.md summary line says milestones not releases
    Given the file skills/big-picture/SKILL.md
    Then it must contain the string "milestones"
    And it must not contain the phrase "total releases"

  Scenario: big-picture roadmap detection checks .sweetclaude path
    Given the file skills/big-picture/SKILL.md
    Then it must contain the string ".sweetclaude/product/roadmap/epics/"

  # --------------------------------------------------------------------------
  # status: no retired prefixes or old paths, uses cache queries
  # --------------------------------------------------------------------------

  Scenario: status SKILL.md contains no RM-* glob pattern
    Given the file skills/status/SKILL.md
    Then it must not contain the string "RM-*.md"

  Scenario: status SKILL.md contains no I-* glob pattern
    Given the file skills/status/SKILL.md
    Then it must not contain the string "I-*.md"

  Scenario: status SKILL.md contains no BL-* glob pattern
    Given the file skills/status/SKILL.md
    Then it must not contain the string "BL-*.md"

  Scenario: status SKILL.md contains no STORY- prefix
    Given the file skills/status/SKILL.md
    Then it must not contain the string "STORY-"

  Scenario: status SKILL.md references cache.py for data
    Given the file skills/status/SKILL.md
    Then it must contain the string "cache.py"

  Scenario: status SKILL.md has migration guard
    Given the file skills/status/SKILL.md
    Then it must contain a guard that checks for .sweetclaude/product/ existence
    And it must contain the string "sweetclaude:update" or "migrate"

  Scenario: status SKILL.md uses correct terminal statuses
    Given the file skills/status/SKILL.md
    Then it must not contain the string "'complete'" as a done status
    And it must not contain the string "'achieved'" as a done status
    And it must not contain the string "'closed'" as a done status

  # --------------------------------------------------------------------------
  # big-picture: migration guard
  # --------------------------------------------------------------------------

  Scenario: big-picture SKILL.md has migration guard
    Given the file skills/big-picture/SKILL.md
    Then it must contain a guard that checks for .sweetclaude/product/ existence

  # --------------------------------------------------------------------------
  # recap: no retired prefixes
  # --------------------------------------------------------------------------

  Scenario: recap SKILL.md contains no retired prefixes
    Given the file skills/recap/SKILL.md
    Then it must not contain the string "REL-"
    And it must not contain the string "RM-"
    And it must not contain the string "BL-"
    And it must not contain the string "STORY-"
