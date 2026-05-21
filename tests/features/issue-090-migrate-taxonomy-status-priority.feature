Feature: Status and priority remapping
  Convert legacy status and priority values to the new vocabulary.

  # --- Status ---

  Scenario Outline: Status remapping (lowercase input)
    Given a BL file with status "<legacy>"
    When the status is remapped
    Then the result is "<new>"

    Examples:
      | legacy      | new         |
      | backlog     | new         |
      | open        | active      |
      | in_progress | active      |
      | in progress | active      |
      | cancelled   | abandoned   |
      | canceled    | abandoned   |
      | complete    | done        |
      | achieved    | done        |
      | closed      | done        |
      | promoted    | superseded  |
      | proposed    | new         |

  Scenario Outline: Status remapping is case-insensitive
    Given a BL file with status "<legacy>"
    When the status is remapped
    Then the result is "<new>"

    Examples:
      | legacy      | new         |
      | BACKLOG     | new         |
      | Open        | active      |
      | DONE        | done        |
      | In_Progress | active      |
      | PROMOTED    | superseded  |

  Scenario Outline: Already-correct statuses pass through
    Given a file with status "<status>"
    When the status is remapped
    Then the result is "<status>"

    Examples:
      | status      |
      | new         |
      | ready       |
      | active      |
      | in-review   |
      | blocked     |
      | on-hold     |
      | deferred    |
      | done        |
      | declined    |
      | abandoned   |
      | superseded  |

  Scenario: Unknown status passes through with warning
    Given a file with status "custom-status"
    When the status is remapped
    Then the result is "custom-status"
    And a warning is emitted about unrecognized status

  # --- Priority ---

  Scenario Outline: Priority remapping (lowercase input)
    Given a file with priority "<legacy>"
    When the priority is remapped
    Then the result is "<new>"

    Examples:
      | legacy  | new |
      | spike   | P3  |
      | next    | P0  |
      | now     | P0  |
      | sooner  | P1  |
      | soon    | P2  |
      | later   | P3  |
      | someday | P4  |
      | high    | P1  |
      | medium  | P2  |
      | low     | P3  |
      | p0      | P0  |
      | p1      | P1  |
      | p2      | P2  |
      | p3      | P3  |
      | p4      | P4  |

  Scenario Outline: Priority remapping is case-insensitive
    Given a file with priority "<legacy>"
    When the priority is remapped
    Then the result is "<new>"

    Examples:
      | legacy  | new |
      | SPIKE   | P3  |
      | High    | P1  |
      | P0      | P0  |
      | SOONER  | P1  |

  Scenario: Unknown priority passes through with warning
    Given a file with priority "critical"
    When the priority is remapped
    Then the result is "critical"
    And a warning is emitted about unrecognized priority

  Scenario: Missing priority field produces None
    Given a file with no priority field
    When the priority is remapped
    Then the result is None

  Scenario: Empty priority string produces None
    Given a file with priority ""
    When the priority is remapped
    Then the result is None

  # --- Workflow type ---

  Scenario Outline: Workflow type inference from type field
    Given a file with type "<type>"
    When workflow type is inferred
    Then the result is "<workflow>"

    Examples:
      | type     | workflow    |
      | story    | enhancement |
      | bug      | bug-fix     |
      | debt     | tech-debt   |
      | chore    | tech-debt   |
      | spike    | spike       |
      | refactor | tech-debt   |

  Scenario: Explicit workflow_type takes precedence over type field
    Given a file with workflow_type "net-new-feature" and type "story"
    When workflow type is inferred
    Then the result is "net-new-feature"

  Scenario: Type field takes precedence over title heuristic
    Given a file with type "story" and title "Fix the bug in login"
    When workflow type is inferred
    Then the result is "enhancement"

  Scenario Outline: Workflow type heuristic from title
    Given a file with no type field and title "<title>"
    When workflow type is inferred
    Then the result is "<workflow>"

    Examples:
      | title                        | workflow    |
      | Spike: evaluate voice SDK    | spike       |
      | Research caching strategies   | spike       |
      | Evaluate new auth provider    | spike       |
      | Fix broken login flow         | bug-fix     |
      | Bug in payment processing     | bug-fix     |
      | Add user invitation feature   | enhancement |

  Scenario: Default workflow type when no signals
    Given a file with no type, no workflow_type, and title "Some task"
    When workflow type is inferred
    Then the result is "enhancement"
