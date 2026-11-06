PRAGMA foreign_keys = ON;

CREATE TABLE student (
    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    branch     TEXT NOT NULL,
    cgpa       REAL NOT NULL CHECK (cgpa BETWEEN 0 AND 10),
    backlogs   INTEGER NOT NULL DEFAULT 0 CHECK (backlogs >= 0)
);

CREATE TABLE company (
    company_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    sector     TEXT,
    location   TEXT
);

CREATE TABLE drive (
    drive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES company(company_id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    package_lpa REAL CHECK (package_lpa >= 0),
    min_cgpa    REAL NOT NULL DEFAULT 0 CHECK (min_cgpa BETWEEN 0 AND 10),
    drive_date  TEXT
);

CREATE TABLE application (
    app_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES student(student_id) ON DELETE CASCADE,
    drive_id   INTEGER NOT NULL REFERENCES drive(drive_id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'Applied'
               CHECK (status IN ('Applied', 'Shortlisted', 'Selected', 'Rejected')),
    UNIQUE (student_id, drive_id)
);

CREATE TABLE offer (
    offer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id       INTEGER NOT NULL UNIQUE REFERENCES application(app_id) ON DELETE CASCADE,
    ctc_lpa      REAL NOT NULL CHECK (ctc_lpa >= 0),
    joining_date TEXT
);

CREATE VIEW eligible_drives AS
SELECT s.student_id, d.drive_id, d.role, d.min_cgpa
FROM student s
JOIN drive d ON s.cgpa >= d.min_cgpa;

-- Sample data
INSERT INTO student (name, email, branch, cgpa, backlogs) VALUES
    ('Aarav Sharma', 'aarav@college.edu', 'CSE', 8.9, 0),
    ('Diya Patel',   'diya@college.edu',   'CSE', 9.2, 0),
    ('Rohan Mehta',  'rohan@college.edu',  'ECE', 7.4, 1),
    ('Sneha Iyer',   'sneha@college.edu',  'IT',  8.1, 0),
    ('Kabir Singh',  'kabir@college.edu',  'MECH', 6.8, 2);

INSERT INTO company (name, sector, location) VALUES
    ('TechNova',   'Software',   'Bengaluru'),
    ('DataWorks',  'Analytics',  'Hyderabad'),
    ('BuildCorp',  'Core',       'Pune');

INSERT INTO drive (company_id, role, package_lpa, min_cgpa, drive_date) VALUES
    (1, 'Software Engineer', 12.0, 8.0, '2026-11-20'),
    (2, 'Data Analyst',       8.5, 7.0, '2026-11-25'),
    (3, 'Graduate Engineer',  5.0, 6.5, '2026-12-02');

INSERT INTO application (student_id, drive_id, status) VALUES
    (1, 1, 'Selected'),
    (2, 1, 'Selected'),
    (3, 2, 'Shortlisted'),
    (4, 2, 'Selected'),
    (5, 3, 'Rejected');

INSERT INTO offer (app_id, ctc_lpa, joining_date) VALUES
    (1, 12.0, '2027-07-01'),
    (2, 12.5, '2027-07-01'),
    (4,  8.5, '2027-07-15');
