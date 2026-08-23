"""Populates the database with sample requirements, acceptance criteria,
test cases, and code coverage so the RTM/dashboard has data on first run.

Run with:  python -m app.seed
"""

from app import models, services
from app.database import Base, SessionLocal, engine
from app.ml.predict import predict_quality
from app.ml.weights import FEATURE_ORDER, QUALITY_REJECT_THRESHOLD

SAMPLE_DATA = [
    {
        "title": "User authentication and login",
        "description": "Users must be able to securely log in with email/password and receive an auth token.",
        "source": "Product Spec v2.1",
        "req_type": "Functional",
        "wbs_deliverables": "Auth Service Module",
        "acceptance_criteria": [
            {
                "description": "Valid credentials return a signed auth token",
                "tests": [
                    {
                        "title": "test_login_valid_credentials_returns_token",
                        "assertion_strength": 90, "coverage_percent": 88, "boundary_coverage": 70,
                        "error_handling": 80, "mutation_resistance": 75,
                        "coverage": [("auth_service.py", 91.0), ("token_utils.py", 85.0)],
                    },
                    {
                        "title": "test_login_valid_credentials_token_signature",
                        "assertion_strength": 85, "coverage_percent": 82, "boundary_coverage": 60,
                        "error_handling": 70, "mutation_resistance": 65,
                        "coverage": [("auth_service.py", 89.0)],
                    },
                ],
            },
            {
                "description": "Invalid credentials are rejected with a 401 and no token is issued",
                "tests": [
                    {
                        "title": "test_login_invalid_password_returns_401",
                        "assertion_strength": 40, "coverage_percent": 35, "boundary_coverage": 20,
                        "error_handling": 30, "mutation_resistance": 25,
                        "coverage": [("auth_service.py", 40.0)],
                    }
                ],
            },
            {
                "description": "Account is locked after 5 consecutive failed login attempts",
                "tests": [],
            },
        ],
    },
    {
        "title": "Checkout payment processing",
        "description": "Users must be able to pay for their cart via credit card at checkout, with refund support.",
        "source": "Stakeholder Interview",
        "req_type": "Functional",
        "wbs_deliverables": "Payment Gateway Integration",
        "acceptance_criteria": [
            {
                "description": "Successful payment charges the card and creates an order record",
                "tests": [
                    {
                        "title": "test_checkout_payment_success_creates_order",
                        "assertion_strength": 92, "coverage_percent": 90, "boundary_coverage": 85,
                        "error_handling": 88, "mutation_resistance": 80,
                        "coverage": [("payment_gateway.py", 93.0), ("order_service.py", 87.0)],
                    }
                ],
            },
            {
                "description": "Declined card shows an actionable error message and does not create an order",
                "tests": [],
            },
            {
                "description": "Refund reverses the charge and updates order status",
                "tests": [
                    {
                        "title": "test_refund_reverses_charge",
                        "assertion_strength": 55, "coverage_percent": 45, "boundary_coverage": 30,
                        "error_handling": 40, "mutation_resistance": 35,
                        "coverage": [("payment_gateway.py", 42.0)],
                    }
                ],
            },
        ],
    },
    {
        "title": "Product search and filtering",
        "description": "Users can search the product catalog and filter results by category, price, and rating.",
        "source": "Product Spec v2.1",
        "req_type": "Functional",
        "wbs_deliverables": "Search Index Service",
        "acceptance_criteria": [
            {
                "description": "Search returns relevant results ranked by relevance",
                "tests": [
                    {
                        "title": "test_search_returns_ranked_results",
                        "assertion_strength": 78, "coverage_percent": 75, "boundary_coverage": 55,
                        "error_handling": 60, "mutation_resistance": 50,
                        "coverage": [("search_index.py", 80.0)],
                    },
                    {
                        "title": "test_search_results_ranked_by_relevance",
                        "assertion_strength": 76, "coverage_percent": 73, "boundary_coverage": 52,
                        "error_handling": 58, "mutation_resistance": 48,
                        "coverage": [("search_index.py", 78.0)],
                    },
                ],
            },
            {
                "description": "Filtering by price range narrows results correctly",
                "tests": [
                    {
                        "title": "test_filter_by_price_range",
                        "assertion_strength": 82, "coverage_percent": 85, "boundary_coverage": 90,
                        "error_handling": 70, "mutation_resistance": 60,
                        "coverage": [("filter_service.py", 88.0)],
                    }
                ],
            },
        ],
    },
    {
        "title": "Order status notifications",
        "description": "Users receive email notifications when their order status changes (shipped, delivered).",
        "source": "Customer Support Feedback",
        "req_type": "Non-Functional",
        "wbs_deliverables": "Notification Service",
        "acceptance_criteria": [
            {
                "description": "Shipping status change triggers a shipped email notification",
                "tests": [
                    {
                        "title": "test_order_shipped_sends_notification",
                        "assertion_strength": 65, "coverage_percent": 60, "boundary_coverage": 40,
                        "error_handling": 45, "mutation_resistance": 30,
                        "coverage": [("notification_service.py", 62.0)],
                    }
                ],
            },
        ],
    },
    {
        "title": "User profile management",
        "description": "Users can view and update their profile information such as name, address, and preferences.",
        "source": "Product Spec v2.1",
        "req_type": "Functional",
        "wbs_deliverables": "Profile Service",
        "acceptance_criteria": [],
    },
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.ProjectSettings).count() == 0:
            db.add(
                models.ProjectSettings(
                    project_name="TestKarts.com",
                    project_manager="Jordan Ellis",
                    project_description=(
                        "QA automation research project covering ML-based test quality "
                        "prediction and requirements traceability."
                    ),
                )
            )
            db.commit()

        if db.query(models.Requirement).count() > 0:
            print("Database already has requirement data — skipping seed. Delete rows first to reseed.")
            return

        for req_data in SAMPLE_DATA:
            requirement = models.Requirement(
                title=req_data["title"],
                description=req_data["description"],
                source=req_data.get("source", ""),
                req_type=req_data.get("req_type", ""),
                wbs_deliverables=req_data.get("wbs_deliverables", ""),
            )
            db.add(requirement)
            db.flush()

            for ac_data in req_data["acceptance_criteria"]:
                ac = models.AcceptanceCriteria(
                    requirement_id=requirement.id, description=ac_data["description"]
                )
                db.add(ac)
                db.flush()

                for test_data in ac_data["tests"]:
                    test = models.TestCase(
                        title=test_data["title"],
                        steps=f"Automated test for: {ac_data['description']}",
                        acceptance_criteria_id=ac.id,
                        assertion_strength=test_data["assertion_strength"],
                        coverage_percent=test_data["coverage_percent"],
                        boundary_coverage=test_data["boundary_coverage"],
                        error_handling=test_data["error_handling"],
                        mutation_resistance=test_data["mutation_resistance"],
                    )
                    db.add(test)
                    db.flush()

                    for module_name, pct in test_data["coverage"]:
                        db.add(
                            models.CodeCoverage(
                                test_case_id=test.id, module_name=module_name, coverage_percent=pct
                            )
                        )

                    features = {key: getattr(test, key) for key in FEATURE_ORDER}
                    score, _ = predict_quality(features)
                    test.quality_score = score
                    test.status = (
                        models.TestStatus.REJECTED
                        if score < QUALITY_REJECT_THRESHOLD
                        else models.TestStatus.APPROVED
                    )

        db.commit()

        for requirement_id in [r.id for r in db.query(models.Requirement.id).all()]:
            services.recompute_rtm_for_requirement(db, requirement_id)

        print(f"Seeded {len(SAMPLE_DATA)} requirements with acceptance criteria and test cases.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
