import os
import re
import sqlite3
import secrets
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('DATABASE_PATH', BASE_DIR / 'instance' / 'newsroom.db'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
csrf = CSRFProtect(app)

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
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        details TEXT,
        created_at TEXT NOT NULL
    );
    ''')
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


@app.context_processor
def inject_globals():
    return {'CATEGORIES': CATEGORIES, 'WORKFLOW': WORKFLOW, 'current_year': datetime.now(UTC).year}


@app.route('/health')
def health():
    try:
        db().execute('SELECT 1').fetchone()
        return {'status': 'ok'}, 200
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
    return render_template('story.html', story=item, related=related)


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
@login_required
def dashboard():
    counts = {row['status']: row['n'] for row in db().execute('SELECT status,COUNT(*) n FROM submissions GROUP BY status')}
    submissions = db().execute('SELECT * FROM submissions ORDER BY updated_at DESC LIMIT 50').fetchall()
    stories = db().execute('SELECT * FROM stories ORDER BY updated_at DESC LIMIT 20').fetchall()
    issues = db().execute('SELECT * FROM issues ORDER BY issue_month DESC').fetchall()
    return render_template('dashboard.html', counts=counts, submissions=submissions, stories=stories, issues=issues)


@app.route('/editor/submission/<int:item_id>', methods=['GET', 'POST'])
@login_required
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
@login_required
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
            db().commit(); audit(action,'story',sid,title); flash('Story saved.','success'); return redirect(url_for('edit_story', item_id=sid))
        except sqlite3.IntegrityError:
            flash('That URL slug is already in use.','error')
    return render_template('edit_story.html', item=item)


@app.route('/editor/issue/new', methods=['GET','POST'])
@app.route('/editor/issue/<int:item_id>', methods=['GET','POST'])
@login_required
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


@app.route('/editor/audit')
@login_required
def audit_log():
    rows=db().execute('SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200').fetchall()
    return render_template('audit.html',rows=rows)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG')=='1')
else:
    init_db()
