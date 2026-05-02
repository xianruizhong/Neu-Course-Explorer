-- PostgreSQL schema for NEU Course Explorer
-- Applied automatically by the scraper on first run

CREATE TABLE IF NOT EXISTS terms (
    code        TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjects (
    code        TEXT NOT NULL,
    description TEXT NOT NULL,
    term_code   TEXT NOT NULL REFERENCES terms(code) ON DELETE CASCADE,
    PRIMARY KEY (code, term_code)
);

CREATE TABLE IF NOT EXISTS courses (
    crn                 TEXT NOT NULL,
    term_code           TEXT NOT NULL REFERENCES terms(code) ON DELETE CASCADE,
    subject             TEXT NOT NULL,
    subject_description TEXT,
    course_number       TEXT NOT NULL,
    title               TEXT,
    credit_hour_low     DOUBLE PRECISION,
    credit_hour_high    DOUBLE PRECISION,
    campus              TEXT,
    schedule_type       TEXT,
    part_of_term        TEXT,
    enrollment          INTEGER,
    max_enrollment      INTEGER,
    seats_available     INTEGER,
    wait_count          INTEGER,
    wait_capacity       INTEGER,
    wait_available      INTEGER,
    open_section        BOOLEAN DEFAULT FALSE,
    description         TEXT,
    prerequisites       TEXT,
    scraped_at          TEXT,
    PRIMARY KEY (crn, term_code)
);

CREATE TABLE IF NOT EXISTS meetings (
    id            SERIAL PRIMARY KEY,
    crn           TEXT NOT NULL,
    term_code     TEXT NOT NULL,
    begin_time    TEXT,
    end_time      TEXT,
    start_date    TEXT,
    end_date      TEXT,
    building      TEXT,
    building_desc TEXT,
    room          TEXT,
    monday        BOOLEAN DEFAULT FALSE,
    tuesday       BOOLEAN DEFAULT FALSE,
    wednesday     BOOLEAN DEFAULT FALSE,
    thursday      BOOLEAN DEFAULT FALSE,
    friday        BOOLEAN DEFAULT FALSE,
    saturday      BOOLEAN DEFAULT FALSE,
    sunday        BOOLEAN DEFAULT FALSE,
    schedule_type TEXT,
    FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS faculty (
    id          SERIAL PRIMARY KEY,
    crn         TEXT NOT NULL,
    term_code   TEXT NOT NULL,
    banner_id   TEXT,
    name        TEXT,
    email       TEXT,
    primary_ind BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS section_attributes (
    id          SERIAL PRIMARY KEY,
    crn         TEXT NOT NULL,
    term_code   TEXT NOT NULL,
    code        TEXT,
    description TEXT,
    FOREIGN KEY (crn, term_code) REFERENCES courses(crn, term_code) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_courses_term    ON courses(term_code);
CREATE INDEX IF NOT EXISTS idx_courses_subject ON courses(subject, term_code);
CREATE INDEX IF NOT EXISTS idx_courses_number  ON courses(course_number);

-- Full-text search via GIN index (replaces SQLite FTS5, updates automatically)
CREATE INDEX IF NOT EXISTS idx_courses_fts ON courses
    USING GIN(to_tsvector('english',
        coalesce(subject, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(description, '')
    ));
