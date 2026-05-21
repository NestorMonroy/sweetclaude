Feature: Collision detection
  Handle overlapping number spaces deterministically.

  # --- Detection ---

  Scenario: No collisions when number spaces don't overlap
    Given BL-001.md and BL-002.md exist
    And STORY-003.md exists
    When detect_collisions() is called
    Then the collision map is empty
    And STORY-003 keeps its number as ISSUE-003

  Scenario: Colliding STORY gets renumbered
    Given BL-015.md and BL-016.md exist (max BL number is 86)
    And STORY-015.md exists in done/
    When detect_collisions() is called
    Then the collision map contains "STORY-15" -> "ISSUE-87"

  Scenario: Multiple collisions renumbered sequentially by STORY number
    Given BL files exist with numbers 15, 16, 17 (max BL is 86)
    And STORY-015.md, STORY-016.md, STORY-017.md exist
    When detect_collisions() is called
    Then the collision map is:
      | old       | new       |
      | STORY-15  | ISSUE-87  |
      | STORY-16  | ISSUE-88  |
      | STORY-17  | ISSUE-89  |

  Scenario: Non-colliding STORY keeps its number
    Given BL files exist with numbers 1 through 86
    And STORY-100.md exists
    When detect_collisions() is called
    Then the collision map is empty
    And STORY-100 maps to ISSUE-100

  Scenario: No BL files exist — STORY numbers kept as-is
    Given no BL files exist
    And STORY-015.md and STORY-016.md exist
    When detect_collisions() is called
    Then the collision map is empty
    And STORY-015 maps to ISSUE-015
    And STORY-016 maps to ISSUE-016

  Scenario: Determinism — same input produces same output
    Given BL files with numbers 15, 16 (max BL is 86)
    And STORY-015.md and STORY-016.md exist
    When detect_collisions() is called twice with identical input
    Then both calls return identical collision maps

  Scenario: STORY number collides with remapped number of another STORY
    Given BL files with max number 86
    And STORY-015.md exists (collides with BL-015, remapped to ISSUE-87)
    And STORY-087.md exists (does not collide with any BL)
    When detect_collisions() is called
    Then STORY-015 maps to ISSUE-87
    And STORY-087 keeps its number as ISSUE-087

  Scenario: Collision map key format uses unpadded numbers
    Given BL-015.md and STORY-015.md exist
    When detect_collisions() is called
    Then the collision map key is "STORY-15" (not "STORY-015")
    And the value is "ISSUE-87" (not "ISSUE-087")

  Scenario: Duplicate STORY files with same number produce error
    Given STORY-015-alpha.md and STORY-015-beta.md both exist
    When detect_collisions() is called
    Then it raises an error about duplicate STORY number 15

  # --- Persistence ---

  Scenario: Collision map is persisted to disk
    Given no collision map file exists
    And BL-015.md and STORY-015.md exist
    When detect_collisions() is called and persisted
    Then taxonomy-collision-map.yaml is written to .sweetclaude/state/
    And it contains the STORY-15 mapping

  Scenario: Persisted collision map is reused with correct mappings
    Given taxonomy-collision-map.yaml exists with "STORY-15" -> "ISSUE-87"
    When load_collision_map() is called
    Then it returns the map with "STORY-15" -> "ISSUE-87"

  Scenario: Empty collision map YAML is treated as no persisted map
    Given taxonomy-collision-map.yaml exists but is empty
    When load_collision_map() is called
    Then it returns None
    And detect_collisions() will be called by plan()

  Scenario: Invalid collision map YAML is treated as no persisted map
    Given taxonomy-collision-map.yaml exists with invalid YAML content
    When load_collision_map() is called
    Then it returns None
    And a warning is emitted about corrupt collision map

  # --- Locking ---

  Scenario: Collision map is locked when execute begins
    Given taxonomy-collision-map.yaml exists without locked flag
    When execute() begins
    Then taxonomy-collision-map.yaml is updated with "locked: true"

  Scenario: Locked collision map is never regenerated
    Given taxonomy-collision-map.yaml exists with "locked: true"
    And some source files have been deleted by a partial run
    When plan() is called
    Then the persisted map is used
    And the plan's collision assignments match the locked map
