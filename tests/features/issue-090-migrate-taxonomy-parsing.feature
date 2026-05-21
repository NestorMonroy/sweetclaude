Feature: File parsing
  Extract metadata from both YAML frontmatter and markdown bold formats.

  # --- YAML frontmatter ---

  Scenario: Parse YAML frontmatter file
    Given a file with content:
      """
      ---
      id: BL-042
      title: Widget builder
      status: open
      priority: P2
      type: enhancement
      epic: EP-001
      milestone: MS-007
      depends_on: [BL-040, BL-041]
      created: 2026-05-01
      updated: 2026-05-15
      ---

      # BL-042: Widget builder

      Build the widget builder component.
      """
    When parse_files() processes this file
    Then parsed["id"] is "BL-042"
    And parsed["title"] is "Widget builder"
    And parsed["status"] is "open"
    And parsed["priority"] is "P2"
    And parsed["epic"] is "EP-001"
    And parsed["depends_on"] is ["BL-040", "BL-041"]
    And parsed["body"] contains "Build the widget builder component."

  Scenario: Parse markdown bold format file
    Given a file with content:
      """
      # BL-042: Widget builder

      **Status:** Open
      **Priority:** P2
      **Epic:** EP-001

      Build the widget builder component.
      """
    When parse_files() processes this file
    Then parsed["title"] is "Widget builder"
    And parsed["status"] is "open"
    And parsed["priority"] is "P2"
    And parsed["epic"] is "EP-001"
    And parsed["body"] contains "Build the widget builder component."

  Scenario: YAML frontmatter takes precedence over markdown bold
    Given a file with content:
      """
      ---
      id: BL-042
      title: YAML title
      status: active
      ---

      # BL-042: Markdown title

      **Status:** Open
      """
    When parse_files() processes this file
    Then parsed["title"] is "YAML title"
    And parsed["status"] is "active"

  # --- Status edge cases ---

  Scenario: Parse file with date-embedded status
    Given a file with content:
      """
      # BL-050: Old feature

      **Status:** DONE — 2026-05-02
      **Priority:** P3
      """
    When parse_files() processes this file
    Then parsed["status"] is "done"
    And parsed["closed_date"] is "2026-05-02"

  Scenario: Parse file with date-embedded status using em-dash without spaces
    Given a file with content:
      """
      # BL-050: Old feature

      **Status:** DONE—2026-05-02
      """
    When parse_files() processes this file
    Then parsed["status"] is "done"
    And parsed["closed_date"] is "2026-05-02"

  Scenario: Parse file with reason-embedded status
    Given a file with content:
      """
      # BL-060: Deferred item

      **Status:** deferred — low ROI for current phase
      **Priority:** P4
      """
    When parse_files() processes this file
    Then parsed["status"] is "deferred"
    And parsed["deferred_reason"] is "low ROI for current phase"

  Scenario: Parse PROMOTED file with target
    Given a file with content:
      """
      # BL-082: Tracked workflows

      **Status:** PROMOTED
      **Promoted to:** EP-009 (v4.1)
      """
    When parse_files() processes this file
    Then parsed["status"] is "promoted"
    And parsed["promoted_to"] is "EP-009 (v4.1)"

  Scenario: Parse PROMOTED file with no promoted_to field
    Given a file with content:
      """
      # BL-099: Orphan promoted

      **Status:** PROMOTED
      """
    When parse_files() processes this file
    Then parsed["status"] is "promoted"
    And parsed["promoted_to"] is None

  # --- Case sensitivity ---

  Scenario: Status values are lowercased before remap
    Given a file with content:
      """
      # BL-084: Case test

      **Status:** BACKLOG
      **Priority:** P3
      """
    When parse_files() processes this file
    Then parsed["status"] is "backlog"

  Scenario: Priority values are lowercased before remap
    Given a file with content:
      """
      # BL-001: Spike

      **Status:** Open
      **Priority:** SPIKE
      """
    When parse_files() processes this file
    Then parsed["priority"] is "spike"

  # --- depends_on formats ---

  Scenario: depends_on as YAML inline list
    Given a YAML frontmatter file with depends_on: [BL-040, BL-041]
    When parse_files() processes this file
    Then parsed["depends_on"] is ["BL-040", "BL-041"]

  Scenario: depends_on as bare scalar string normalized to list
    Given a YAML frontmatter file with depends_on: BL-040
    When parse_files() processes this file
    Then parsed["depends_on"] is ["BL-040"]

  Scenario: depends_on as YAML block sequence
    Given a YAML frontmatter file with:
      """
      depends_on:
        - BL-040
        - BL-041
      """
    When parse_files() processes this file
    Then parsed["depends_on"] is ["BL-040", "BL-041"]

  # --- Robustness ---

  Scenario: Empty YAML frontmatter falls back to bold parsing
    Given a file with content:
      """
      ---
      ---

      # BL-042: Widget builder

      **Status:** Open
      """
    When parse_files() processes this file
    Then parsed["title"] is "Widget builder"
    And parsed["status"] is "open"

  Scenario: Malformed YAML frontmatter falls back to bold parsing
    Given a file with content:
      """
      ---
      id: BL-042
      title: "unclosed quote
      status: [invalid: yaml
      ---

      # BL-042: Widget builder

      **Status:** Open
      """
    When parse_files() processes this file
    Then parsed["title"] is "Widget builder"
    And parsed["status"] is "open"
    And a warning is emitted about YAML parse failure

  Scenario: Body containing HR separator is not re-parsed as frontmatter
    Given a file with content:
      """
      # BL-082: Tracked workflows

      **Status:** Open

      First section content.

      ---

      ## Feature Request: Second Document

      Second section content.
      """
    When parse_files() processes this file
    Then parsed["body"] contains "First section content."
    And parsed["body"] contains "Feature Request: Second Document"
    And parsed["body"] contains "Second section content."

  Scenario: Bold patterns inside body code blocks are not parsed as metadata
    Given a file with content:
      """
      # MS-007: Tracked workflows

      **Status:** Active

      ## Appendix A

      ```
      **Status:** done
      **Priority:** P0
      ```

      Regular body text after code block.
      """
    When parse_files() processes this file
    Then parsed["status"] is "active"
    And parsed["body"] contains "**Status:** done"
    And parsed["body"] contains "Regular body text after code block."

  Scenario: Bold patterns after first blank line are body not metadata
    Given a file with content:
      """
      # MS-007: Tracked workflows

      **Status:** Active
      **Priority:** P2

      **Status:** This is a body line that looks like metadata
      """
    When parse_files() processes this file
    Then parsed["status"] is "active"
    And parsed["body"] contains "**Status:** This is a body line"

  # --- Unrecognized fields ---

  Scenario: Unrecognized YAML frontmatter fields are preserved
    Given a file with content:
      """
      ---
      id: STORY-015
      title: Orchestrator state machine
      status: done
      workflow_type: enhancement
      shape: small
      phase: ship
      pr: "#52"
      milestone: MS-007
      ---

      Story body.
      """
    When parse_files() processes this file
    Then parsed["workflow_type"] is "enhancement"
    And parsed["shape"] is "small"
    And parsed["phase"] is "ship"
    And parsed["pr"] is "#52"

  Scenario: Unrecognized bold-format fields are preserved
    Given a file with content:
      """
      # MS-001: Public Launch

      **Status:** Proposed
      **mode_introduced:** agile
      **Replaces:** MS-000-alpha
      """
    When parse_files() processes this file
    Then parsed["mode_introduced"] is "agile"
    And parsed["replaces"] is "MS-000-alpha"

  # --- Hash and misc ---

  Scenario: SHA-256 hash is computed over raw bytes
    Given a file with known byte content
    When parse_files() processes this file
    Then parsed["source_hash"] equals hashlib.sha256(raw_bytes).hexdigest()

  Scenario: File with no body produces empty string body
    Given a file with only YAML frontmatter and no content after
    When parse_files() processes this file
    Then parsed["body"] is ""

  Scenario: File with no parseable metadata at all
    Given a file with content:
      """
      # MS-009: Planning Workflows

      Just a heading and some prose, no metadata fields.
      """
    When parse_files() processes this file
    Then parsed["title"] is "Planning Workflows"
    And parsed["status"] is None
    And a warning is emitted about missing metadata
