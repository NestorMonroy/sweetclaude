Feature: Doctor onboarding_state checks
  The check_onboarding_state function validates SweetClaude onboarding
  configuration: skills.yaml presence and schema version.

  Background:
    Given a healthy SweetClaude project fixture
    And a fake home directory with SweetClaude installed at version "4.0.8-beta"

  # --- Negative (healthy) ---

  Scenario: Healthy project produces no onboarding_state findings
    When check_onboarding_state runs against the project state
    Then the result contains 0 findings

  # --- skills.yaml missing ---

  Scenario: skills.yaml missing when state directory exists produces info finding
    Given skills.yaml does not exist
    When check_onboarding_state runs against the project state
    Then the findings include id "onboarding-state:missing:skills.yaml"
    And the finding with id "onboarding-state:missing:skills.yaml" has severity "info"
    And the finding with id "onboarding-state:missing:skills.yaml" has fix_type "prompted"
    And the finding with id "onboarding-state:missing:skills.yaml" fix_recipe action is "prompt"
    And the finding with id "onboarding-state:missing:skills.yaml" fix_recipe type is "bootstrap"

  Scenario: skills.yaml missing when state directory absent produces no finding
    Given the state directory does not exist
    When check_onboarding_state runs against the project state
    Then no finding has id prefix "onboarding-state:missing"

  # --- skills.yaml schema version ---

  Scenario: skills.yaml with schema_version 1 produces warning
    Given skills.yaml has schema_version 1
    When check_onboarding_state runs against the project state
    Then the findings include id "onboarding-state:schema-v1:skills.yaml"
    And the finding with id "onboarding-state:schema-v1:skills.yaml" has severity "warning"
    And the finding with id "onboarding-state:schema-v1:skills.yaml" has fix_type "prompted"

  Scenario: skills.yaml with schema_version 2 produces no finding
    When check_onboarding_state runs against the project state
    Then no finding has id prefix "onboarding-state:schema-v1"

  Scenario: skills.yaml with no schema_version key produces no schema finding
    Given skills.yaml has no schema_version key
    When check_onboarding_state runs against the project state
    Then no finding has id prefix "onboarding-state:schema-v1"

  Scenario: skills.yaml that is empty (parsed as None) produces missing finding
    Given skills.yaml is empty
    When check_onboarding_state runs against the project state
    Then the findings include id "onboarding-state:missing:skills.yaml"
