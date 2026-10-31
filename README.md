# Library Information System (MongoDB + Python)

A menu-driven NoSQL project for managing a college library with two sections: **Engineering** and **MBA**.
It comes in two forms that share the same MongoDB database (`library_db`):

- `library_nosql.py` is a **console menu** application (PyMongo).
- `library_web.py` is a **web application** (Flask + PyMongo) with a dashboard, live search and reports.

## Features

- Add, view, search, update and delete books, with different fields per section
  (Engineering: branch and edition; MBA: specialization and case-study flag).
- Register, edit and delete members, with a profile page showing loans and fines.
- Issue, return and renew books (14-day loan, max 3 books per member, max 2 renewals).
- Automatic fine calculation (Rs. 2 per day after the due date).
- Reports built with the MongoDB aggregation pipeline: copies by category, most issued books,
  top borrowers, overdue books and total fines.
- Web app extras: dashboard charts, live search and sorting, light and dark theme, CSV export.

## NoSQL design

| Collection     | Purpose                                | Key fields                                                                          |
|----------------|----------------------------------------|-------------------------------------------------------------------------------------|
| `books`        | Catalogue of both libraries            | `dept`, `book_id`, `title`, `author`, `total_copies`, `available`, plus section-specific fields |
| `members`      | Registered students                    | `dept`, `member_id`, `name`, `phone`, `email`                                       |
| `transactions` | Issue, return and renewal records      | `dept`, `member_id`, `book_id`, `issue_date`, `due_date`, `return_date`, `fine`, `status` |

- **Flexible schema:** Engineering and MBA books live in the same collection with different extra fields.
- **Indexes:** unique compound indexes on `(dept, book_id)` and `(dept, member_id)`.
- **Atomic issue:** a conditional `update_one` with `$inc` stops two members getting the last copy.

## Setup

Requirements: Python 3.9+ and a running MongoDB server (`mongodb://localhost:27017`).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run the console menu

```bash
python3 library_nosql.py
```

Choose a section, then option **12** to load sample data.

### Run the web app

```bash
python3 library_web.py
```

Open http://127.0.0.1:5000 and click **Load sample data** on the dashboard.

## Project structure

```
.
├── library_nosql.py   # console menu application
├── library_web.py     # Flask web application (self-contained)
├── requirements.txt
└── README.md
```

## Useful mongosh queries

```javascript
use library_db
show collections
db.books.find({ dept: "Engineering" })
db.transactions.find({ status: "Issued" })
db.books.aggregate([{ $group: { _id: "$dept", copies: { $sum: "$total_copies" } } }])
```

## License

Released under the [MIT License](LICENSE).

## Author

Himanshu Thakre
