# Presidential Descendants Newsroom

A working low-cost MVP for collecting member news, managing an editorial workflow, publishing stories, assembling monthly issues, and maintaining a searchable historical archive.

## Included

- Public newsroom homepage and article templates
- Searchable archive by keyword and editorial section
- Contributor submission portal with tracking number
- Rights certification, privacy and embargo fields
- Secure editorial dashboard
- Submission workflow: Received → Review → Research → Fact Check → Approved → Scheduled → Published
- Draft story creation from a submission
- Fact-check, rights, source and metadata fields
- Monthly issue builder and public issue preview
- Audit log
- SQLite database and demonstration content
- Responsive design suitable for phone, tablet and desktop
- Docker and Gunicorn deployment support

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

Demonstration editor login:

- Email: `editor@society.local`
- Password: `ChangeMe123!`

Change the password and `SECRET_KEY` before deployment.

## Deploy below $100

The application can run on a low-cost Python web host with persistent disk. SQLite is adequate for the initial 15–100 contributors. For higher traffic, replace SQLite with PostgreSQL.

Typical initial operating stack:

- Application hosting: free tier or approximately $5–$10/month
- Database: SQLite on persistent disk; $0 incremental
- Domain/subdomain: use an existing Society subdomain
- Email distribution: existing mailing-list provider
- AI: optional; no AI API is required for the core system

## Production controls still required

This package is a production-capable MVP, not a security certification. Before public launch:

1. Replace the seeded editor password.
2. Configure a long random `SECRET_KEY`.
3. Put the app behind HTTPS.
4. Add outbound email notifications through the Society’s provider.
5. Add file uploads using cloud object storage if photographs/documents are required.
6. Add automated backups.
7. Confirm the Society’s privacy, copyright, corrections and AI-use policies.
8. Replace demonstration stories with fact-checked Society content.

## Agentic editorial extension

The database already includes `ai_notes`, source notes, fact-check status and workflow states. A future agent runner can be attached without changing the public system. Recommended agents:

- Intake classifier
- Assignment scorer
- Research/source retriever
- Claim-level fact checker
- Copy editor
- Standards and sensitivity reviewer
- Metadata/archive editor
- Issue production editor

No agent should directly publish. The `Published` state remains a human editorial decision.

## Version 2 editorial features
- Markdown-based rich story editor with formatting toolbar
- Sanitized HTML rendering for public articles
- Image, PDF, and Word-document attachments
- Persistent media storage compatible with the Render disk
- Attachment captions, credits, public links, and editor deletion
- Migration-safe `attachments` table created automatically


## Version 3 — Society Portal

- Members-only portal and searchable descendant/member directory
- Role-separated member and administrator logins
- Society events, governance-document links, committees, biographies, and non-binding donation pledges
- Administrator workflows for creating member accounts, events, and portal documents

## Version 4 — AI Research Assistant

- Source-conscious presidential-history research requests and saved history
- OpenAI Responses API integration with built-in web search when `OPENAI_API_KEY` is configured
- Graceful research-packet mode when the API key is absent
- Research prompts require chronology, primary-source leads, citations, and explicit separation of fact, interpretation, and unresolved questions

## Version 6 Agentic Editorial Pipeline
Five bounded stages: planning, evidence collection, chronology/fact matrix, editorial drafting, and managing-editor review. Completed packets and evidence are saved to the Historical Knowledge Library. Each stage has an independent timeout and partial outputs are retained when usable.


## Version 6 Agentic Editorial Pipeline
Five bounded stages: planning, evidence collection, chronology/fact matrix, editorial drafting, and managing-editor review. Completed packets and evidence are saved to the Historical Knowledge Library. Each stage has an independent timeout and partial outputs are retained when usable.

