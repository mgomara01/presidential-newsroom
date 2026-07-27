import importlib
import io
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
        cls.module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

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

    def test_health(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')
        self.assertEqual(response.get_json()['version'], '6.0.0')

    def test_login_rejects_external_redirect(self):
        response = self.client.post('/login?next=//evil.example', data={
            'email': 'editor@society.local',
            'password': 'ChangeMe123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/editor'))

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

    def test_markdown_is_rendered_and_script_removed(self):
        rendered = self.module.render_markdown("## Heading\n\n<script>alert(1)</script>**Bold**")
        self.assertIn("<h2>Heading</h2>", rendered)
        self.assertIn("<strong>Bold</strong>", rendered)
        self.assertNotIn("<script>", rendered)

    def test_story_attachment_upload_and_public_access(self):
        self.login()
        response = self.client.post(
            "/editor/story/new",
            data={
                "title": "Story With Attachment",
                "body": "Attachment test",
                "category": "Society News",
                "publication_status": "Published",
                "fact_check_status": "Verified",
                "rights_status": "Cleared",
                "attachments": (io.BytesIO(b"fake image bytes"), "portrait.jpg"),
                "attachment_caption": "Test portrait",
                "attachment_credit": "Test archive",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.module.app.app_context():
            attachment = self.module.db().execute(
                "SELECT * FROM attachments ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(attachment)
            media = self.client.get(f"/media/{attachment['filename']}")
            self.assertEqual(media.status_code, 200)
            media.close()


    def test_portal_requires_login_and_loads(self):
        self.assertEqual(self.client.get('/portal').status_code, 302)
        self.login()
        response=self.client.get('/portal')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Society Portal', response.data)

    def test_portal_admin_creates_member_event_document(self):
        self.login()
        r=self.client.post('/editor/portal/member/new',data={'full_name':'Test Descendant','presidential_connection':'Test President','city':'Tampa','state':'FL','visibility':'Members'},follow_redirects=False)
        self.assertEqual(r.status_code,302)
        r=self.client.post('/editor/portal/event/new',data={'title':'Annual Gathering','starts_at':'2026-10-10T10:00','location':'Washington'},follow_redirects=False)
        self.assertEqual(r.status_code,302)
        r=self.client.post('/editor/portal/document/new',data={'title':'Board Minutes','file_url':'https://example.com/minutes.pdf'},follow_redirects=False)
        self.assertEqual(r.status_code,302)
        self.assertIn(b'Test Descendant',self.client.get('/portal/directory').data)

    def test_research_assistant_graceful_without_api_key(self):
        self.login()
        os.environ.pop('OPENAI_API_KEY',None)
        r=self.client.post('/editor/research',data={'question':'What primary sources document the event?','scope':'Early republic'},follow_redirects=True)
        self.assertEqual(r.status_code,200)
        self.assertIn(b'Needs API Key',r.data)
        self.assertIn(b'National Archives',r.data)



    def test_research_runs_in_background_without_blocking_request(self):
        import time

        class FakeCreatedResponse:
            id = 'resp_test_123'
            status = 'queued'

        class FakeCompletedResponse:
            id = 'resp_test_123'
            status = 'completed'
            output_text = 'Completed research packet'

        class FakeResponses:
            def create(self, **kwargs):
                self.create_kwargs = kwargs
                return FakeCreatedResponse()

            def retrieve(self, response_id):
                self.response_id = response_id
                return FakeCompletedResponse()

        class FakeOpenAI:
            shared_responses = FakeResponses()

            def __init__(self, **_kwargs):
                self.responses = self.shared_responses

        self.login()
        original_openai = self.module.OpenAI
        os.environ['OPENAI_API_KEY'] = 'test-key'
        self.module.OpenAI = FakeOpenAI
        try:
            started = time.monotonic()
            response = self.client.post(
                '/editor/research',
                data={'question': 'Background test', 'scope': 'Test scope'},
                follow_redirects=False,
            )
            elapsed = time.monotonic() - started
            self.assertEqual(response.status_code, 302)
            self.assertLess(elapsed, 0.5)
            self.assertTrue(FakeOpenAI.shared_responses.create_kwargs['background'])
            request_id = int(response.location.rsplit('=', 1)[1])
            page = self.client.get(response.location)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Completed research packet', page.data)
            with self.module.app.app_context():
                row = self.module.db().execute(
                    'SELECT * FROM research_requests WHERE id=?', (request_id,)
                ).fetchone()
            self.assertEqual(row['status'], 'Completed')
            self.assertEqual(row['response_id'], 'resp_test_123')
        finally:
            self.module.OpenAI = original_openai
            os.environ.pop('OPENAI_API_KEY', None)

    def test_member_can_use_portal_but_not_editor(self):
        self.login()
        self.client.post('/editor/portal/member/new',data={'full_name':'Portal Member','email':'member@example.com','password':'MemberPass123!','visibility':'Members'})
        self.client.get('/logout')
        response=self.client.post('/login',data={'email':'member@example.com','password':'MemberPass123!'},follow_redirects=False)
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/portal').status_code,200)
        self.assertEqual(self.client.get('/editor').status_code,403)


if __name__ == "__main__":
    unittest.main()
