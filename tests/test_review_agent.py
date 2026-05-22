from unittest.mock import patch

from fastapi.testclient import TestClient
from unittest import TestCase

from src.api_server import app
from src.reviewer import review_document


class ReviewAgentTest(TestCase):
    def test_passes_complete_document(self):
        with patch("src.reviewer.urllib_request.urlopen") as urlopen:
            result = review_document({"styled_markdown": "# Trip\n\nThis is a complete enough memory."})

        self.assertEqual(result["review_status"], "ok")
        self.assertEqual(result["issue_count"], 0)
        self.assertFalse(result["review_polished"])
        urlopen.assert_not_called()

    def test_can_enable_llm_polishing_when_quality_mode_is_requested(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"response":"# Trip\\n\\nThis is polished.\\n"}'

        with patch.dict("os.environ", {"REVIEW_ENABLE_LLM_POLISH": "true"}):
            with patch("src.reviewer.urllib_request.urlopen", return_value=FakeResponse()):
                result = review_document({"styled_markdown": "# Trip\n\nThis is a complete enough memory."})

        self.assertEqual(result["review_status"], "ok_polished")
        self.assertTrue(result["review_polished"])

    def test_detects_excluded_photo_reference(self):
        result = review_document(
            {
                "styled_markdown": "# Trip\n\n![secret](passport.jpg) private document",
                "excluded_photos": [{"file_name": "passport.jpg"}],
            }
        )

        self.assertEqual(result["review_status"], "needs_attention")
        self.assertGreater(result["issue_count"], 0)

    def test_flags_generic_filler_phrases(self):
        result = review_document(
            {
                "styled_markdown": (
                    "# 기록\n\n"
                    "이 장면은 여행의 흐름을 자연스럽게 이어준다. "
                    "작은 장면들이 모여 하루의 분위기를 완성했다."
                ),
            }
        )

        self.assertEqual(result["review_status"], "needs_attention")
        filler_check = next(c for c in result["checks"] if c["name"] == "no_generic_filler")
        self.assertEqual(filler_check["status"], "fail")

    def test_flags_repeated_plain_impressions(self):
        result = review_document(
            {
                "styled_markdown": (
                    "# 기록\n\n"
                    "분위기가 좋았다. 음식도 좋았다. 공간도 인상적이었다. 다시 봐도 좋았다."
                ),
            }
        )

        repeated_check = next(c for c in result["checks"] if c["name"] == "no_repetitive_plain_impressions")
        self.assertEqual(repeated_check["status"], "fail")

    def test_seo_keywords_reflected_passes(self):
        result = review_document(
            {
                "styled_markdown": (
                    "# 제주 흑돼지 맛집 후기\n\n"
                    "제주 흑돼지 맛집을 다녀왔다. 두툼한 고기가 인상적이었고 분위기도 좋았다. "
                    "다음 제주 여행에도 다시 들르고 싶은 곳이다."
                ),
                "target_keywords": "제주 흑돼지 맛집",
            }
        )

        self.assertEqual(result["review_status"], "ok")
        self.assertEqual(result["issue_count"], 0)
        names = {c["name"] for c in result["checks"]}
        self.assertIn("seo_title_contains_keyword", names)

    def test_seo_keyword_missing_from_title_flags(self):
        result = review_document(
            {
                "styled_markdown": "# 오늘의 기록\n\n흑돼지를 먹었다. 정말 맛있어서 또 먹고 싶었다.",
                "target_keywords": "제주 흑돼지 맛집",
            }
        )

        self.assertEqual(result["review_status"], "needs_attention")
        self.assertGreater(result["issue_count"], 0)
        title_check = next(c for c in result["checks"] if c["name"] == "seo_title_contains_keyword")
        self.assertEqual(title_check["status"], "fail")

    def test_seo_keyword_stuffing_flags(self):
        result = review_document(
            {
                "styled_markdown": "# 맛집\n\n맛집 맛집 맛집 맛집 맛집 맛집.",
                "target_keywords": "맛집",
            }
        )

        stuffing = next(c for c in result["checks"] if c["name"] == "seo_no_keyword_stuffing")
        self.assertEqual(stuffing["status"], "fail")
        self.assertGreater(result["issue_count"], 0)

    def test_no_target_keywords_skips_seo_checks(self):
        result = review_document({"styled_markdown": "# Trip\n\nThis is a complete enough memory."})

        names = {c["name"] for c in result["checks"]}
        self.assertNotIn("seo_title_contains_keyword", names)
        self.assertEqual(result["issue_count"], 0)

    def test_review_endpoint_accepts_target_keywords(self):
        client = TestClient(app)

        response = client.post(
            "/api/v1/reviews",
            json={
                "project_id": "sample",
                "styled_markdown": "# 제주 흑돼지 맛집\n\n제주 흑돼지 맛집 다녀온 솔직 후기입니다.",
                "target_keywords": "제주 흑돼지 맛집",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project_id"], "sample")

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

    def test_metrics_endpoint_returns_prometheus_data(self):
        client = TestClient(app)

        response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("http_request_duration_seconds", response.text)
