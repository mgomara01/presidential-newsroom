from datetime import UTC, datetime

PUBLIC_LEADERSHIP = [
    ('Tweed Roosevelt','Great-grandson of Theodore Roosevelt','President of the Society and chairman of the Theodore Roosevelt Institute.','', '', 'Officer - President'),
    ('Massee McKinley','','Vice President and Chief of Staff of the Society.','', '', 'Officer - Vice President and Chief of Staff'),
    ('Lynda Johnson Robb','','Vice President of the Society.','', '', 'Officer - Vice President'),
    ('Clifton Truman Daniel','','Vice President of the Society.','', '', 'Officer - Vice President'),
    ('Austin Hayes','','Treasurer of the Society.','', '', 'Officer - Treasurer'),
    ('Hobart P. "Hobey" Bauhan','Direct descendant of John Adams and John Quincy Adams','Government-relations executive and president of the Virginia Poultry Federation.','', 'Virginia', 'Board of Trustees'),
    ('Sarah Garfield Berry','Great-great-granddaughter of James A. Garfield','Senior wealth-management advisor and Massachusetts civic leader.','', 'Massachusetts', 'Board of Trustees'),
    ('James Earl Carter IV','Grandson of Jimmy Carter','Public-policy graduate, political researcher, and founder of Carter Research.','', '', 'Board of Trustees'),
    ('George Cleveland','Grandson of Grover Cleveland','Radio news director, historian, speaker, and advisor to presidential-history organizations.','', 'New Hampshire', 'Board of Trustees'),
    ('Arnold Cogswell, Jr.','Great-great-great-nephew of Chester A. Arthur','Former historic archaeologist, museum administrator, and social-studies teacher.','Williamsburg', 'Virginia', 'Board of Trustees'),
    ('Ulysses Grant Dietz','Great-great-grandson of Ulysses S. Grant','Retired museum curator, author, and board member of the U.S. Grant Presidential Library and Museum.','', '', 'Board of Trustees'),
    ('Mark H. Ellis','','Member of the Society Board of Trustees.','', '', 'Board of Trustees'),
    ('Richard Gatchell, Jr.','Fifth great-grandson of James Monroe','History graduate, telecommunications professional, and member of the Society of the Cincinnati in Virginia.','Baltimore', 'Maryland', 'Board of Trustees'),
    ('James A. Garfield III','Great-great-great-grandson of James A. Garfield','Professor and athletic trainer at Case Western Reserve University and supporter of Garfield historic sites.','Cleveland', 'Ohio', 'Board of Trustees'),
    ('Jennifer Coolidge Sayles Harville','Great-granddaughter of Calvin Coolidge','Author, lecturer, public-health graduate, and family historian.','', '', 'Board of Trustees'),
    ('Edward Hayes','','Member of the Society Board of Trustees.','', '', 'Board of Trustees'),
    ('Leslie Hoover-Lauble','Great-granddaughter of Herbert Hoover','Volunteer, family historian, and active participant in Hoover Presidential Library and West Branch programming.','Hood River', 'Oregon', 'Board of Trustees'),
    ('Samuel LeBlond','','Advisory Board Member of the Society.','', '', 'Advisory Board Member'),
    ('Michael G. O\'Mara','Fifth great-nephew of James Madison','Business executive and custodian of Madison-related historical artifacts.','Tampa', 'Florida', 'Board of Trustees'),
    ('Sharon Polk Smith','','Member of the Society Board of Trustees.','', '', 'Board of Trustees'),
    ('Ashley Reagan','Granddaughter of Ronald Reagan','Educator and participant in the Reagan Legacy Foundation.','', '', 'Advisory Board Member'),
    ('Patricia M. Taft','Great-granddaughter of William Howard Taft','Interior designer and advocate for presidential and First Lady history.','Santa Monica', 'California', 'Board of Trustees'),
    ('Bob Taft','','Former Governor of Ohio and Distinguished Research Associate at the University of Dayton.','', 'Ohio', 'Advisory Board Member'),
    ('Birchard M. Taylor','Great-great-grandson of Rutherford B. Hayes','Engineer and business professional.','', '', 'Board of Trustees'),
    ('Jim Walker','','Member of the Society Board of Trustees.','', '', 'Board of Trustees'),
    ('John Hamilton Works, Jr.','Seventh-generation lineal descendant of Thomas Jefferson','Attorney, international-finance advisor, historical-society leader, and newsletter editor.','', '', 'Board of Trustees'),
    ('Tim York','','Member of the Society Board of Trustees.','', '', 'Board of Trustees'),
]


def seed_public_leadership(conn):
    now = datetime.now(UTC).isoformat()
    for full_name, connection, biography, city, state, role in PUBLIC_LEADERSHIP:
        row = conn.execute('SELECT id FROM members WHERE full_name=?', (full_name,)).fetchone()
        if row:
            conn.execute('UPDATE members SET presidential_connection=?, biography=?, city=?, state=?, visibility=?, committee=?, updated_at=? WHERE id=?',
                         (connection, biography, city, state, 'Public', role, now, row[0]))
        else:
            conn.execute('INSERT INTO members(user_id,full_name,presidential_connection,biography,city,state,visibility,committee,phone,created_at,updated_at) VALUES(NULL,?,?,?,?,?,?,?,?,?,?)',
                         (full_name, connection, biography, city, state, 'Public', role, '', now, now))
