-- SQL seed data for demo database
-- ============================================================
-- Library Management System — Demo Database
-- ============================================================

-- Drop tables if they exist (for clean re-runs)
DROP TABLE IF EXISTS borrowings;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS members;


-- ============================================================
-- TABLE: members
-- ============================================================
CREATE TABLE members (
    member_id     SERIAL PRIMARY KEY,
    name          VARCHAR(100)        NOT NULL,
    email         VARCHAR(150) UNIQUE NOT NULL,
    city          VARCHAR(100)        NOT NULL,
    joined_date   DATE                NOT NULL
);


-- ============================================================
-- TABLE: books
-- ============================================================
CREATE TABLE books (
    book_id          SERIAL PRIMARY KEY,
    title            VARCHAR(200)  NOT NULL,
    author           VARCHAR(100)  NOT NULL,
    genre            VARCHAR(50)   NOT NULL,
    published_year   INT           NOT NULL,
    available_copies INT           NOT NULL DEFAULT 0
);


-- ============================================================
-- TABLE: borrowings
-- ============================================================
CREATE TABLE borrowings (
    borrow_id    SERIAL PRIMARY KEY,
    book_id      INT  NOT NULL REFERENCES books(book_id),
    member_id    INT  NOT NULL REFERENCES members(member_id),
    borrow_date  DATE NOT NULL,
    return_date  DATE,                         -- NULL means not yet returned
    status       VARCHAR(20) NOT NULL          -- 'returned', 'borrowed', 'overdue'
);


-- ============================================================
-- SEED: members (15 rows)
-- ============================================================
INSERT INTO members (name, email, city, joined_date) VALUES
('Aarav Mehta',     'aarav.mehta@email.com',     'Mumbai',    '2021-03-15'),
('Priya Sharma',    'priya.sharma@email.com',     'Delhi',     '2020-07-22'),
('Rohan Verma',     'rohan.verma@email.com',      'Bangalore', '2022-01-10'),
('Sneha Patil',     'sneha.patil@email.com',      'Pune',      '2019-11-05'),
('Arjun Nair',      'arjun.nair@email.com',       'Chennai',   '2023-02-28'),
('Kavya Reddy',     'kavya.reddy@email.com',      'Hyderabad', '2021-08-14'),
('Vikram Singh',    'vikram.singh@email.com',     'Jaipur',    '2020-04-30'),
('Ananya Das',      'ananya.das@email.com',       'Kolkata',   '2022-06-18'),
('Rahul Gupta',     'rahul.gupta@email.com',      'Mumbai',    '2021-12-01'),
('Meera Iyer',      'meera.iyer@email.com',       'Bangalore', '2023-05-09'),
('Karan Malhotra',  'karan.malhotra@email.com',   'Delhi',     '2019-09-17'),
('Divya Pillai',    'divya.pillai@email.com',     'Kochi',     '2022-03-25'),
('Aditya Joshi',    'aditya.joshi@email.com',     'Pune',      '2020-10-11'),
('Nisha Tiwari',    'nisha.tiwari@email.com',     'Lucknow',   '2021-07-03'),
('Siddharth Bose',  'siddharth.bose@email.com',   'Kolkata',   '2023-01-20');


-- ============================================================
-- SEED: books (20 rows)
-- ============================================================
INSERT INTO books (title, author, genre, published_year, available_copies) VALUES
('The Alchemist',                  'Paulo Coelho',        'Fiction',       1988, 3),
('Sapiens',                        'Yuval Noah Harari',   'Non-Fiction',   2011, 2),
('Atomic Habits',                  'James Clear',         'Self-Help',     2018, 4),
('1984',                           'George Orwell',       'Dystopian',     1949, 2),
('The Great Gatsby',               'F. Scott Fitzgerald', 'Classic',       1925, 1),
('Educated',                       'Tara Westover',       'Memoir',        2018, 3),
('Dune',                           'Frank Herbert',       'Sci-Fi',        1965, 2),
('The Pragmatic Programmer',       'David Thomas',        'Technology',    1999, 2),
('Clean Code',                     'Robert C. Martin',    'Technology',    2008, 3),
('Think and Grow Rich',            'Napoleon Hill',       'Self-Help',     1937, 2),
('To Kill a Mockingbird',          'Harper Lee',          'Classic',       1960, 2),
('The Subtle Art of Not Giving Up','Mark Manson',         'Self-Help',     2016, 4),
('Ikigai',                         'Hector Garcia',       'Self-Help',     2016, 3),
('A Brief History of Time',        'Stephen Hawking',     'Science',       1988, 1),
('Harry Potter and the Sorcerer',  'J.K. Rowling',        'Fantasy',       1997, 5),
('The Hitchhiker\'s Guide',        'Douglas Adams',       'Sci-Fi',        1979, 2),
('Becoming',                       'Michelle Obama',      'Memoir',        2018, 3),
('Zero to One',                    'Peter Thiel',         'Non-Fiction',   2014, 2),
('The Psychology of Money',        'Morgan Housel',       'Non-Fiction',   2020, 4),
('Thinking, Fast and Slow',        'Daniel Kahneman',     'Non-Fiction',   2011, 2);


-- ============================================================
-- SEED: borrowings (25 rows — mix of returned, borrowed, overdue)
-- ============================================================
INSERT INTO borrowings (book_id, member_id, borrow_date, return_date, status) VALUES
(1,  1,  '2024-01-10', '2024-01-25', 'returned'),
(2,  2,  '2024-02-05', '2024-02-20', 'returned'),
(3,  3,  '2024-03-01', NULL,         'borrowed'),
(4,  4,  '2024-01-15', '2024-01-30', 'returned'),
(5,  5,  '2024-02-18', NULL,         'overdue'),
(6,  6,  '2024-03-10', '2024-03-25', 'returned'),
(7,  7,  '2024-04-01', NULL,         'borrowed'),
(8,  8,  '2024-01-20', '2024-02-05', 'returned'),
(9,  9,  '2024-02-28', NULL,         'overdue'),
(10, 10, '2024-03-15', '2024-03-30', 'returned'),
(11, 11, '2024-04-05', NULL,         'borrowed'),
(12, 12, '2024-01-08', '2024-01-22', 'returned'),
(13, 13, '2024-02-12', NULL,         'overdue'),
(14, 14, '2024-03-20', '2024-04-04', 'returned'),
(15, 15, '2024-04-10', NULL,         'borrowed'),
(3,  1,  '2024-02-01', '2024-02-15', 'returned'),
(7,  2,  '2024-03-05', NULL,         'borrowed'),
(19, 3,  '2024-04-02', NULL,         'borrowed'),
(20, 4,  '2024-01-25', '2024-02-10', 'returned'),
(15, 5,  '2024-02-22', NULL,         'overdue'),
(1,  6,  '2024-03-18', '2024-04-01', 'returned'),
(9,  7,  '2024-04-08', NULL,         'borrowed'),
(2,  8,  '2024-01-30', '2024-02-14', 'returned'),
(12, 9,  '2024-03-25', NULL,         'overdue'),
(18, 10, '2024-04-12', NULL,         'borrowed');