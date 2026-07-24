import importlib
import os
import tempfile
import unittest
from pathlib import Path


class NewsroomTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_newsroom.db"
        os.environ["DATABASE_PATH"] = str(cls.db_path)
        os.environ["SECRET_KEY"] = "test-secret"
        cls.module = importlib.import_module("app")
        cls.module.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = self.module.app.test_client()

    def login(self):
        return self.client.post(
            "/login",
            data={"email": "editor@society.local", "password": "ChangeMe123!"},
            follow_redirects=False,
        )

    def test_public_routes(self):
        for path in ["/", "/archive", "/submit", "/login"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_missing_content_returns_404(self):
        self.assertEqual(self.client.get("/story/not-real").status_code, 404)
        self.assertEqual(self.client.get("/issues/999999").status_code, 404)

    def test_editor_requires_login(self):
        response = self.client.get("/editor")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_login_and_dashboard(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/editor"))
        self.assertEqual(self.client.get("/editor").status_code, 200)

    def test_submission_creation(self):
        response = self.client.post(
            "/submit",
            data={
                "contributor_name": "Test Contributor",
                "contributor_email": "test@example.com",
                "relationship": "Researcher",
                "category": "Society News",
                "summary": "Automated test submission.",
                "rights_certified": "yes",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SPD-", response.data)

    def test_story_and_issue_creation(self):
        self.login()
        story_response = self.client.post(
            "/editor/story/new",
            data={
                "title": "Automated Story",
                "body": "A story created by the automated test suite.",
                "category": "Society News",
                "publication_status": "Published",
                "fact_check_status": "Verified",
                "rights_status": "Cleared",
            },
            follow_redirects=False,
        )
        self.assertEqual(story_response.status_code, 302)
        self.assertIn("/editor/story/", story_response.location)

        issue_response = self.client.post(
            "/editor/issue/new",
            data={
                "title": "Automated Issue",
                "issue_month": "2026-07",
                "status": "Draft",
            },
            follow_redirects=False,
        )
        self.assertEqual(issue_response.status_code, 302)
        self.assertIn("/editor/issue/", issue_response.location)


if __name__ == "__main__":
    unittest.main()
