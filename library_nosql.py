"""
Library Information System - Menu Driven NoSQL Project (MongoDB + Python)
Sections : Engineering library, MBA library
Database : library_db
Collections : books, members, transactions

Run:  pip install pymongo
      python library_nosql.py
"""
import re
import sys
from datetime import datetime, timedelta

from pymongo import MongoClient, errors

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "library_db"
LOAN_DAYS = 14        # days a book can be kept
FINE_PER_DAY = 2      # Rs. per day after due date
MAX_BOOKS = 3         # max active issues per member

# Each department stores different extra fields -> flexible (schema-less) documents
DEPARTMENTS = {
    "1": {"name": "Engineering", "group_field": "branch",
          "extra": [("branch", "Branch (CSE/ENTC/Mech/Civil)"), ("edition", "Edition")]},
    "2": {"name": "MBA", "group_field": "specialization",
          "extra": [("specialization", "Specialization (Finance/Marketing/HR/Operations)"),
                    ("case_study", "Case-study book? (yes/no)")]},
}

SAMPLE_BOOKS = [
    {"dept": "Engineering", "book_id": "E101", "title": "Database System Concepts", "author": "Silberschatz",
     "publisher": "McGraw Hill", "year": 2019, "branch": "CSE", "edition": "7th", "total_copies": 5},
    {"dept": "Engineering", "book_id": "E102", "title": "Engineering Thermodynamics", "author": "P.K. Nag",
     "publisher": "McGraw Hill", "year": 2017, "branch": "Mech", "edition": "6th", "total_copies": 3},
    {"dept": "Engineering", "book_id": "E103", "title": "Digital Signal Processing", "author": "Proakis",
     "publisher": "Pearson", "year": 2014, "branch": "ENTC", "edition": "4th", "total_copies": 4},
    {"dept": "MBA", "book_id": "M201", "title": "Marketing Management", "author": "Philip Kotler",
     "publisher": "Pearson", "year": 2016, "specialization": "Marketing", "case_study": "no", "total_copies": 6},
    {"dept": "MBA", "book_id": "M202", "title": "Corporate Finance", "author": "Brealey & Myers",
     "publisher": "McGraw Hill", "year": 2020, "specialization": "Finance", "case_study": "yes", "total_copies": 4},
    {"dept": "MBA", "book_id": "M203", "title": "Organizational Behaviour", "author": "Stephen Robbins",
     "publisher": "Pearson", "year": 2018, "specialization": "HR", "case_study": "yes", "total_copies": 3},
]
SAMPLE_MEMBERS = [
    {"dept": "Engineering", "member_id": "ENG01", "name": "Aarav Patil", "phone": "9000000001", "email": "aarav@college.edu"},
    {"dept": "Engineering", "member_id": "ENG02", "name": "Sneha Kulkarni", "phone": "9000000002", "email": "sneha@college.edu"},
    {"dept": "MBA", "member_id": "MBA01", "name": "Rohan Deshmukh", "phone": "9000000003", "email": "rohan@college.edu"},
    {"dept": "MBA", "member_id": "MBA02", "name": "Priya Joshi", "phone": "9000000004", "email": "priya@college.edu"},
]


# ----------------------------- helpers -----------------------------
def ask(prompt, required=True):
    while True:
        val = input(f"  {prompt}: ").strip()
        if val or not required:
            return val
        print("  ! This field is required.")


def ask_int(prompt, minimum=0):
    while True:
        try:
            n = int(input(f"  {prompt}: ").strip())
            if n >= minimum:
                return n
        except ValueError:
            pass
        print(f"  ! Enter a whole number >= {minimum}.")


def fmt_date(d):
    return d.strftime("%d-%m-%Y") if d else "-"


def show_book(b):
    extras = ", ".join(f"{k}: {v}" for k, v in b.items()
                       if k not in ("_id", "dept", "book_id", "title", "author", "publisher",
                                    "year", "total_copies", "available", "added_on"))
    print(f"  [{b['book_id']}] {b['title']} | {b['author']} | {b.get('publisher', '-')} | "
          f"{b.get('year', '-')} | {extras} | Available {b['available']}/{b['total_copies']}")


def setup(db):
    db.books.create_index([("dept", 1), ("book_id", 1)], unique=True)
    db.members.create_index([("dept", 1), ("member_id", 1)], unique=True)
    db.transactions.create_index([("dept", 1), ("status", 1)])


def choose_department():
    print("\nSelect Library Section:\n  1. Engineering\n  2. MBA")
    while True:
        c = input("  Choice: ").strip()
        if c in DEPARTMENTS:
            return DEPARTMENTS[c]
        print("  ! Enter 1 or 2.")


# ----------------------------- book operations -----------------------------
def add_book(db, dept):
    print(f"\n-- Add Book ({dept['name']}) --")
    book = {"dept": dept["name"], "book_id": ask("Book ID").upper(), "title": ask("Title"),
            "author": ask("Author"), "publisher": ask("Publisher", False), "year": ask_int("Year", 1000)}
    for key, label in dept["extra"]:
        book[key] = ask(label, False)
    copies = ask_int("Number of copies", 1)
    book.update(total_copies=copies, available=copies, added_on=datetime.now())
    try:
        db.books.insert_one(book)
        print("  Book added.")
    except errors.DuplicateKeyError:
        print("  ! A book with this ID already exists in this section.")


def view_books(db, dept):
    print(f"\n-- All Books ({dept['name']}) --")
    books = list(db.books.find({"dept": dept["name"]}).sort("book_id", 1))
    if not books:
        print("  No books found.")
    for b in books:
        show_book(b)


def search_books(db, dept):
    print(f"\n-- Search Books ({dept['name']}) --")
    pattern = {"$regex": re.escape(ask("Keyword (title / author / category)")), "$options": "i"}
    query = {"dept": dept["name"], "$or": [{"title": pattern}, {"author": pattern},
                                           {dept["group_field"]: pattern}]}
    found = list(db.books.find(query))
    print(f"  {len(found)} result(s).")
    for b in found:
        show_book(b)


def update_book(db, dept):
    print(f"\n-- Update Book ({dept['name']}) --")
    book = db.books.find_one({"dept": dept["name"], "book_id": ask("Book ID").upper()})
    if not book:
        return print("  ! Book not found.")
    show_book(book)
    print("  1. Change title/author   2. Change total copies")
    c = ask("Choice")
    if c == "1":
        title = ask(f"New title [{book['title']}]", False) or book["title"]
        author = ask(f"New author [{book['author']}]", False) or book["author"]
        db.books.update_one({"_id": book["_id"]}, {"$set": {"title": title, "author": author}})
        print("  Updated.")
    elif c == "2":
        new_total = ask_int("New total copies", 1)
        delta = new_total - book["total_copies"]
        if book["available"] + delta < 0:
            return print("  ! Cannot reduce below the number of copies currently issued.")
        db.books.update_one({"_id": book["_id"]},
                            {"$set": {"total_copies": new_total}, "$inc": {"available": delta}})
        print("  Updated.")
    else:
        print("  ! Invalid choice.")


def delete_book(db, dept):
    print(f"\n-- Delete Book ({dept['name']}) --")
    book = db.books.find_one({"dept": dept["name"], "book_id": ask("Book ID").upper()})
    if not book:
        return print("  ! Book not found.")
    if book["available"] != book["total_copies"]:
        return print("  ! Copies are still issued; cannot delete.")
    db.books.delete_one({"_id": book["_id"]})
    print("  Book deleted.")


# ----------------------------- member operations -----------------------------
def add_member(db, dept):
    print(f"\n-- Register Member ({dept['name']}) --")
    member = {"dept": dept["name"], "member_id": ask("Member ID").upper(), "name": ask("Name"),
              "phone": ask("Phone", False), "email": ask("Email", False), "joined_on": datetime.now()}
    try:
        db.members.insert_one(member)
        print("  Member registered.")
    except errors.DuplicateKeyError:
        print("  ! Member ID already exists in this section.")


def view_members(db, dept):
    print(f"\n-- Members ({dept['name']}) --")
    for m in db.members.find({"dept": dept["name"]}).sort("member_id", 1):
        active = db.transactions.count_documents(
            {"dept": dept["name"], "member_id": m["member_id"], "status": "Issued"})
        print(f"  [{m['member_id']}] {m['name']} | {m.get('phone', '-')} | {m.get('email', '-')} | "
              f"Books issued: {active}")


# ----------------------------- issue / return -----------------------------
def issue_book(db, dept):
    print(f"\n-- Issue Book ({dept['name']}) --")
    member_id, book_id = ask("Member ID").upper(), ask("Book ID").upper()
    if not db.members.find_one({"dept": dept["name"], "member_id": member_id}):
        return print("  ! Member not found.")
    if db.transactions.count_documents(
            {"dept": dept["name"], "member_id": member_id, "status": "Issued"}) >= MAX_BOOKS:
        return print(f"  ! Limit of {MAX_BOOKS} books reached.")
    if db.transactions.find_one({"dept": dept["name"], "member_id": member_id,
                                 "book_id": book_id, "status": "Issued"}):
        return print("  ! This member already has this book.")
    # atomic: decrement only if a copy is available
    res = db.books.update_one({"dept": dept["name"], "book_id": book_id, "available": {"$gt": 0}},
                              {"$inc": {"available": -1}})
    if res.modified_count == 0:
        return print("  ! Book not found or no copies available.")
    now = datetime.now()
    db.transactions.insert_one({"dept": dept["name"], "member_id": member_id, "book_id": book_id,
                                "issue_date": now, "due_date": now + timedelta(days=LOAN_DAYS),
                                "return_date": None, "fine": 0, "status": "Issued"})
    print(f"  Issued. Due date: {fmt_date(now + timedelta(days=LOAN_DAYS))}")


def return_book(db, dept):
    print(f"\n-- Return Book ({dept['name']}) --")
    member_id, book_id = ask("Member ID").upper(), ask("Book ID").upper()
    txn = db.transactions.find_one({"dept": dept["name"], "member_id": member_id,
                                    "book_id": book_id, "status": "Issued"})
    if not txn:
        return print("  ! No matching issued record.")
    now = datetime.now()
    late_days = max(0, (now.date() - txn["due_date"].date()).days)
    fine = late_days * FINE_PER_DAY
    db.transactions.update_one({"_id": txn["_id"]},
                               {"$set": {"return_date": now, "fine": fine, "status": "Returned"}})
    db.books.update_one({"dept": dept["name"], "book_id": book_id}, {"$inc": {"available": 1}})
    print(f"  Returned. Late by {late_days} day(s). Fine: Rs. {fine}")


def view_issued(db, dept):
    print(f"\n-- Currently Issued Books ({dept['name']}) --")
    now = datetime.now()
    rows = list(db.transactions.find({"dept": dept["name"], "status": "Issued"}))
    if not rows:
        print("  None.")
    for t in rows:
        flag = "  ** OVERDUE **" if t["due_date"] < now else ""
        print(f"  {t['member_id']} -> {t['book_id']} | issued {fmt_date(t['issue_date'])} | "
              f"due {fmt_date(t['due_date'])}{flag}")


# ----------------------------- reports (aggregation) -----------------------------
def reports(db, dept):
    d = dept["name"]
    print(f"\n-- Reports ({d}) --")
    print("  1. Books per " + dept["group_field"])
    print("  2. Most issued books (Top 5)")
    print("  3. Overdue books with fine")
    print("  4. Total fine collected")
    c = ask("Choice")
    if c == "1":
        pipe = [{"$match": {"dept": d}},
                {"$group": {"_id": f"${dept['group_field']}", "titles": {"$sum": 1},
                            "copies": {"$sum": "$total_copies"}}},
                {"$sort": {"copies": -1}}]
        for r in db.books.aggregate(pipe):
            print(f"  {r['_id'] or 'Unspecified'}: {r['titles']} title(s), {r['copies']} copies")
    elif c == "2":
        pipe = [{"$match": {"dept": d}},
                {"$group": {"_id": "$book_id", "times": {"$sum": 1}}},
                {"$sort": {"times": -1}}, {"$limit": 5}]
        for r in db.transactions.aggregate(pipe):
            book = db.books.find_one({"dept": d, "book_id": r["_id"]}) or {}
            print(f"  {r['_id']} {book.get('title', '')}: issued {r['times']} time(s)")
    elif c == "3":
        now = datetime.now()
        rows = list(db.transactions.find({"dept": d, "status": "Issued", "due_date": {"$lt": now}}))
        if not rows:
            print("  No overdue books.")
        for t in rows:
            days = (now.date() - t["due_date"].date()).days
            print(f"  {t['member_id']} -> {t['book_id']} | {days} day(s) late | fine so far Rs. {days * FINE_PER_DAY}")
    elif c == "4":
        res = list(db.transactions.aggregate([{"$match": {"dept": d}},
                                              {"$group": {"_id": None, "total": {"$sum": "$fine"}}}]))
        print(f"  Total fine collected: Rs. {res[0]['total'] if res else 0}")
    else:
        print("  ! Invalid choice.")


def load_sample(db, dept):
    added = 0
    for b in SAMPLE_BOOKS:
        b = dict(b, available=b["total_copies"], added_on=datetime.now())
        try:
            db.books.insert_one(b)
            added += 1
        except errors.DuplicateKeyError:
            pass
    for m in SAMPLE_MEMBERS:
        try:
            db.members.insert_one(dict(m, joined_on=datetime.now()))
            added += 1
        except errors.DuplicateKeyError:
            pass
    print(f"  Sample data loaded ({added} new document(s)).")


# ----------------------------- main menu -----------------------------
MENU = """
==== LIBRARY INFORMATION SYSTEM  [{dept}] ====
  1. Add book              7. View members
  2. View all books        8. Issue book
  3. Search books          9. Return book
  4. Update book          10. View issued books
  5. Delete book          11. Reports
  6. Register member      12. Load sample data
 13. Switch section (Engineering / MBA)
  0. Exit"""

ACTIONS = {"1": add_book, "2": view_books, "3": search_books, "4": update_book, "5": delete_book,
           "6": add_member, "7": view_members, "8": issue_book, "9": return_book,
           "10": view_issued, "11": reports, "12": load_sample}


def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    return client[DB_NAME]


def main():
    try:
        db = get_db()
    except Exception as e:
        sys.exit(f"Cannot connect to MongoDB at {MONGO_URI}: {e}")
    setup(db)
    dept = choose_department()
    while True:
        print(MENU.format(dept=dept["name"]))
        choice = input("Enter choice: ").strip()
        if choice == "0":
            print("Goodbye!")
            break
        if choice == "13":
            dept = choose_department()
        elif choice in ACTIONS:
            try:
                ACTIONS[choice](db, dept)
            except errors.PyMongoError as e:
                print(f"  ! Database error: {e}")
        else:
            print("  ! Invalid choice.")


if __name__ == "__main__":
    main()
