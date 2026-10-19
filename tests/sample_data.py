"""Deterministic test inputs shared by the research test suite.

The Gherkin texts mirror the shape Component 2 produces (Feature / Scenario /
Given / When / Then). Requirement rows mirror Component 1's
GET /api/v1/pipeline/iterations/{id}/requirements-with-stories `items` shape.
"""

LOGIN_HIGH = """Feature: User Login
  Scenario: Successful login with valid credentials
    Given a registered user "alice@example.com" exists with password "Secret123"
    When the user enters email "alice@example.com" and password "Secret123" and clicks "Login"
    Then the system returns status code 200 and redirects to the "Dashboard" page
  Scenario: Login rejected with wrong password
    Given a registered user "alice@example.com" exists with password "Secret123"
    When the user enters email "alice@example.com" and password "Wrong999" and clicks "Login"
    Then the system displays the error "Invalid email or password"
"""

LOGIN_LOW = """Feature: Login
  Scenario: login works
    When some action is performed properly on the login
"""

LOGIN_AC = [
    "The user can login with a valid email and password",
    "If the password is wrong, the system displays an invalid email or password error",
]
LOCKOUT_AC = "The account is locked after five failed login attempts"

CHECKOUT_TEXT = """Feature: Checkout
  Scenario: Pay with a saved card
    Given the customer has 2 items in the cart totalling "49.99"
    When the customer pays with the saved card ending "4242"
    Then the order is confirmed and a receipt email is sent
"""


def requirement(req_id, story_id, priority="Must", acs=None, text=None, title=None, story_text=None):
    return {
        "requirement_id": req_id,
        "requirement_text": text or f"Requirement {req_id}",
        "requirement_type": "Functional",
        "requirement_status": "approved",
        "meeting_title": "Sprint planning",
        "user_story_id": story_id,
        "user_story_title": title or f"Story {story_id}",
        "user_story_text": story_text or "As a registered user, I want to log in so that I can use the system",
        "priority": priority,
        "user_story_status": "approved",
        "acceptance_criteria": list(acs) if acs is not None else [],
    }


def make_test_case(tc_id, story_id, description, status="pending", title=None):
    return {"story_id": story_id, "id": tc_id, "title": title or tc_id, "description": description, "status": status}
