import os
import re
import json
import sqlite3
import secrets
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from flask_wtf.csrf import CSRFProtect
import bleach
import markdown
from werkzeug.security import check_password_hash, generate_password_hash
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('DATABASE_PATH', BASE_DIR / 'instance' / 'newsroom.db'))
UPLOAD_DIR = Path(os.environ.get('UPLOAD_DIR', DB_PATH.parent / 'uploads'))
ALLOWED_UPLOADS = {'png','jpg','jpeg','gif','webp','pdf','doc','docx'}
APP_VERSION = '6.2.0'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
csrf = CSRFProtect(app)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

WORKFLOW = ['Received', 'Under Review', 'Research', 'Fact Check', 'Approved', 'Scheduled', 'Published', 'Held', 'Declined']
CATEGORIES = [
    'Society News', 'From the Families', 'Presidential History', 'Founding Generation',
    'Libraries & Historic Sites', 'Archival Discovery', 'Scholar’s Desk',
    'Member Profile', 'Events', 'Memorials'
]


def db():
    if 'db' not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA journal_mode = WAL')
        g.db.execute('PRAGMA busy_timeout = 5000')
    return g.db


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    return response


@app.teardown_appcontext
def close_db(_exc=None):
    conn = g.pop('db', None)
    if conn:
        conn.close()


def slugify(text):
    text = re.sub(r'[^a-zA-Z0-9\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text) or 'story'


def allowed_upload(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_UPLOADS


def render_markdown(value):
    raw = markdown.markdown(value or '', extensions=['extra','sane_lists'])
    tags = set(bleach.sanitizer.ALLOWED_TAGS) | {'p','h1','h2','h3','h4','pre','code','blockquote','hr','br','img','table','thead','tbody','tr','th','td'}
    attrs = {'a':['href','title','target','rel'], 'img':['src','alt','title'], '*':['class']}
    return bleach.clean(raw, tags=tags, attributes=attrs, protocols={'http','https','mailto'}, strip=True)


app.jinja_env.filters['markdown'] = render_markdown


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'editor'
    );
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_code TEXT UNIQUE NOT NULL,
        contributor_name TEXT NOT NULL,
        contributor_email TEXT NOT NULL,
        relationship TEXT NOT NULL,
        category TEXT NOT NULL,
        presidential_connection TEXT,
        proposed_headline TEXT,
        summary TEXT NOT NULL,
        full_narrative TEXT,
        event_date TEXT,
        location TEXT,
        sources TEXT,
        photo_caption TEXT,
        photo_credit TEXT,
        rights_certified INTEGER NOT NULL DEFAULT 0,
        privacy_level TEXT NOT NULL DEFAULT 'Public',
        embargo_date TEXT,
        status TEXT NOT NULL DEFAULT 'Received',
        editor_notes TEXT,
        ai_notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        deck TEXT,
        body TEXT NOT NULL,
        category TEXT NOT NULL,
        author TEXT,
        president_tags TEXT,
        topic_tags TEXT,
        source_notes TEXT,
        fact_check_status TEXT NOT NULL DEFAULT 'Pending',
        rights_status TEXT NOT NULL DEFAULT 'Pending',
        publication_status TEXT NOT NULL DEFAULT 'Draft',
        published_at TEXT,
        featured INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(submission_id) REFERENCES submissions(id)
    );
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        issue_month TEXT NOT NULL,
        editor_note TEXT,
        status TEXT NOT NULL DEFAULT 'Draft',
        published_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS issue_stories (
        issue_id INTEGER NOT NULL,
        story_id INTEGER NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        section_name TEXT,
        PRIMARY KEY(issue_id, story_id),
        FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE,
        FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, full_name TEXT NOT NULL, presidential_connection TEXT, biography TEXT, city TEXT, state TEXT, visibility TEXT NOT NULL DEFAULT 'Members', committee TEXT, phone TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS society_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, starts_at TEXT NOT NULL, ends_at TEXT, location TEXT, audience TEXT NOT NULL DEFAULT 'Members', registration_url TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS portal_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, file_url TEXT, category TEXT, audience TEXT NOT NULL DEFAULT 'Members', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS donation_pledges (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL NOT NULL, note TEXT, status TEXT NOT NULL DEFAULT 'Pledged', created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS research_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question TEXT NOT NULL, scope TEXT, status TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        details TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        story_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        mime_type TEXT,
        caption TEXT,
        credit TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
    );
    ''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(research_requests)').fetchall()}
    if 'response_id' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN response_id TEXT')
    if 'deadline_at' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN deadline_at TEXT')
    if 'poll_errors' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN poll_errors INTEGER NOT NULL DEFAULT 0')
    if 'last_error' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN last_error TEXT')
    if 'pipeline_stage' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN pipeline_stage INTEGER NOT NULL DEFAULT 0')
    if 'stage_outputs' not in columns:
        conn.execute("ALTER TABLE research_requests ADD COLUMN stage_outputs TEXT NOT NULL DEFAULT '{}'")
    if 'stage_started_at' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN stage_started_at TEXT')
    if 'stage_deadline_at' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN stage_deadline_at TEXT')
    if 'progress_label' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN progress_label TEXT')
    if 'knowledge_saved' not in columns:
        conn.execute('ALTER TABLE research_requests ADD COLUMN knowledge_saved INTEGER NOT NULL DEFAULT 0')
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        research_request_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        summary TEXT NOT NULL,
        source_packet TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(research_request_id) REFERENCES research_requests(id) ON DELETE CASCADE
    )''')
    now = datetime.now(UTC).isoformat()
    if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        admin_email = os.environ.get('ADMIN_EMAIL', 'editor@society.local').lower().strip()
        admin_name = os.environ.get('ADMIN_NAME', 'Managing Editor').strip()
        admin_password = os.environ.get('ADMIN_PASSWORD')
        if not admin_password:
            if os.environ.get('APP_ENV') == 'production':
                raise RuntimeError('ADMIN_PASSWORD is required in production')
            admin_password = 'ChangeMe123!'
        conn.execute('INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)',
                     (admin_email, admin_name, generate_password_hash(admin_password), 'admin'))
    if not conn.execute('SELECT 1 FROM stories LIMIT 1').fetchone():
        samples = [
            ('A New Digital Chapter for Presidential Legacy', 'The Society launches an editorial platform designed to preserve family perspectives and connect them with rigorous historical scholarship.',
             'The Society of Presidential Descendants is establishing a permanent digital newsroom to collect, verify, preserve, and publish material concerning the American presidency, presidential families, and the Founding generation. The platform will combine member submissions with disciplined editorial review, source documentation, rights management, and a searchable public archive.',
             'Society News', 'Editorial Desk', 'George Washington,Theodore Roosevelt,Harry S. Truman', 'digital archive,public history', 1),
            ('From Family Memory to Public History', 'A practical framework for preserving recollections without blurring the line between memory and documented fact.',
             'Family recollections are historically valuable because they reveal how national legacies are experienced and transmitted across generations. The newsroom preserves those recollections in the contributor’s voice while clearly distinguishing personal memory, documentary evidence, and later historical interpretation.',
             'From the Families', 'Research Desk', 'Ulysses S. Grant,Lyndon B. Johnson', 'oral history,family archive', 0),
            ('This Month in the Early Republic', 'A curated guide to consequential events, documents, and debates from the nation’s formative period.',
             'The Founding Generation desk will publish concise, source-backed treatments of constitutional milestones, diplomacy, political institutions, and the people whose decisions shaped the early republic. Each entry will link readers to primary documents and reputable repositories whenever those materials are publicly available.',
             'Founding Generation', 'Historical Desk', 'George Washington,John Adams,Thomas Jefferson,James Madison', 'founding era,constitution', 0)
        ]
        for title, deck, body, category, author, presidents, topics, featured in samples:
            conn.execute('''INSERT INTO stories(slug,title,deck,body,category,author,president_tags,topic_tags,source_notes,fact_check_status,rights_status,publication_status,published_at,featured,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (slugify(title), title, deck, body, category, author, presidents, topics,
                          'Seed content for demonstration; replace with verified editorial material.', 'Verified', 'Cleared', 'Published', now, featured, now, now))
        conn.execute('INSERT INTO issues(title,issue_month,editor_note,status,published_at,created_at) VALUES(?,?,?,?,?,?)',
                     ('The Presidential Legacy Review — Inaugural Edition', datetime.now(UTC).strftime('%Y-%m'),
                      'This inaugural edition demonstrates the newsroom’s structure, standards, and public presentation.', 'Published', now, now))
        issue_id = conn.execute('SELECT id FROM issues ORDER BY id DESC LIMIT 1').fetchone()[0]
        for pos, row in enumerate(conn.execute('SELECT id, category FROM stories ORDER BY featured DESC, id').fetchall(), start=1):
            conn.execute('INSERT INTO issue_stories(issue_id,story_id,position,section_name) VALUES(?,?,?,?)',
                         (issue_id, row[0], pos, row[1]))
    stale_cutoff = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    conn.execute(
        "UPDATE research_requests SET status='Error', result='Research exceeded the maximum processing window and was stopped. Please submit a narrower request.', last_error='Maximum runtime exceeded', updated_at=? WHERE status IN ('Queued','In Progress') AND created_at<?",
        (now, stale_cutoff),
    )
    conn.commit()
    conn.close()


def audit(action, entity_type, entity_id=None, details=''):
    actor = session.get('user_name', 'Public')
    db().execute('INSERT INTO audit_log(actor,action,entity_type,entity_id,details,created_at) VALUES(?,?,?,?,?,?)',
                 (actor, action, entity_type, entity_id, details, datetime.now(UTC).isoformat()))
    db().commit()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        if session.get('role') != 'admin':
            return ('Forbidden', 403)
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {'CATEGORIES': CATEGORIES, 'WORKFLOW': WORKFLOW, 'current_year': datetime.now(UTC).year}


@app.route('/health')
def health():
    try:
        db().execute('SELECT 1').fetchone()
        return {'status': 'ok', 'version': APP_VERSION, 'research_mode': 'search-and-draft'}, 200
    except sqlite3.Error:
        app.logger.exception('Database health check failed')
        return {'status': 'error'}, 503


@app.route('/')
def home():
    featured = db().execute("SELECT * FROM stories WHERE publication_status='Published' ORDER BY featured DESC, published_at DESC LIMIT 1").fetchone()
    stories = db().execute("SELECT * FROM stories WHERE publication_status='Published' AND id != ? ORDER BY published_at DESC LIMIT 8", (featured['id'] if featured else 0,)).fetchall()
    issue = db().execute("SELECT * FROM issues WHERE status='Published' ORDER BY issue_month DESC LIMIT 1").fetchone()
    return render_template('home.html', featured=featured, stories=stories, issue=issue)


@app.route('/archive')
def archive():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    sql = "SELECT * FROM stories WHERE publication_status='Published'"
    params = []
    if q:
        sql += " AND (title LIKE ? OR deck LIKE ? OR body LIKE ? OR president_tags LIKE ? OR topic_tags LIKE ?)"
        params += [f'%{q}%'] * 5
    if category:
        sql += ' AND category=?'
        params.append(category)
    sql += ' ORDER BY published_at DESC'
    stories = db().execute(sql, params).fetchall()
    return render_template('archive.html', stories=stories, q=q, category=category)


@app.route('/story/<slug>')
def story(slug):
    item = db().execute("SELECT * FROM stories WHERE slug=? AND publication_status='Published'", (slug,)).fetchone()
    if not item:
        return ('Not found', 404)
    related = db().execute("SELECT * FROM stories WHERE publication_status='Published' AND category=? AND id!=? ORDER BY published_at DESC LIMIT 3", (item['category'], item['id'])).fetchall()
    attachments = db().execute('SELECT * FROM attachments WHERE story_id=? ORDER BY id', (item['id'],)).fetchall()
    return render_template('story.html', story=item, related=related, attachments=attachments)



@app.route('/media/<path:filename>')
def media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route('/issues/<int:issue_id>')
def issue(issue_id):
    item = db().execute("SELECT * FROM issues WHERE id=? AND (status='Published' OR ?=1)", (issue_id, 1 if session.get('user_id') else 0)).fetchone()
    if not item:
        return ('Not found', 404)
    stories = db().execute('''SELECT s.*, i.section_name, i.position FROM issue_stories i JOIN stories s ON s.id=i.story_id
                              WHERE i.issue_id=? ORDER BY i.position''', (issue_id,)).fetchall()
    return render_template('issue.html', issue=item, stories=stories)


@app.route('/submit', methods=['GET', 'POST'])
def submit():
    if request.method == 'POST':
        required = ['contributor_name', 'contributor_email', 'relationship', 'category', 'summary']
        missing = [x for x in required if not request.form.get(x, '').strip()]
        if missing or request.form.get('rights_certified') != 'yes':
            flash('Complete all required fields and certify publication rights.', 'error')
            return render_template('submit.html', form=request.form)
        now = datetime.now(UTC)
        tracking = f"SPD-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
        cur = db().execute('''INSERT INTO submissions(tracking_code,contributor_name,contributor_email,relationship,category,presidential_connection,proposed_headline,summary,full_narrative,event_date,location,sources,photo_caption,photo_credit,rights_certified,privacy_level,embargo_date,status,created_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (tracking, request.form['contributor_name'].strip(), request.form['contributor_email'].strip(), request.form['relationship'], request.form['category'], request.form.get('presidential_connection','').strip(), request.form.get('proposed_headline','').strip(), request.form['summary'].strip(), request.form.get('full_narrative','').strip(), request.form.get('event_date',''), request.form.get('location','').strip(), request.form.get('sources','').strip(), request.form.get('photo_caption','').strip(), request.form.get('photo_credit','').strip(), 1, request.form.get('privacy_level','Public'), request.form.get('embargo_date',''), 'Received', now.isoformat(), now.isoformat()))
        db().commit()
        audit('Created', 'submission', cur.lastrowid, tracking)
        return render_template('thanks.html', tracking=tracking)
    return render_template('submit.html', form={})


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db().execute('SELECT * FROM users WHERE email=?', (request.form.get('email','').lower().strip(),)).fetchone()
        if user and check_password_hash(user['password_hash'], request.form.get('password','')):
            session.clear(); session['user_id'] = user['id']; session['user_name'] = user['name']; session['role'] = user['role']
            next_url = request.args.get('next', '')
            return redirect(next_url if next_url.startswith('/') and not next_url.startswith('//') else url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('home'))


@app.route('/editor')
@admin_required
def dashboard():
    counts = {row['status']: row['n'] for row in db().execute('SELECT status,COUNT(*) n FROM submissions GROUP BY status')}
    submissions = db().execute('SELECT * FROM submissions ORDER BY updated_at DESC LIMIT 50').fetchall()
    stories = db().execute('SELECT * FROM stories ORDER BY updated_at DESC LIMIT 20').fetchall()
    issues = db().execute('SELECT * FROM issues ORDER BY issue_month DESC').fetchall()
    return render_template('dashboard.html', counts=counts, submissions=submissions, stories=stories, issues=issues)


@app.route('/editor/submission/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def edit_submission(item_id):
    item = db().execute('SELECT * FROM submissions WHERE id=?', (item_id,)).fetchone()
    if not item: return ('Not found', 404)
    if request.method == 'POST':
        status = request.form.get('status', item['status'])
        notes = request.form.get('editor_notes','')
        ai_notes = request.form.get('ai_notes','')
        db().execute('UPDATE submissions SET status=?,editor_notes=?,ai_notes=?,updated_at=? WHERE id=?',
                     (status, notes, ai_notes, datetime.now(UTC).isoformat(), item_id))
        db().commit(); audit('Updated', 'submission', item_id, status); flash('Submission updated.', 'success')
        if request.form.get('create_story') == 'yes':
            title = item['proposed_headline'] or item['summary'][:90]
            base_slug = slugify(title); slug = base_slug; n=2
            while db().execute('SELECT 1 FROM stories WHERE slug=?', (slug,)).fetchone(): slug=f'{base_slug}-{n}'; n+=1
            now = datetime.now(UTC).isoformat()
            cur = db().execute('''INSERT INTO stories(submission_id,slug,title,deck,body,category,author,president_tags,topic_tags,source_notes,fact_check_status,rights_status,publication_status,created_at,updated_at)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (item_id, slug, title, item['summary'], item['full_narrative'] or item['summary'], item['category'], item['contributor_name'], item['presidential_connection'], '', item['sources'], 'Pending', 'Certified by contributor' if item['rights_certified'] else 'Pending', 'Draft', now, now))
            db().commit(); audit('Created', 'story', cur.lastrowid, f'From submission {item_id}'); flash('Draft story created.', 'success')
        return redirect(url_for('edit_submission', item_id=item_id))
    return render_template('edit_submission.html', item=item)


@app.route('/editor/story/new', methods=['GET', 'POST'])
@app.route('/editor/story/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def edit_story(item_id=None):
    item = db().execute('SELECT * FROM stories WHERE id=?', (item_id,)).fetchone() if item_id else None
    if request.method == 'POST':
        title = request.form['title'].strip(); now = datetime.now(UTC).isoformat()
        slug = request.form.get('slug','').strip() or slugify(title)
        values = (slug,title,request.form.get('deck',''),request.form.get('body',''),request.form.get('category','Society News'),request.form.get('author','Editorial Desk'),request.form.get('president_tags',''),request.form.get('topic_tags',''),request.form.get('source_notes',''),request.form.get('fact_check_status','Pending'),request.form.get('rights_status','Pending'),request.form.get('publication_status','Draft'),request.form.get('published_at') or None,1 if request.form.get('featured')=='yes' else 0,now)
        try:
            if item:
                db().execute('''UPDATE stories SET slug=?,title=?,deck=?,body=?,category=?,author=?,president_tags=?,topic_tags=?,source_notes=?,fact_check_status=?,rights_status=?,publication_status=?,published_at=?,featured=?,updated_at=? WHERE id=?''', values+(item_id,))
                sid=item_id; action='Updated'
            else:
                cur=db().execute('''INSERT INTO stories(slug,title,deck,body,category,author,president_tags,topic_tags,source_notes,fact_check_status,rights_status,publication_status,published_at,featured,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', values+(now,))
                sid=cur.lastrowid; action='Created'
            db().commit()
            for uploaded in request.files.getlist('attachments'):
                if uploaded and uploaded.filename:
                    if not allowed_upload(uploaded.filename):
                        flash(f'Unsupported file type: {uploaded.filename}', 'error')
                        continue
                    original = secure_filename(uploaded.filename)
                    ext = original.rsplit('.',1)[1].lower()
                    stored = f'{sid}-{secrets.token_hex(8)}.{ext}'
                    uploaded.save(UPLOAD_DIR / stored)
                    db().execute('INSERT INTO attachments(story_id,filename,original_name,mime_type,caption,credit,created_at) VALUES(?,?,?,?,?,?,?)',
                                 (sid,stored,original,uploaded.mimetype,request.form.get('attachment_caption','').strip(),request.form.get('attachment_credit','').strip(),now))
                    db().commit(); audit('Uploaded','attachment',sid,original)
            audit(action,'story',sid,title); flash('Story saved.','success'); return redirect(url_for('edit_story', item_id=sid))
        except sqlite3.IntegrityError:
            flash('That URL slug is already in use.','error')
    attachments = db().execute('SELECT * FROM attachments WHERE story_id=? ORDER BY id DESC', (item_id,)).fetchall() if item_id else []
    return render_template('edit_story.html', item=item, attachments=attachments)


@app.route('/editor/attachment/<int:attachment_id>/delete', methods=['POST'])
@admin_required
def delete_attachment(attachment_id):
    item = db().execute('SELECT * FROM attachments WHERE id=?', (attachment_id,)).fetchone()
    if not item:
        abort(404)
    path = UPLOAD_DIR / item['filename']
    db().execute('DELETE FROM attachments WHERE id=?', (attachment_id,))
    db().commit()
    if path.exists():
        path.unlink()
    audit('Deleted','attachment',attachment_id,item['original_name'])
    flash('Attachment deleted.','success')
    return redirect(url_for('edit_story', item_id=item['story_id']))


@app.route('/editor/issue/new', methods=['GET','POST'])
@app.route('/editor/issue/<int:item_id>', methods=['GET','POST'])
@admin_required
def edit_issue(item_id=None):
    item = db().execute('SELECT * FROM issues WHERE id=?', (item_id,)).fetchone() if item_id else None
    all_stories = db().execute("SELECT * FROM stories WHERE publication_status IN ('Approved','Published','Scheduled') ORDER BY category,title").fetchall()
    selected = []
    if item:
        selected = db().execute('SELECT story_id,position,section_name FROM issue_stories WHERE issue_id=? ORDER BY position',(item_id,)).fetchall()
    if request.method=='POST':
        now=datetime.now(UTC).isoformat(); title=request.form['title']; month=request.form['issue_month']; status=request.form.get('status','Draft')
        if item:
            db().execute('UPDATE issues SET title=?,issue_month=?,editor_note=?,status=?,published_at=? WHERE id=?',(title,month,request.form.get('editor_note',''),status,now if status=='Published' else item['published_at'],item_id)); iid=item_id
        else:
            cur=db().execute('INSERT INTO issues(title,issue_month,editor_note,status,published_at,created_at) VALUES(?,?,?,?,?,?)',(title,month,request.form.get('editor_note',''),status,now if status=='Published' else None,now)); iid=cur.lastrowid
        db().execute('DELETE FROM issue_stories WHERE issue_id=?',(iid,))
        story_ids=request.form.getlist('story_ids')
        for pos,sid in enumerate(story_ids,start=1):
            story=db().execute('SELECT category FROM stories WHERE id=?',(sid,)).fetchone()
            if story: db().execute('INSERT INTO issue_stories(issue_id,story_id,position,section_name) VALUES(?,?,?,?)',(iid,sid,pos,story['category']))
        db().commit(); audit('Saved','issue',iid,title); flash('Issue saved.','success'); return redirect(url_for('edit_issue',item_id=iid))
    return render_template('edit_issue.html',item=item,all_stories=all_stories,selected=selected)


@app.route('/portal')
@login_required
def portal_home():
    events=db().execute("SELECT * FROM society_events ORDER BY starts_at LIMIT 8").fetchall()
    documents=db().execute("SELECT * FROM portal_documents ORDER BY created_at DESC LIMIT 8").fetchall()
    members=db().execute("SELECT * FROM members WHERE visibility!='Private' ORDER BY full_name LIMIT 12").fetchall()
    return render_template('portal.html',events=events,documents=documents,members=members)

@app.route('/portal/directory')
@login_required
def portal_directory():
    q=request.args.get('q','').strip(); sql="SELECT * FROM members WHERE visibility!='Private'"; params=[]
    if q:
        sql += " AND (full_name LIKE ? OR presidential_connection LIKE ? OR city LIKE ? OR state LIKE ? OR committee LIKE ?)"; params=[f'%{q}%']*5
    return render_template('directory.html',members=db().execute(sql+' ORDER BY full_name',params).fetchall(),q=q)

@app.route('/portal/pledge',methods=['POST'])
@login_required
def portal_pledge():
    try: amount=float(request.form.get('amount','0'))
    except ValueError: amount=0
    if amount<=0: flash('Enter a valid pledge amount.','error'); return redirect(url_for('portal_home'))
    db().execute('INSERT INTO donation_pledges(user_id,amount,note,created_at) VALUES(?,?,?,?)',(session['user_id'],amount,request.form.get('note','').strip(),datetime.now(UTC).isoformat())); db().commit(); audit('Created','donation_pledge',details=f'${amount:.2f}')
    flash('Your pledge has been recorded. No payment was processed.','success'); return redirect(url_for('portal_home'))

@app.route('/editor/portal/member/new',methods=['GET','POST'])
@admin_required
def portal_member_new():
    if request.method=='POST':
        now=datetime.now(UTC).isoformat(); email=request.form.get('email','').lower().strip(); password=request.form.get('password','').strip(); user_id=None
        if email and password:
            cur=db().execute("INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)",(email,request.form['full_name'].strip(),generate_password_hash(password),'member')); user_id=cur.lastrowid
        db().execute("INSERT INTO members(user_id,full_name,presidential_connection,biography,city,state,visibility,committee,phone,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(user_id,request.form['full_name'].strip(),request.form.get('presidential_connection',''),request.form.get('biography',''),request.form.get('city',''),request.form.get('state',''),request.form.get('visibility','Members'),request.form.get('committee',''),request.form.get('phone',''),now,now)); db().commit(); flash('Member added.','success'); return redirect(url_for('portal_home'))
    return render_template('portal_admin.html',mode='member')

@app.route('/editor/portal/event/new',methods=['GET','POST'])
@admin_required
def portal_event_new():
    if request.method=='POST':
        db().execute("INSERT INTO society_events(title,description,starts_at,ends_at,location,audience,registration_url,created_at) VALUES(?,?,?,?,?,?,?,?)",(request.form['title'].strip(),request.form.get('description',''),request.form['starts_at'],request.form.get('ends_at',''),request.form.get('location',''),request.form.get('audience','Members'),request.form.get('registration_url',''),datetime.now(UTC).isoformat())); db().commit(); flash('Event added.','success'); return redirect(url_for('portal_home'))
    return render_template('portal_admin.html',mode='event')

@app.route('/editor/portal/document/new',methods=['GET','POST'])
@admin_required
def portal_document_new():
    if request.method=='POST':
        db().execute("INSERT INTO portal_documents(title,description,file_url,category,audience,created_at) VALUES(?,?,?,?,?,?)",(request.form['title'].strip(),request.form.get('description',''),request.form.get('file_url',''),request.form.get('category','Governance'),request.form.get('audience','Members'),datetime.now(UTC).isoformat())); db().commit(); flash('Document added.','success'); return redirect(url_for('portal_home'))
    return render_template('portal_admin.html',mode='document')

RESEARCH_STAGE_MINUTES = int(os.environ.get('RESEARCH_STAGE_MINUTES', '8'))
RESEARCH_MODEL = os.environ.get('OPENAI_RESEARCH_MODEL', 'gpt-5-mini')
SEARCH_DRAFT_MODEL = os.environ.get('OPENAI_RESEARCH_MODEL', 'gpt-5-mini')
SEARCH_DRAFT_TIMEOUT = int(os.environ.get('SEARCH_DRAFT_TIMEOUT', '60'))


def search_draft_prompt(topic, scope, article_type, target_words):
    return (
        "You are a fast, experienced historical news editor for the Society of Presidential Descendants. "
        "Use web search only as needed to confirm the most important facts. Write a clear, engaging, nonpartisan "
        f"{article_type} of about {target_words} words in 5 to 8 paragraphs. Begin with a strong headline, then the article. "
        "Use plain English, avoid academic apparatus, and do not produce a research plan, chronology, fact matrix, or long bibliography. "
        "End with a short Sources consulted section listing 2 to 5 authoritative sources or repositories. "
        "Distinguish uncertain claims and do not invent quotations.\n\n"
        f"Topic: {topic}\nAdditional direction: {scope}"
    )


@app.route('/editor/research', methods=['GET', 'POST'])
@admin_required
def research_assistant():
    enabled = bool(os.environ.get('OPENAI_API_KEY')) and OpenAI is not None
    result = None
    if request.method == 'POST':
        topic = request.form['question'].strip()
        scope = request.form.get('scope', '').strip()
        article_type = request.form.get('article_type', 'news post').strip()
        try:
            target_words = max(300, min(900, int(request.form.get('target_words', '600'))))
        except ValueError:
            target_words = 600
        now = datetime.now(UTC).isoformat()
        status = 'Needs API Key'
        output = 'AI search and drafting is not activated.'
        diagnostic = 'OPENAI_API_KEY unavailable'
        if enabled:
            try:
                client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=float(SEARCH_DRAFT_TIMEOUT), max_retries=1)
                response = client.responses.create(
                    model=SEARCH_DRAFT_MODEL,
                    tools=[{'type': 'web_search'}],
                    input=search_draft_prompt(topic, scope, article_type, target_words),
                    max_tool_calls=3,
                    max_output_tokens=1800,
                )
                output = getattr(response, 'output_text', '') or ''
                if output.strip():
                    status = 'Completed'
                    diagnostic = ''
                else:
                    detail = getattr(response, 'incomplete_details', None) or getattr(response, 'error', None) or 'No text returned'
                    status = 'Error'
                    diagnostic = str(detail)
                    output = f'Search and drafting did not return usable text. Diagnostic: {diagnostic}'
            except Exception as exc:
                app.logger.exception('Search and draft failed')
                status = 'Error'
                diagnostic = f'{type(exc).__name__}: {exc}'
                output = 'Search and drafting failed. Diagnostic: ' + diagnostic
        cur = db().execute(
            "INSERT INTO research_requests(user_id,question,scope,status,result,created_at,updated_at,response_id,deadline_at,poll_errors,last_error,pipeline_stage,stage_outputs,progress_label,knowledge_saved) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session['user_id'], topic, scope, status, output, now, now, None, None, 0, diagnostic, 0, '{}', 'Search & Draft', 0),
        )
        db().commit()
        request_id = cur.lastrowid
        audit('Created', 'research_request', request_id, status)
        return redirect(url_for('research_assistant', request_id=request_id))

    request_id = request.args.get('request_id', type=int)
    if request_id:
        result = db().execute('SELECT * FROM research_requests WHERE id=?', (request_id,)).fetchone()
    history = db().execute('SELECT * FROM research_requests ORDER BY created_at DESC LIMIT 20').fetchall()
    return render_template('research.html', result=result, history=history, enabled=enabled, timeout_seconds=SEARCH_DRAFT_TIMEOUT)


@app.route('/editor/audit')
@admin_required
def audit_log():
    rows=db().execute('SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200').fetchall()
    return render_template('audit.html',rows=rows)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG')=='1')
else:
    init_db()
