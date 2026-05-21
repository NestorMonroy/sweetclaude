Feature: Cache taxonomy update (ISSUE-92)
  The roadmap cache (scripts/cache.py) must be updated to scan the
  post-migration file structure, normalize messy frontmatter values,
  and return correct query results for all consumers.

  Background:
    Given a project directory with ".sweetclaude/product/" structure
    And artifact-privacy.yaml points to ".sweetclaude/product"

  # ---------------------------------------------------------------------------
  # Scan paths
  # ---------------------------------------------------------------------------

  Scenario: Rebuild scans new taxonomy paths
    Given an ISSUE file at ".sweetclaude/product/backlog/ISSUE-001-foo.md" with frontmatter:
      | id       | ISSUE-001    |
      | type     | enhancement  |
      | title    | Foo          |
      | status   | new          |
    And an ISSUE file at ".sweetclaude/product/roadmap/issues/ISSUE-002-bar.md" with frontmatter:
      | id       | ISSUE-002    |
      | type     | bug-fix      |
      | title    | Bar          |
      | status   | new          |
      | epic     | EP-001       |
    And an ISSUE file at ".sweetclaude/product/roadmap/issues/done/ISSUE-003-baz.md" with frontmatter:
      | id       | ISSUE-003    |
      | type     | spike        |
      | title    | Baz          |
      | status   | done         |
    And a milestone file at ".sweetclaude/product/roadmap/milestones/MS-001-launch.md" with frontmatter:
      | id       | MS-001       |
      | type     | milestone    |
      | title    | Launch       |
      | status   | active       |
    And an epic file at ".sweetclaude/product/roadmap/epics/EP-001-workflow.md" with frontmatter:
      | id        | EP-001      |
      | type      | epic        |
      | title     | Workflow    |
      | status    | active      |
      | milestone | MS-001      |
    When I rebuild the cache
    Then the cache contains 5 items
    And item "ISSUE-001" exists with type "enhancement"
    And item "ISSUE-002" exists with type "bug-fix"
    And item "ISSUE-003" exists with type "spike"
    And item "MS-001" exists with type "milestone"
    And item "EP-001" exists with type "epic"

  Scenario: Rebuild ignores old docs/product/ paths
    Given an ISSUE file at "docs/product/backlog/stories/STORY-001-old.md" with frontmatter:
      | id     | STORY-001 |
      | type   | story     |
      | title  | Old       |
      | status | new       |
    When I rebuild the cache
    Then the cache contains 0 items

  Scenario: Index files without frontmatter are skipped
    Given a file at ".sweetclaude/product/backlog/BACKLOG-INDEX.md" with content "# Backlog"
    And a file at ".sweetclaude/product/issues/ISSUES-INDEX.md" with content "# Issues"
    When I rebuild the cache
    Then the cache contains 0 items

  Scenario: Archived files are included in cache
    Given an archived file at ".sweetclaude/product/backlog/archived/I-021-spike.md" with frontmatter:
      | id     | I-021    |
      | type   | spike    |
      | title  | Old spike|
      | status | done     |
    When I rebuild the cache
    Then the cache contains 1 item
    And item "I-021" exists with type "spike"

  # ---------------------------------------------------------------------------
  # Status normalization
  # ---------------------------------------------------------------------------

  Scenario: Status with embedded date is normalized to bare keyword
    Given an ISSUE file at ".sweetclaude/product/roadmap/issues/done/ISSUE-023-worktree.md" with frontmatter:
      | id     | ISSUE-023              |
      | type   | enhancement            |
      | title  | Worktree               |
      | status | done (2026-05-02)      |
    When I rebuild the cache
    Then item "ISSUE-023" has status "done"

  Scenario: Status with em-dash date is normalized
    Given an ISSUE file at ".sweetclaude/product/roadmap/issues/done/ISSUE-009-routing.md" with frontmatter:
      | id     | ISSUE-009                 |
      | type   | enhancement               |
      | title  | Routing                   |
      | status | done — 2026-05-02         |
    When I rebuild the cache
    Then item "ISSUE-009" has status "done"

  Scenario: Status with parenthetical note is normalized
    Given an ISSUE file at ".sweetclaude/product/roadmap/issues/done/ISSUE-032-demo.md" with frontmatter:
      | id     | ISSUE-032                                           |
      | type   | enhancement                                         |
      | title  | Demo                                                |
      | status | done (bl-032 remotion demo video carried to ms-005) |
    When I rebuild the cache
    Then item "ISSUE-032" has status "done"

  Scenario: Normalized done items excluded from backlog query
    Given an ISSUE file at ".sweetclaude/product/backlog/ISSUE-010-open.md" with frontmatter:
      | id     | ISSUE-010    |
      | type   | enhancement  |
      | title  | Open item    |
      | status | new          |
    And an ISSUE file at ".sweetclaude/product/roadmap/issues/done/ISSUE-023-done.md" with frontmatter:
      | id     | ISSUE-023              |
      | type   | enhancement            |
      | title  | Done item              |
      | status | done (2026-05-02)      |
    When I rebuild the cache
    And I query backlog
    Then the backlog contains 1 item
    And the backlog contains "ISSUE-010"
    And the backlog does not contain "ISSUE-023"

  # ---------------------------------------------------------------------------
  # Milestone field normalization
  # ---------------------------------------------------------------------------

  Scenario: Milestone with display name is normalized to clean ID
    Given an ISSUE file at ".sweetclaude/product/roadmap/issues/ISSUE-027-decay.md" with frontmatter:
      | id        | ISSUE-027                      |
      | type      | enhancement                    |
      | title     | Decay                          |
      | status    | new                            |
      | milestone | MS-004 (Stream B)              |
    When I rebuild the cache
    Then item "ISSUE-027" has milestone "MS-004"

  Scenario: Milestone "(unassigned)" is normalized to null
    Given an ISSUE file at ".sweetclaude/product/backlog/ISSUE-025-cli.md" with frontmatter:
      | id        | ISSUE-025       |
      | type      | enhancement     |
      | title     | CLI             |
      | status    | new             |
      | milestone | (unassigned)    |
    When I rebuild the cache
    Then item "ISSUE-025" has no milestone

  Scenario: Milestone "TBD" is normalized to null
    Given an ISSUE file at ".sweetclaude/product/backlog/ISSUE-036-test.md" with frontmatter:
      | id        | ISSUE-036  |
      | type      | enhancement|
      | title     | Test       |
      | status    | new        |
      | milestone | TBD        |
    When I rebuild the cache
    Then item "ISSUE-036" has no milestone

  Scenario: Clean milestone ID is preserved
    Given an ISSUE file at ".sweetclaude/product/roadmap/issues/ISSUE-050-clean.md" with frontmatter:
      | id        | ISSUE-050    |
      | type      | enhancement  |
      | title     | Clean        |
      | status    | new          |
      | milestone | MS-007       |
    When I rebuild the cache
    Then item "ISSUE-050" has milestone "MS-007"

  # ---------------------------------------------------------------------------
  # Type filter: denylist approach
  # ---------------------------------------------------------------------------

  Scenario: All workflow types appear in backlog query
    Given an ISSUE file at ".sweetclaude/product/backlog/ISSUE-001-enhance.md" with frontmatter:
      | id   | ISSUE-001   | type | enhancement |title|A|status|new|
    And an ISSUE file at ".sweetclaude/product/backlog/ISSUE-002-spike.md" with frontmatter:
      | id   | ISSUE-002   | type | spike       |title|B|status|new|
    And an ISSUE file at ".sweetclaude/product/backlog/ISSUE-003-bugfix.md" with frontmatter:
      | id   | ISSUE-003   | type | bug-fix     |title|C|status|new|
    And an ISSUE file at ".sweetclaude/product/backlog/ISSUE-004-debt.md" with frontmatter:
      | id   | ISSUE-004   | type | tech-debt   |title|D|status|new|
    And an ISSUE file at ".sweetclaude/product/backlog/ISSUE-005-feature.md" with frontmatter:
      | id   | ISSUE-005   | type | net-new-feature |title|E|status|new|
    And a milestone at ".sweetclaude/product/roadmap/milestones/MS-001-m.md" with frontmatter:
      | id | MS-001 | type | milestone | title | M | status | active |
    And an epic at ".sweetclaude/product/roadmap/epics/EP-001-e.md" with frontmatter:
      | id | EP-001 | type | epic | title | E | status | active | milestone | MS-001 |
    When I rebuild the cache
    And I query backlog
    Then the backlog contains 5 items
    And the backlog does not contain "MS-001"
    And the backlog does not contain "EP-001"

  # ---------------------------------------------------------------------------
  # Milestone hierarchy (replaces releases)
  # ---------------------------------------------------------------------------

  Scenario: Milestones-compact returns milestone-epic-issue hierarchy
    Given a milestone at ".sweetclaude/product/roadmap/milestones/MS-001-launch.md" with frontmatter:
      | id     | MS-001    |
      | type   | milestone |
      | title  | Launch    |
      | status | active    |
    And an epic at ".sweetclaude/product/roadmap/epics/EP-001-engine.md" with frontmatter:
      | id        | EP-001    |
      | type      | epic      |
      | title     | Engine    |
      | status    | active    |
      | milestone | MS-001    |
      | completion_criteria | ["Design done", "Tests pass"] |
      | completion_criteria_done | [0] |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-010-design.md" with frontmatter:
      | id     | ISSUE-010    |
      | type   | enhancement  |
      | title  | Design       |
      | status | done         |
      | epic   | EP-001       |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-011-impl.md" with frontmatter:
      | id     | ISSUE-011    |
      | type   | enhancement  |
      | title  | Implement    |
      | status | new          |
      | epic   | EP-001       |
    When I rebuild the cache
    And I query releases-compact
    Then the result contains 1 milestone
    And the first milestone has id "MS-001" and status "active"
    And the first milestone has 1 epic
    And that epic has id "EP-001" with criteria_done 1 and criteria_total 2
    And that epic has 2 stories

  Scenario: Releases-compact is an alias for milestones-compact
    Given a milestone at ".sweetclaude/product/roadmap/milestones/MS-001-m.md" with frontmatter:
      | id | MS-001 | type | milestone | title | M | status | active |
    When I rebuild the cache
    And I query releases-compact
    And I query milestones-compact
    Then both queries return identical results

  # ---------------------------------------------------------------------------
  # Summary query
  # ---------------------------------------------------------------------------

  Scenario: Summary returns milestone counts instead of release counts
    Given a milestone at ".sweetclaude/product/roadmap/milestones/MS-001-m.md" with frontmatter:
      | id | MS-001 | type | milestone | title | M | status | active |
    And a milestone at ".sweetclaude/product/roadmap/milestones/MS-002-m.md" with frontmatter:
      | id | MS-002 | type | milestone | title | N | status | done |
    And an epic at ".sweetclaude/product/roadmap/epics/EP-001-e.md" with frontmatter:
      | id | EP-001 | type | epic | title | E | status | active | milestone | MS-001 |
    And an ISSUE at ".sweetclaude/product/backlog/ISSUE-001-a.md" with frontmatter:
      | id | ISSUE-001 | type | enhancement | title | A | status | new | epic | EP-001 |
    And an ISSUE at ".sweetclaude/product/backlog/ISSUE-002-b.md" with frontmatter:
      | id | ISSUE-002 | type | spike | title | B | status | new |
    When I rebuild the cache
    And I query summary
    Then summary milestones total is 2
    And summary linked open is 1
    And summary unlinked open is 1

  # ---------------------------------------------------------------------------
  # Priority sort
  # ---------------------------------------------------------------------------

  Scenario: Backlog sorts P1 before P2 before P3
    Given an ISSUE at ".sweetclaude/product/backlog/ISSUE-001-low.md" with frontmatter:
      | id | ISSUE-001 | type | enhancement | title | Low | status | new | priority | P3 |
    And an ISSUE at ".sweetclaude/product/backlog/ISSUE-002-high.md" with frontmatter:
      | id | ISSUE-002 | type | enhancement | title | High | status | new | priority | P1 |
    And an ISSUE at ".sweetclaude/product/backlog/ISSUE-003-med.md" with frontmatter:
      | id | ISSUE-003 | type | enhancement | title | Med | status | new | priority | P2 |
    When I rebuild the cache
    And I query backlog
    Then the backlog items are ordered: ISSUE-002, ISSUE-003, ISSUE-001

  Scenario: Backlog sorts legacy priorities correctly
    Given an ISSUE at ".sweetclaude/product/backlog/ISSUE-001-later.md" with frontmatter:
      | id | ISSUE-001 | type | enhancement | title | Later | status | new | priority | later |
    And an ISSUE at ".sweetclaude/product/backlog/ISSUE-002-now.md" with frontmatter:
      | id | ISSUE-002 | type | enhancement | title | Now | status | new | priority | now |
    When I rebuild the cache
    And I query backlog
    Then the backlog items are ordered: ISSUE-002, ISSUE-001

  # ---------------------------------------------------------------------------
  # Dependencies
  # ---------------------------------------------------------------------------

  Scenario: Issue depends_on is stored in dependencies table
    Given an ISSUE at ".sweetclaude/product/backlog/ISSUE-092-cache.md" with frontmatter:
      | id         | ISSUE-092    |
      | type       | enhancement  |
      | title      | Cache update |
      | status     | new          |
      | depends_on | [ISSUE-091]  |
    When I rebuild the cache
    Then the dependencies table contains a row with item_id "ISSUE-092" and depends_on "ISSUE-091"

  Scenario: Epic depends_on is stored in dependencies table
    Given an epic at ".sweetclaude/product/roadmap/epics/EP-002-next.md" with frontmatter:
      | id         | EP-002       |
      | type       | epic         |
      | title      | Next         |
      | status     | planned      |
      | depends_on | [EP-001]     |
    When I rebuild the cache
    Then the dependencies table contains a row with item_id "EP-002" and depends_on "EP-001"

  # ---------------------------------------------------------------------------
  # next-id counter
  # ---------------------------------------------------------------------------

  Scenario: next-id for ISSUE scans all directories
    Given an ISSUE at ".sweetclaude/product/backlog/ISSUE-050-a.md" with frontmatter:
      | id | ISSUE-050 | type | enhancement | title | A | status | new |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/done/ISSUE-100-b.md" with frontmatter:
      | id | ISSUE-100 | type | enhancement | title | B | status | done |
    When I rebuild the cache
    And I query next-id with prefix "ISSUE"
    Then the next id is "ISSUE-101"

  # ---------------------------------------------------------------------------
  # Epic-issues query (replaces epic-stories)
  # ---------------------------------------------------------------------------

  Scenario: Epic-issues returns all workflow types linked to an epic
    Given an epic at ".sweetclaude/product/roadmap/epics/EP-001-e.md" with frontmatter:
      | id | EP-001 | type | epic | title | E | status | active | milestone | MS-001 |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-010-a.md" with frontmatter:
      | id | ISSUE-010 | type | enhancement | title | A | status | new | epic | EP-001 |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-011-b.md" with frontmatter:
      | id | ISSUE-011 | type | bug-fix | title | B | status | new | epic | EP-001 |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-012-c.md" with frontmatter:
      | id | ISSUE-012 | type | tech-debt | title | C | status | done | epic | EP-001 |
    When I rebuild the cache
    And I query epic-issues for "EP-001"
    Then the result contains 3 items
    And I query epic-issues for "EP-001" excluding done
    Then the result contains 2 items

  Scenario: Epic-stories is an alias for epic-issues
    Given an epic at ".sweetclaude/product/roadmap/epics/EP-001-e.md" with frontmatter:
      | id | EP-001 | type | epic | title | E | status | active |
    And an ISSUE at ".sweetclaude/product/roadmap/issues/ISSUE-010-a.md" with frontmatter:
      | id | ISSUE-010 | type | enhancement | title | A | status | new | epic | EP-001 |
    When I rebuild the cache
    And I query epic-stories for "EP-001"
    And I query epic-issues for "EP-001"
    Then both queries return identical results

  # ---------------------------------------------------------------------------
  # Schema correctness
  # ---------------------------------------------------------------------------

  Scenario: Schema has milestone column and index, not release
    When I rebuild the cache
    Then the items table has a "milestone" column
    And the items table does not have a "release" column
    And an index exists on items(milestone)

  Scenario: Dependencies table uses item_id not epic_id
    When I rebuild the cache
    Then the dependencies table has columns "item_id" and "depends_on"

  Scenario: Completion criteria table still works for epics
    Given an epic at ".sweetclaude/product/roadmap/epics/EP-001-e.md" with frontmatter:
      | id | EP-001 | type | epic | title | E | status | active |
      | completion_criteria | ["A done", "B done", "C done"] |
      | completion_criteria_done | [0, 2] |
    When I rebuild the cache
    Then EP-001 has 3 completion criteria with 2 done
