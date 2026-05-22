Feature: Doctor state_integrity checks
  The check_state_integrity function validates SweetClaude core state files:
  sweetclaude.yaml, session-state.yaml, schema version, installed version,
  and product_base path consistency.

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no state_integrity findings
    When check_state_integrity runs against the project state
    Then the result contains 0 findings

  # --- Positive (problems detected) ---

  Scenario: sweetclaude.yaml has a YAML parse error
    Given sweetclaude.yaml contains invalid YAML "{{bad: yaml: [unclosed"
    When check_state_integrity runs against the project state
    Then the result contains 1 finding
    And finding 0 has id "state-integrity:yaml-parse:sweetclaude.yaml"
    And finding 0 has severity "error"
    And finding 0 has fix_type "prompted"
    And finding 0 fix_recipe action is "prompt"

  Scenario: session-state.yaml is missing
    Given session-state.yaml does not exist
    When check_state_integrity runs against the project state
    Then the result contains 1 finding
    And finding 0 has id "state-integrity:missing:session-state.yaml"
    And finding 0 has severity "warning"
    And finding 0 has fix_type "auto"
    And finding 0 fix_recipe action is "run_script"

  Scenario: phase_schema_version is not 2
    Given sweetclaude.yaml has phase_schema_version set to 1
    When check_state_integrity runs against the project state
    Then the result contains 1 finding
    And finding 0 has id "state-integrity:schema-version:sweetclaude.yaml"
    And finding 0 has severity "warning"
    And finding 0 has fix_type "report-only"

  Scenario: installed_version drifts from installed_plugins.json
    Given sweetclaude.yaml records installed_version as "3.0.0"
    And installed_plugins.json reports version "4.0.8-beta"
    When check_state_integrity runs against the project state
    Then the result contains 1 finding
    And finding 0 has id "state-integrity:version-drift:installed_version"
    And finding 0 has severity "warning"
    And finding 0 has fix_type "auto"
    And finding 0 fix_recipe action is "write_field"
    And finding 0 fix_recipe key is "framework"
    And finding 0 fix_recipe value contains key "installed_version" with value "4.0.8-beta"

  Scenario: product_base diverges between artifact-privacy.yaml and session-state.yaml
    Given artifact-privacy.yaml sets product base_path to ".sweetclaude/product"
    And session-state.yaml sets paths.product_base to "docs/product"
    When check_state_integrity runs against the project state
    Then the result contains 1 finding
    And finding 0 has id "state-integrity:product-base-drift:session-state"
    And finding 0 has severity "warning"
    And finding 0 has fix_type "auto"
    And finding 0 fix_recipe action is "run_script"
    And finding 0 has 2 file_paths

  # --- Edge cases ---

  Scenario: sweetclaude.yaml exists but is empty (parsed as None)
    Given sweetclaude.yaml contains only "---\n---"
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:yaml-parse"
    And no finding has id prefix "state-integrity:schema-version"

  Scenario: Both artifact-privacy and session-state are missing
    Given artifact-privacy.yaml does not exist
    And session-state.yaml does not exist
    When check_state_integrity runs against the project state
    Then the result contains exactly 1 finding with id prefix "state-integrity:missing"

  # --- R1: sweetclaude.yaml does not exist on disk ---

  Scenario: sweetclaude.yaml does not exist on disk
    Given sweetclaude.yaml does not exist
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:yaml-parse"
    And no finding has id prefix "state-integrity:schema-version"
    And no finding has id prefix "state-integrity:version-drift"

  # --- R2: Multiple findings accumulate ---

  Scenario: Multiple problems produce multiple findings in a single run
    Given sweetclaude.yaml contains invalid YAML "{{bad: yaml: [unclosed"
    And session-state.yaml does not exist
    When check_state_integrity runs against the project state
    Then the result contains 2 findings
    And the findings include id "state-integrity:yaml-parse:sweetclaude.yaml"
    And the findings include id "state-integrity:missing:session-state.yaml"

  # --- R3: Trailing slash normalization ---

  Scenario: Trailing slashes on product base paths do not trigger false drift
    Given artifact-privacy.yaml sets product base_path to ".sweetclaude/product/"
    And session-state.yaml sets paths.product_base to ".sweetclaude/product"
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:product-base-drift"

  # --- R4: framework key missing ---

  Scenario: framework key missing from sweetclaude.yaml skips version drift
    Given sweetclaude.yaml has no framework key
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:version-drift"

  # --- R5: installed_plugins.json absent ---

  Scenario: installed_plugins.json absent skips version drift silently
    Given sweetclaude.yaml records installed_version as "3.0.0"
    And installed_plugins.json does not exist
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:version-drift"

  # --- R6: artifact-privacy categories is null ---

  Scenario: artifact-privacy with null categories skips product base drift
    Given artifact-privacy.yaml has categories set to null
    When check_state_integrity runs against the project state
    Then no finding has id prefix "state-integrity:product-base-drift"
