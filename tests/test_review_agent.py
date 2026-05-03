from fastapi.testclient import TestClient
from unittest import TestCase

from src.api_server import app
from src.reviewer import review_document


class ReviewAgentTest(TestCase):
    def test_passes_complete_document(self):
        result = review_document({"styled_markdown": "# Trip\n\nThis is a complete enough memory."})

        self.assertEqual(result["review_status"], "ok")
        self.assertEqual(result["issue_count"], 0)

    def test_detects_excluded_photo_reference(self):
        result = review_document(
            {
                "styled_markdown": "# Trip\n\n![secret](passport.jpg) private document",
                "excluded_photos": [{"file_name": "passport.jpg"}],
            }
        )

        self.assertEqual(result["review_status"], "needs_attention")
        self.assertGreater(result["issue_count"], 0)

    def test_health_endpoint(self):
        client = TestClient(app)

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "review_agent")

    def test_review_endpoint(self):
        client = TestClient(app)

        response = client.post(
            "/api/v1/reviews",
            json={"project_id": "sample", "styled_markdown": "# Trip\n\nThis body is ready."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project_id"], "sample")
        self.assertIn("review_status", response.json())

