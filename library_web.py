"""
Library Information System - Web App v2 (Flask + MongoDB)
Self-contained: no other project file is needed. It uses the same database as the
console menu (library_db -> books, members, transactions).

    pip install flask pymongo
    python3 library_web.py          ->  open http://127.0.0.1:5000
"""
import csv
import io
from datetime import datetime, timedelta

from bson import ObjectId
from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for
from jinja2 import DictLoader
from pymongo import MongoClient, errors

# ============================================================== CONFIG
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "library_db"
LOAN_DAYS, FINE_PER_DAY, MAX_BOOKS, MAX_RENEWALS = 14, 2, 3, 2

DEPTS = {
    "engineering": {"name": "Engineering", "group": "branch", "group_label": "Branch",
                    "extra": [("branch", "Branch"), ("edition", "Edition")],
                    "choices": ["CSE", "ENTC", "Mech", "Civil", "Electrical"]},
    "mba": {"name": "MBA", "group": "specialization", "group_label": "Specialization",
            "extra": [("specialization", "Specialization"), ("case_study", "Case study (yes/no)")],
            "choices": ["Finance", "Marketing", "HR", "Operations"]},
}
NAV = [("dashboard", "Dashboard", "▦"), ("books", "Books", "📚"), ("members", "Members", "👥"),
       ("circulation", "Issue / Return", "🔁"), ("history", "History", "🕑"), ("reports", "Reports", "📊")]

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
# (dept, member, book, issued N days ago, returned N days ago or None)
SAMPLE_LOANS = [
    ("Engineering", "ENG01", "E101", 20, None), ("Engineering", "ENG02", "E103", 3, None),
    ("Engineering", "ENG01", "E102", 30, 12), ("MBA", "MBA01", "M201", 16, None),
    ("MBA", "MBA02", "M202", 2, None), ("MBA", "MBA02", "M203", 25, 15),
]

# ============================================================== APP + DB
app = Flask(__name__)
app.secret_key = "library-demo-key"
app.jinja_env.filters["dt"] = lambda v: v.strftime("%d %b %Y") if v else "—"
app.jinja_env.globals.update(NAV=NAV, LOAN_DAYS=LOAN_DAYS, FINE_PER_DAY=FINE_PER_DAY,
                             MAX_BOOKS=MAX_BOOKS, MAX_RENEWALS=MAX_RENEWALS)


def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    database = client[DB_NAME]
    database.books.create_index([("dept", 1), ("book_id", 1)], unique=True)
    database.members.create_index([("dept", 1), ("member_id", 1)], unique=True)
    database.transactions.create_index([("dept", 1), ("status", 1)])
    return database


db = get_db()


# ============================================================== HELPERS
def dept_of(d):
    return DEPTS.get(d) or abort(404)


def render(page, d, **ctx):
    return render_template(f"{page}.html", page=page, d=d, dept=DEPTS[d], **ctx)


def ok(msg):
    flash(msg, "ok")


def err(msg):
    flash(msg, "err")


def idv(text):
    return (text.strip().upper().split() or [""])[0]


def back(d):
    nxt = request.form.get("next", "")
    ok_path = nxt.startswith("/") and not nxt.startswith("//")
    return redirect(nxt if ok_path else url_for("circulation", d=d))


def oid_or_404(tid):
    try:
        return ObjectId(tid)
    except Exception:
        abort(404)


def days_late(t, ref):
    return max(0, (ref.date() - t["due_date"].date()).days)


def title_map(n):
    return {b["book_id"]: b["title"] for b in db.books.find({"dept": n}, {"book_id": 1, "title": 1})}


def by_category(n, group):
    pipe = [{"$match": {"dept": n}}, {"$group": {"_id": "$" + group, "value": {"$sum": "$total_copies"}}},
            {"$sort": {"value": -1}}]
    return [{"label": r["_id"] or "Unspecified", "value": r["value"]} for r in db.books.aggregate(pipe)]


def top_books(n, k=5):
    titles = title_map(n)
    pipe = [{"$match": {"dept": n}}, {"$group": {"_id": "$book_id", "value": {"$sum": 1}}},
            {"$sort": {"value": -1}}, {"$limit": k}]
    return [{"label": f'{r["_id"]} · {titles.get(r["_id"], "")}'[:36], "value": r["value"]}
            for r in db.transactions.aggregate(pipe)]


def top_borrowers(n, k=5):
    names = {m["member_id"]: m["name"] for m in db.members.find({"dept": n})}
    pipe = [{"$match": {"dept": n}}, {"$group": {"_id": "$member_id", "value": {"$sum": 1}}},
            {"$sort": {"value": -1}}, {"$limit": k}]
    return [{"label": f'{r["_id"]} · {names.get(r["_id"], "")}'[:36], "value": r["value"]}
            for r in db.transactions.aggregate(pipe)]


def fine_totals(n, now):
    r = list(db.transactions.aggregate([{"$match": {"dept": n, "status": "Returned"}},
                                        {"$group": {"_id": None, "t": {"$sum": "$fine"}}}]))
    collected = r[0]["t"] if r else 0
    late = db.transactions.find({"dept": n, "status": "Issued", "due_date": {"$lt": now}})
    return collected, sum(days_late(t, now) * FINE_PER_DAY for t in late)


# ============================================================== PAGES
@app.route("/")
def root():
    return redirect(url_for("dashboard", d="engineering"))


@app.errorhandler(404)
def not_found(_e):
    return 'Page not found. <a href="/">Go to the library</a>', 404


@app.route("/<d>/")
def dashboard(d):
    dept = dept_of(d)
    n, now = dept["name"], datetime.now()
    active = {"dept": n, "status": "Issued"}
    agg = list(db.books.aggregate([{"$match": {"dept": n}}, {"$group": {
        "_id": None, "titles": {"$sum": 1}, "copies": {"$sum": "$total_copies"}, "avail": {"$sum": "$available"}}}]))
    a = agg[0] if agg else {"titles": 0, "copies": 0, "avail": 0}
    overdue_q = {**active, "due_date": {"$lt": now}}
    n_overdue = db.transactions.count_documents(overdue_q)
    stats = [
        {"label": "Titles", "value": a["titles"], "sub": f'{a["copies"]} copies in total', "icon": "📚", "tone": ""},
        {"label": "Available now", "value": a["avail"], "sub": f'{a["copies"] - a["avail"]} currently on loan',
         "icon": "✅", "tone": ""},
        {"label": "Members", "value": db.members.count_documents({"dept": n}), "sub": "registered", "icon": "👥",
         "tone": ""},
        {"label": "Overdue", "value": n_overdue, "sub": f'{db.transactions.count_documents(active)} active loans',
         "icon": "⏰", "tone": "bad" if n_overdue else ""},
    ]
    since = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    counts = {}
    for t in db.transactions.find({"dept": n, "issue_date": {"$gte": since}}, {"issue_date": 1}):
        counts[t["issue_date"].date()] = counts.get(t["issue_date"].date(), 0) + 1
    week = []
    for i in range(7):
        day = since + timedelta(days=i)
        week.append({"label": day.strftime("%a"), "value": counts.get(day.date(), 0)})
    return render("dashboard", d, stats=stats, by_cat=by_category(n, dept["group"]), week=week, now=now,
                  recent=list(db.transactions.find({"dept": n}).sort("issue_date", -1).limit(8)),
                  overdue=list(db.transactions.find(overdue_q).sort("due_date", 1).limit(5)), titles=title_map(n))


@app.post("/<d>/sample")
def sample(d):
    dept_of(d)
    now, added = datetime.now(), 0
    for doc, coll in [(dict(b, available=b["total_copies"], added_on=now), db.books) for b in SAMPLE_BOOKS] + \
                     [(dict(m, joined_on=now), db.members) for m in SAMPLE_MEMBERS]:
        try:
            coll.insert_one(doc)
            added += 1
        except errors.DuplicateKeyError:
            pass
    for dname, mid, bid, issued_ago, returned_ago in SAMPLE_LOANS:
        if db.transactions.count_documents({"dept": dname, "member_id": mid, "book_id": bid}):
            continue
        issued = now - timedelta(days=issued_ago)
        due = issued + timedelta(days=LOAN_DAYS)
        rec = {"dept": dname, "member_id": mid, "book_id": bid, "issue_date": issued, "due_date": due,
               "renewals": 0}
        if returned_ago is None:
            took = db.books.update_one({"dept": dname, "book_id": bid, "available": {"$gt": 0}},
                                       {"$inc": {"available": -1}})
            if took.modified_count == 0:
                continue
            rec.update(return_date=None, fine=0, status="Issued")
        else:
            ret = now - timedelta(days=returned_ago)
            rec.update(return_date=ret, fine=max(0, (ret.date() - due.date()).days) * FINE_PER_DAY,
                       status="Returned")
        db.transactions.insert_one(rec)
        added += 1
    ok(f"Sample data ready ({added} new records).")
    return redirect(url_for("dashboard", d=d))


# ---------------------------------------------------------------- books
@app.route("/<d>/books")
def books(d):
    dept = dept_of(d)
    rows = list(db.books.find({"dept": dept["name"]}).sort("book_id", 1))
    keys = ["book_id", "title", "author", "publisher", "year", "total_copies"] + [k for k, _ in dept["extra"]]
    for r in rows:
        r["js"] = {k: r.get(k, "") for k in keys}
    cats = sorted({r.get(dept["group"]) for r in rows if r.get(dept["group"])})
    return render("books", d, rows=rows, cats=cats)


@app.post("/<d>/books/add")
def book_add(d):
    dept, f = dept_of(d), request.form
    try:
        copies, year = int(f["total_copies"]), int(f["year"])
        if copies < 1:
            raise ValueError
        doc = {"dept": dept["name"], "book_id": idv(f["book_id"]), "title": f["title"].strip(),
               "author": f["author"].strip(), "publisher": f.get("publisher", "").strip(), "year": year}
        for k, _lbl in dept["extra"]:
            doc[k] = f.get(k, "").strip()
        doc.update(total_copies=copies, available=copies, added_on=datetime.now())
        db.books.insert_one(doc)
        ok(f'Added "{doc["title"]}".')
    except errors.DuplicateKeyError:
        err("A book with this ID already exists.")
    except ValueError:
        err("Year and copies must be valid numbers (copies at least 1).")
    return redirect(url_for("books", d=d))


@app.post("/<d>/books/<bid>/edit")
def book_edit(d, bid):
    dept, f = dept_of(d), request.form
    b = db.books.find_one({"dept": dept["name"], "book_id": bid})
    if not b:
        err("Book not found.")
        return redirect(url_for("books", d=d))
    try:
        total, year = int(f["total_copies"]), int(f["year"])
        delta = total - b["total_copies"]
        if total < 1 or b["available"] + delta < 0:
            raise ValueError
    except ValueError:
        err("Invalid numbers, or fewer copies than are currently on loan.")
        return redirect(url_for("books", d=d))
    upd = {"title": f["title"].strip(), "author": f["author"].strip(), "publisher": f.get("publisher", "").strip(),
           "year": year, "total_copies": total}
    for k, _lbl in dept["extra"]:
        upd[k] = f.get(k, "").strip()
    db.books.update_one({"_id": b["_id"]}, {"$set": upd, "$inc": {"available": delta}})
    ok(f'Updated "{upd["title"]}".')
    return redirect(url_for("books", d=d))


@app.post("/<d>/books/<bid>/delete")
def book_delete(d, bid):
    n = dept_of(d)["name"]
    b = db.books.find_one({"dept": n, "book_id": bid})
    if b and b["available"] == b["total_copies"]:
        db.books.delete_one({"_id": b["_id"]})
        ok(f'Deleted "{b["title"]}".')
    else:
        err("Cannot delete: book not found or copies are still on loan.")
    return redirect(url_for("books", d=d))


# ---------------------------------------------------------------- members
@app.route("/<d>/members")
def members(d):
    n = dept_of(d)["name"]
    rows = list(db.members.find({"dept": n}).sort("member_id", 1))
    loans = {}
    for t in db.transactions.find({"dept": n, "status": "Issued"}, {"member_id": 1}):
        loans[t["member_id"]] = loans.get(t["member_id"], 0) + 1
    for m in rows:
        m["loans"] = loans.get(m["member_id"], 0)
        m["js"] = {k: m.get(k, "") for k in ("member_id", "name", "phone", "email")}
    return render("members", d, rows=rows)


@app.post("/<d>/members/add")
def member_add(d):
    n, f = dept_of(d)["name"], request.form
    try:
        db.members.insert_one({"dept": n, "member_id": idv(f["member_id"]), "name": f["name"].strip(),
                               "phone": f.get("phone", "").strip(), "email": f.get("email", "").strip(),
                               "joined_on": datetime.now()})
        ok("Member registered.")
    except errors.DuplicateKeyError:
        err("This member ID already exists.")
    return redirect(url_for("members", d=d))


@app.post("/<d>/members/<mid>/edit")
def member_edit(d, mid):
    n, f = dept_of(d)["name"], request.form
    res = db.members.update_one({"dept": n, "member_id": mid}, {"$set": {
        "name": f["name"].strip(), "phone": f.get("phone", "").strip(), "email": f.get("email", "").strip()}})
    (ok if res.matched_count else err)("Member updated." if res.matched_count else "Member not found.")
    return redirect(url_for("members", d=d))


@app.post("/<d>/members/<mid>/delete")
def member_delete(d, mid):
    n = dept_of(d)["name"]
    if db.transactions.count_documents({"dept": n, "member_id": mid, "status": "Issued"}):
        err("Cannot delete: this member still has books on loan.")
    else:
        db.members.delete_one({"dept": n, "member_id": mid})
        ok("Member deleted.")
    return redirect(url_for("members", d=d))


@app.route("/<d>/members/<mid>")
def member(d, mid):
    n, now = dept_of(d)["name"], datetime.now()
    m = db.members.find_one({"dept": n, "member_id": mid}) or abort(404)
    txns = list(db.transactions.find({"dept": n, "member_id": mid}).sort("issue_date", -1))
    active = [t for t in txns if t["status"] == "Issued"]
    return render("member", d, m=m, active=active, past=[t for t in txns if t["status"] != "Issued"], now=now,
                  titles=title_map(n), paid=sum(t["fine"] for t in txns if t["status"] == "Returned"),
                  accruing=sum(days_late(t, now) * FINE_PER_DAY for t in active), total=len(txns))


# ---------------------------------------------------------------- circulation
@app.route("/<d>/circulation")
def circulation(d):
    n, now = dept_of(d)["name"], datetime.now()
    return render("circulation", d, now=now, titles=title_map(n), pre=request.args.get("member", ""),
                  rows=list(db.transactions.find({"dept": n, "status": "Issued"}).sort("due_date", 1)),
                  members_list=list(db.members.find({"dept": n}).sort("member_id", 1)),
                  books_list=list(db.books.find({"dept": n, "available": {"$gt": 0}}).sort("book_id", 1)))


@app.post("/<d>/issue")
def issue(d):
    n = dept_of(d)["name"]
    mid, bid = idv(request.form["member_id"]), idv(request.form["book_id"])
    active = {"dept": n, "member_id": mid, "status": "Issued"}
    if not db.members.find_one({"dept": n, "member_id": mid}):
        err(f"Member {mid} not found.")
    elif db.transactions.count_documents(active) >= MAX_BOOKS:
        err(f"{mid} already has the maximum of {MAX_BOOKS} books.")
    elif db.transactions.find_one({**active, "book_id": bid}):
        err(f"{mid} already has {bid}.")
    elif db.books.update_one({"dept": n, "book_id": bid, "available": {"$gt": 0}},
                             {"$inc": {"available": -1}}).modified_count == 0:
        err(f"Book {bid} not found or no copies available.")
    else:
        now = datetime.now()
        due = now + timedelta(days=LOAN_DAYS)
        db.transactions.insert_one({"dept": n, "member_id": mid, "book_id": bid, "issue_date": now, "due_date": due,
                                    "return_date": None, "fine": 0, "status": "Issued", "renewals": 0})
        ok(f"Issued {bid} to {mid}. Due {due:%d %b %Y}.")
    return redirect(url_for("circulation", d=d))


@app.post("/<d>/return/<tid>")
def return_book(d, tid):
    n, now = dept_of(d)["name"], datetime.now()
    t = db.transactions.find_one({"_id": oid_or_404(tid), "dept": n, "status": "Issued"})
    if not t:
        err("No matching active loan.")
    else:
        late = days_late(t, now)
        fine = late * FINE_PER_DAY
        db.transactions.update_one({"_id": t["_id"]},
                                   {"$set": {"return_date": now, "fine": fine, "status": "Returned"}})
        db.books.update_one({"dept": n, "book_id": t["book_id"]}, {"$inc": {"available": 1}})
        ok(f"Returned {t['book_id']}." + (f" Late by {late} day(s) — fine Rs. {fine}." if late else " No fine."))
    return back(d)


@app.post("/<d>/renew/<tid>")
def renew(d, tid):
    n, now = dept_of(d)["name"], datetime.now()
    t = db.transactions.find_one({"_id": oid_or_404(tid), "dept": n, "status": "Issued"})
    if not t:
        err("No matching active loan.")
    elif t["due_date"] < now:
        err("Overdue books must be returned, not renewed.")
    elif t.get("renewals", 0) >= MAX_RENEWALS:
        err(f"Renewal limit ({MAX_RENEWALS}) reached.")
    else:
        new_due = t["due_date"] + timedelta(days=LOAN_DAYS)
        db.transactions.update_one({"_id": t["_id"]}, {"$set": {"due_date": new_due}, "$inc": {"renewals": 1}})
        ok(f"Renewed {t['book_id']}. New due date {new_due:%d %b %Y}.")
    return back(d)


@app.route("/<d>/history")
def history(d):
    n = dept_of(d)["name"]
    return render("history", d, now=datetime.now(), titles=title_map(n),
                  rows=list(db.transactions.find({"dept": n}).sort("issue_date", -1).limit(500)))


# ---------------------------------------------------------------- reports + export
@app.route("/<d>/reports")
def reports(d):
    dept = dept_of(d)
    n, now = dept["name"], datetime.now()
    collected, accruing = fine_totals(n, now)
    return render("reports", d, now=now, collected=collected, accruing=accruing, titles=title_map(n),
                  by_cat=by_category(n, dept["group"]), top=top_books(n), borrowers=top_borrowers(n),
                  overdue=list(db.transactions.find({"dept": n, "status": "Issued", "due_date": {"$lt": now}})
                               .sort("due_date", 1)))


@app.route("/<d>/export/<what>.csv")
def export(d, what):
    dept = dept_of(d)
    n = dept["name"]
    extra = [k for k, _ in dept["extra"]]
    if what == "books":
        head = ["book_id", "title", "author", "publisher", "year"] + extra + ["total_copies", "available"]
        rows = [[b.get(k, "") for k in head] for b in db.books.find({"dept": n}).sort("book_id", 1)]
    elif what == "members":
        head = ["member_id", "name", "phone", "email"]
        rows = [[m.get(k, "") for k in head] for m in db.members.find({"dept": n}).sort("member_id", 1)]
    elif what == "transactions":
        head = ["member_id", "book_id", "issue_date", "due_date", "return_date", "fine", "status"]
        rows = [[(t.get(k).strftime("%Y-%m-%d") if hasattr(t.get(k), "strftime") else t.get(k, "")) for k in head]
                for t in db.transactions.find({"dept": n}).sort("issue_date", -1)]
    else:
        abort(404)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(head)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={d}_{what}.csv"})


# ============================================================== TEMPLATES
TEMPLATES = {
    # ------------------------------------------------------------ macros
    "macros.html": r"""
{% macro bars(items, unit='') %}
{% set mx = (items|map(attribute='value')|max) if items else 1 %}
{% for i in items %}<div class="bar"><span class="bl" title="{{ i.label }}">{{ i.label }}</span>
<div class="bt"><div class="bf" style="width:{{ (100*i.value/(mx or 1))|round|int }}%"></div></div>
<span class="bv">{{ i.value }}{{ unit }}</span></div>
{% else %}<p class="muted">No data yet. Load sample data or add records.</p>{% endfor %}
{% endmacro %}

{% macro cols(items) %}
{% set mx = (items|map(attribute='value')|max) or 1 %}
<div class="cols">{% for i in items %}<div class="col"><span class="cv">{{ i.value }}</span>
<div class="cb" style="height:{{ (100*i.value/mx)|round|int + 3 }}px"></div><span class="cl">{{ i.label }}</span></div>{% endfor %}</div>
{% endmacro %}

{% macro badge(text, tone='') %}<span class="badge {{ tone }}">{{ text }}</span>{% endmacro %}

{% macro book_fields(dept, edit=false) %}
<div class="fields">
<label>Book ID<input name="book_id" required {{ 'readonly' if edit }}></label>
<label class="w2">Title<input name="title" required></label>
<label>Author<input name="author" required></label>
<label>Publisher<input name="publisher"></label>
<label>Year<input name="year" type="number" min="1000" max="2100" required></label>
{% for k,lbl in dept.extra %}<label>{{ lbl }}<input name="{{ k }}" {% if k==dept.group %}list="groups"{% endif %}></label>{% endfor %}
<label>Total copies<input name="total_copies" type="number" min="1" required></label>
</div>
{% endmacro %}

{% macro loans_table(rows, now, titles, d, nxt, show_member=true, tid='lt') %}
<table id="{{ tid }}"><thead><tr>
{% if show_member %}<th data-sort>Member</th>{% endif %}<th data-sort>Book</th><th data-sort>Issued</th>
<th data-sort>Due</th><th>Status</th><th></th></tr></thead><tbody>
{% for t in rows %}{% set late = t.due_date < now %}
<tr data-text="{{ (t.member_id ~ ' ' ~ t.book_id ~ ' ' ~ titles.get(t.book_id,''))|lower }}" data-status="{{ 'overdue' if late else 'ontime' }}">
{% if show_member %}<td><a href="{{ url_for('member', d=d, mid=t.member_id) }}">{{ t.member_id }}</a></td>{% endif %}
<td><b>{{ t.book_id }}</b> <span class="muted">{{ titles.get(t.book_id,'') }}</span></td>
<td data-v="{{ t.issue_date.strftime('%Y%m%d%H%M') }}">{{ t.issue_date|dt }}</td>
<td data-v="{{ t.due_date.strftime('%Y%m%d%H%M') }}">{{ t.due_date|dt }}</td>
<td>{% if late %}<span class="badge bad">Overdue {{ (now.date() - t.due_date.date()).days }}d · Rs {{ (now.date() - t.due_date.date()).days * FINE_PER_DAY }}</span>
{% else %}<span class="badge ok">On time</span>{% endif %}
{% if t.get('renewals', 0) %}<span class="badge">renewed ×{{ t.renewals }}</span>{% endif %}</td>
<td class="act">
<form method="post" action="{{ url_for('renew', d=d, tid=t['_id']|string) }}"><input type="hidden" name="next" value="{{ nxt }}">
<button class="btn ghost sm" {{ 'disabled' if late or t.get('renewals', 0) >= MAX_RENEWALS }}>Renew</button></form>
<form method="post" action="{{ url_for('return_book', d=d, tid=t['_id']|string) }}"><input type="hidden" name="next" value="{{ nxt }}">
<button class="btn sm">Return</button></form></td></tr>
{% else %}<tr class="empty"><td colspan="6">No books are currently on loan.</td></tr>{% endfor %}
</tbody></table>
{% endmacro %}
""",
    # ------------------------------------------------------------ base layout
    "base.html": r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ dept.name }} Library · {% block title %}{% endblock %}</title>
<script>try{var t=localStorage.getItem('lib-theme');if(!t)t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
:root{--bg:#f4f5fb;--card:#fff;--ink:#1c2233;--mut:#6b7385;--line:#e4e7f0;--pri:#4f46e5;--pri2:#6366f1;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;--side:#151a2e;--shadow:0 1px 3px rgba(20,25,50,.08),0 6px 18px rgba(20,25,50,.05)}
[data-theme=dark]{--bg:#0f1220;--card:#181d33;--ink:#e8ebf7;--mut:#98a0b8;--line:#272d48;--pri:#8087ff;--side:#0a0d1a;--shadow:none}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink);display:flex;min-height:100vh}
a{color:var(--pri);text-decoration:none}a:hover{text-decoration:underline}
.side{width:236px;flex:none;background:var(--side);color:#c9cfe8;padding:18px 14px;display:flex;flex-direction:column;gap:18px;position:sticky;top:0;height:100vh}
.brand{font-size:19px;color:#fff;display:flex;flex-direction:column;line-height:1.2;padding:0 6px}.brand small{color:#8c94b3;font-size:12px}
.side nav{display:flex;flex-direction:column;gap:4px}
.side nav a{color:inherit;padding:9px 12px;border-radius:9px;display:flex;gap:10px;align-items:center;text-decoration:none}
.side nav a:hover{background:rgba(255,255,255,.07)}.side nav a.on{background:var(--pri2);color:#fff}
.seg{display:flex;background:rgba(255,255,255,.08);border-radius:10px;padding:3px}
.seg a{flex:1;text-align:center;padding:7px 4px;border-radius:8px;color:#c9cfe8;font-size:13px;text-decoration:none}.seg a.on{background:#fff;color:#151a2e;font-weight:600}
.side-foot{margin-top:auto}.side-foot button{width:100%;background:rgba(255,255,255,.08);color:#c9cfe8;border:0;border-radius:9px;padding:9px;cursor:pointer;font:inherit}
.main{flex:1;min-width:0}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:22px 28px 0;flex-wrap:wrap}
.top h1{margin:0;font-size:24px}.top .acts{display:flex;gap:8px;flex-wrap:wrap}.content{padding:18px 28px 48px;max-width:1240px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);margin-bottom:16px;overflow-x:auto}
.card h3{margin:0 0 12px;font-size:15px}.muted{color:var(--mut)}
.grid{display:grid;gap:16px}.stats{grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-bottom:16px}
.two{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}.two .card{margin:0}.two{margin-bottom:16px}
.stat{display:flex;gap:14px;align-items:center;margin:0}.stat .ico{font-size:24px;background:var(--bg);width:48px;height:48px;border-radius:12px;display:grid;place-items:center;flex:none}
.stat b{font-size:28px;display:block;line-height:1.1}.stat span{color:var(--mut)}.stat small{display:block;color:var(--mut);font-size:12px}.stat.bad b{color:var(--bad)}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);white-space:nowrap;user-select:none}
th[data-sort]{cursor:pointer}th[data-sort]:hover{color:var(--pri)}th[data-dir=asc]::after{content:" ▲";font-size:9px}th[data-dir=desc]::after{content:" ▼";font-size:9px}
tbody tr:hover{background:color-mix(in srgb,var(--pri) 6%,transparent)}tr.empty td{text-align:center;color:var(--mut);padding:26px}
.act{white-space:nowrap}.act form{display:inline-block;margin:0 2px}
input,select,textarea{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 10px;width:100%}
input:focus,select:focus{outline:2px solid color-mix(in srgb,var(--pri) 45%,transparent);border-color:var(--pri)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.toolbar input,.toolbar select{width:auto;flex:1;min-width:150px}.toolbar .search{flex:2;min-width:220px}
.btn{font:inherit;background:var(--pri);color:#fff;border:0;border-radius:9px;padding:8px 14px;cursor:pointer;display:inline-block;text-decoration:none;white-space:nowrap}
.btn:hover{filter:brightness(1.08);text-decoration:none}.btn.ghost{background:transparent;color:var(--pri);border:1px solid var(--line)}
.btn.danger{background:var(--bad)}.btn.sm{padding:4px 10px;font-size:13px}.btn[disabled]{opacity:.4;cursor:not-allowed}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;background:var(--bg);color:var(--mut);border:1px solid var(--line)}
.badge.ok{background:#16a34a22;color:var(--ok);border-color:#16a34a44}.badge.warn{background:#d9770622;color:var(--warn);border-color:#d9770644}.badge.bad{background:#dc262622;color:var(--bad);border-color:#dc262644}
.avatar{width:34px;height:34px;border-radius:50%;background:var(--pri2);color:#fff;display:inline-grid;place-items:center;font-weight:600;margin-right:10px;vertical-align:middle}
.bar{display:grid;grid-template-columns:150px 1fr 44px;gap:10px;align-items:center;margin:8px 0}.bl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mut)}
.bt{background:var(--bg);border-radius:99px;height:10px;overflow:hidden}.bf{background:linear-gradient(90deg,var(--pri2),var(--pri));height:100%;border-radius:99px;transition:width .6s}.bv{text-align:right;font-weight:600}
.cols{display:flex;gap:10px;align-items:flex-end;height:170px;padding-top:10px}.col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:4px;height:100%}
.cb{width:100%;max-width:44px;background:linear-gradient(var(--pri2),var(--pri));border-radius:7px 7px 3px 3px;transition:height .6s}.cv{font-weight:600;font-size:13px}.cl{color:var(--mut);font-size:12px}
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.fields .w2{grid-column:span 2}label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--mut)}
.stack{display:flex;flex-direction:column;gap:12px}.rules{margin:0;padding-left:18px;line-height:1.9}
dialog{border:0;border-radius:16px;padding:0;background:var(--card);color:var(--ink);width:min(640px,94vw);box-shadow:0 20px 60px rgba(0,0,0,.35)}
dialog::backdrop{background:rgba(10,13,26,.55);backdrop-filter:blur(2px)}.dlg{padding:20px}.dlg h3{margin:0 0 14px}.dlg-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
#toasts{position:fixed;right:18px;bottom:18px;display:flex;flex-direction:column;gap:8px;z-index:99}
.toast{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--ok);padding:11px 16px;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.2);max-width:360px;cursor:pointer;animation:in .25s}
.toast.err{border-left-color:var(--bad)}@keyframes in{from{transform:translateY(12px);opacity:0}}
@media(max-width:820px){body{flex-direction:column}.side{width:auto;height:auto;position:static;flex-direction:row;flex-wrap:wrap;align-items:center;gap:10px;padding:10px}
.side nav{flex-direction:row;overflow-x:auto;width:100%;order:3}.brand small,.side-foot{display:none}.seg{margin-left:auto}.top,.content{padding-left:14px;padding-right:14px}.bar{grid-template-columns:100px 1fr 40px}}
</style></head><body>
<aside class="side">
 <div class="brand"><b>📖 LibraryOS</b><small>Library Information System</small></div>
 <div class="seg">{% set ep = 'members' if page=='member' else page %}{% for s,lbl in [('engineering','Engineering'),('mba','MBA')] %}<a href="{{ url_for(ep, d=s) }}" class="{{ 'on' if s==d }}">{{ lbl }}</a>{% endfor %}</div>
 <nav>{% for key,label,icon in NAV %}<a href="{{ url_for(key, d=d) }}" class="{{ 'on' if page==key or (key=='members' and page=='member') }}"><span>{{ icon }}</span>{{ label }}</a>{% endfor %}</nav>
 <div class="side-foot"><button id="theme" type="button">🌓 Light / Dark</button></div>
</aside>
<div class="main">
 <header class="top"><h1>{% block title2 %}{{ self.title() }}{% endblock %} <span class="badge">{{ dept.name }}</span></h1><div class="acts">{% block actions %}{% endblock %}</div></header>
 <section class="content">{% block body %}{% endblock %}</section>
</div>
<div id="toasts">{% for cat,msg in get_flashed_messages(with_categories=true) %}<div class="toast {{ cat }}">{{ msg }}</div>{% endfor %}</div>
<script>
(function(){
 var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
 /* theme */
 $('#theme').onclick=function(){var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{localStorage.setItem('lib-theme',t)}catch(e){}};
 /* toasts */
 $$('.toast').forEach(function(t,i){t.onclick=function(){t.remove()};setTimeout(function(){t.remove()},4500+i*700)});
 /* animated counters */
 $$('[data-count]').forEach(function(el){var n=+el.dataset.count;if(!n)return;var i=0,step=Math.max(1,Math.ceil(n/20));el.textContent=0;
  var h=setInterval(function(){i=Math.min(n,i+step);el.textContent=i;if(i>=n)clearInterval(h)},30)});
 /* live filter: inputs/selects carry data-table; selects also data-attr */
 function apply(id){var tb=document.getElementById(id);if(!tb)return;var q='',sels=[];
  $$('[data-table="'+id+'"]').forEach(function(c){if(c.tagName==='SELECT')sels.push(c);else q=c.value.toLowerCase()});
  var shown=0;$$('tbody tr[data-text]',tb).forEach(function(tr){var okk=tr.dataset.text.indexOf(q)>-1;
   sels.forEach(function(s){if(s.value&&tr.dataset[s.dataset.attr]!==s.value)okk=false});tr.hidden=!okk;if(okk)shown++});
  var c=document.getElementById(id+'-count');if(c)c.textContent=shown}
 $$('[data-table]').forEach(function(c){c.addEventListener('input',function(){apply(c.dataset.table)})});
 /* click-to-sort */
 $$('th[data-sort]').forEach(function(th){th.addEventListener('click',function(){var tb=th.closest('table'),body=tb.tBodies[0],i=th.cellIndex,dir=th.dataset.dir==='asc'?-1:1;
  $$('th',tb).forEach(function(x){x.removeAttribute('data-dir')});th.dataset.dir=dir===1?'asc':'desc';
  var rows=$$('tr[data-text]',body);rows.sort(function(a,b){var x=(a.cells[i].dataset.v||a.cells[i].textContent).trim(),y=(b.cells[i].dataset.v||b.cells[i].textContent).trim(),nx=parseFloat(x),ny=parseFloat(y);
   return ((!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y))*dir});rows.forEach(function(r){body.appendChild(r)})})});
 /* dialogs (+ prefill for edit) */
 document.addEventListener('click',function(e){var o=e.target.closest('[data-open]');
  if(o){var dlg=document.getElementById(o.dataset.open),f=$('form',dlg);
   if(o.dataset.edit){var obj=JSON.parse(o.dataset.edit);for(var k in obj){if(f.elements[k])f.elements[k].value=obj[k]}
    if(f.dataset.base)f.action=f.dataset.base.replace('__ID__',encodeURIComponent(obj[f.dataset.idkey]))}
   else if(f.dataset.reset!==undefined)f.reset();
   dlg.showModal();return}
  if(e.target.closest('[data-close]'))e.target.closest('dialog').close();
  else if(e.target.tagName==='DIALOG')e.target.close()});
 /* shortcut: press / to search */
 document.addEventListener('keydown',function(e){var s=$('.search');if(e.key==='/'&&s&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();s.focus()}});
})();
</script></body></html>""",
    # ------------------------------------------------------------ dashboard
    "dashboard.html": r"""{% extends "base.html" %}{% from "macros.html" import bars, cols, badge with context %}
{% block title %}Dashboard{% endblock %}
{% block actions %}<form method="post" action="{{ url_for('sample', d=d) }}"><button class="btn ghost">⬇ Load sample data</button></form>
<a class="btn" href="{{ url_for('circulation', d=d) }}">🔁 Issue / Return</a>{% endblock %}
{% block body %}
<div class="grid stats">{% for s in stats %}<div class="card stat {{ s.tone }}"><div class="ico">{{ s.icon }}</div>
<div><b data-count="{{ s.value }}">{{ s.value }}</b><span>{{ s.label }}</span><small>{{ s.sub }}</small></div></div>{% endfor %}</div>
<div class="grid two">
 <div class="card"><h3>Copies by {{ dept.group_label|lower }}</h3>{{ bars(by_cat) }}</div>
 <div class="card"><h3>Books issued · last 7 days</h3>{{ cols(week) }}</div>
</div>
<div class="grid two">
 <div class="card"><h3>⏰ Overdue now</h3><table><tbody>
 {% for t in overdue %}<tr><td><a href="{{ url_for('member', d=d, mid=t.member_id) }}">{{ t.member_id }}</a></td><td>{{ t.book_id }} <span class="muted">{{ titles.get(t.book_id,'') }}</span></td>
 <td><span class="badge bad">{{ (now.date() - t.due_date.date()).days }}d late</span></td></tr>
 {% else %}<tr class="empty"><td>Nothing overdue 🎉</td></tr>{% endfor %}</tbody></table></div>
 <div class="card"><h3>Recent activity</h3><table><tbody>
 {% for t in recent %}<tr><td>{{ badge('Issued','warn') if t.status=='Issued' else badge('Returned','ok') }}</td>
 <td><a href="{{ url_for('member', d=d, mid=t.member_id) }}">{{ t.member_id }}</a> · {{ t.book_id }}</td><td class="muted">{{ t.issue_date|dt }}</td></tr>
 {% else %}<tr class="empty"><td>No activity yet.</td></tr>{% endfor %}</tbody></table></div>
</div>
{% endblock %}""",
    # ------------------------------------------------------------ books
    "books.html": r"""{% extends "base.html" %}{% from "macros.html" import book_fields, badge with context %}
{% block title %}Books{% endblock %}
{% block actions %}<a class="btn ghost" href="{{ url_for('export', d=d, what='books') }}">⬇ Export CSV</a>
<button class="btn" data-open="addBook">＋ Add book</button>{% endblock %}
{% block body %}
<div class="card">
<div class="toolbar">
 <input class="search" type="search" placeholder="Search title, author, ID…  (press /)" data-table="bt">
 <select data-table="bt" data-attr="cat"><option value="">All {{ dept.group_label|lower }}s</option>{% for c in cats %}<option>{{ c }}</option>{% endfor %}</select>
 <select data-table="bt" data-attr="avail"><option value="">Any availability</option><option value="yes">Available</option><option value="no">All copies out</option></select>
 <span class="muted"><b id="bt-count">{{ rows|length }}</b> / {{ rows|length }} titles</span>
</div>
<table id="bt"><thead><tr><th data-sort>ID</th><th data-sort>Title</th><th data-sort>Author</th><th data-sort>Year</th>
{% for k,lbl in dept.extra %}<th data-sort>{{ lbl }}</th>{% endfor %}<th data-sort>Copies</th><th></th></tr></thead><tbody>
{% for b in rows %}
<tr data-text="{{ (b.book_id ~ ' ' ~ b.title ~ ' ' ~ b.author ~ ' ' ~ b.get(dept.group,''))|lower }}" data-cat="{{ b.get(dept.group,'') }}" data-avail="{{ 'yes' if b.available>0 else 'no' }}">
<td><b>{{ b.book_id }}</b></td><td>{{ b.title }}</td><td>{{ b.author }}</td><td>{{ b.year }}</td>
{% for k,lbl in dept.extra %}<td>{{ b.get(k,'') }}</td>{% endfor %}
<td>{{ badge(b.available ~ ' / ' ~ b.total_copies, 'bad' if b.available==0 else ('warn' if b.available==1 else 'ok')) }}</td>
<td class="act"><button class="btn ghost sm" data-open="editBook" data-edit='{{ b.js|tojson }}'>Edit</button>
<form method="post" action="{{ url_for('book_delete', d=d, bid=b.book_id) }}" onsubmit="return confirm('Delete this book?')"><button class="btn danger sm">Delete</button></form></td></tr>
{% else %}<tr class="empty"><td colspan="9">No books yet. Add one, or load sample data from the dashboard.</td></tr>{% endfor %}
</tbody></table></div>
<datalist id="groups">{% for c in dept.choices %}<option value="{{ c }}">{% endfor %}</datalist>
<dialog id="addBook"><div class="dlg"><h3>Add a book</h3><form method="post" action="{{ url_for('book_add', d=d) }}" data-reset>
{{ book_fields(dept) }}<div class="dlg-foot"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn">Save book</button></div></form></div></dialog>
<dialog id="editBook"><div class="dlg"><h3>Edit book</h3><form method="post" data-base="{{ url_for('book_edit', d=d, bid='__ID__') }}" data-idkey="book_id">
{{ book_fields(dept, true) }}<div class="dlg-foot"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn">Save changes</button></div></form></div></dialog>
{% endblock %}""",
    # ------------------------------------------------------------ members
    "members.html": r"""{% extends "base.html" %}
{% block title %}Members{% endblock %}
{% block actions %}<a class="btn ghost" href="{{ url_for('export', d=d, what='members') }}">⬇ Export CSV</a>
<button class="btn" data-open="addMember">＋ Add member</button>{% endblock %}
{% block body %}
<div class="card"><div class="toolbar"><input class="search" type="search" placeholder="Search name, ID, email…  (press /)" data-table="mt">
<span class="muted"><b id="mt-count">{{ rows|length }}</b> / {{ rows|length }} members</span></div>
<table id="mt"><thead><tr><th data-sort>Member</th><th data-sort>ID</th><th>Phone</th><th>Email</th><th data-sort>On loan</th><th></th></tr></thead><tbody>
{% for m in rows %}<tr data-text="{{ (m.member_id ~ ' ' ~ m.name ~ ' ' ~ m.email ~ ' ' ~ m.phone)|lower }}">
<td><span class="avatar">{{ m.name[:1]|upper }}</span><a href="{{ url_for('member', d=d, mid=m.member_id) }}">{{ m.name }}</a></td>
<td>{{ m.member_id }}</td><td>{{ m.phone }}</td><td>{{ m.email }}</td>
<td><span class="badge {{ 'warn' if m.loans else '' }}">{{ m.loans }} / {{ MAX_BOOKS }}</span></td>
<td class="act"><a class="btn ghost sm" href="{{ url_for('circulation', d=d, member=m.member_id) }}">Issue</a>
<button class="btn ghost sm" data-open="editMember" data-edit='{{ m.js|tojson }}'>Edit</button>
<form method="post" action="{{ url_for('member_delete', d=d, mid=m.member_id) }}" onsubmit="return confirm('Delete this member?')"><button class="btn danger sm">Delete</button></form></td></tr>
{% else %}<tr class="empty"><td colspan="6">No members yet.</td></tr>{% endfor %}</tbody></table></div>
<dialog id="addMember"><div class="dlg"><h3>Register a member</h3><form method="post" action="{{ url_for('member_add', d=d) }}" data-reset>
<div class="fields"><label>Member ID<input name="member_id" required></label><label>Full name<input name="name" required></label>
<label>Phone<input name="phone"></label><label>Email<input name="email" type="email"></label></div>
<div class="dlg-foot"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn">Register</button></div></form></div></dialog>
<dialog id="editMember"><div class="dlg"><h3>Edit member</h3><form method="post" data-base="{{ url_for('member_edit', d=d, mid='__ID__') }}" data-idkey="member_id">
<div class="fields"><label>Member ID<input name="member_id" readonly></label><label>Full name<input name="name" required></label>
<label>Phone<input name="phone"></label><label>Email<input name="email" type="email"></label></div>
<div class="dlg-foot"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn">Save changes</button></div></form></div></dialog>
{% endblock %}""",
    # ------------------------------------------------------------ member profile
    "member.html": r"""{% extends "base.html" %}{% from "macros.html" import loans_table, badge with context %}
{% block title %}{{ m.name }}{% endblock %}
{% block actions %}<a class="btn ghost" href="{{ url_for('members', d=d) }}">← All members</a>
<a class="btn" href="{{ url_for('circulation', d=d, member=m.member_id) }}">Issue a book</a>{% endblock %}
{% block body %}
<div class="card"><span class="avatar" style="width:52px;height:52px;font-size:20px">{{ m.name[:1]|upper }}</span>
<b style="font-size:18px">{{ m.name }}</b> <span class="muted">· {{ m.member_id }} · {{ m.phone }} · {{ m.email }} · joined {{ m.joined_on|dt }}</span></div>
<div class="grid stats">
 <div class="card stat"><div class="ico">📖</div><div><b>{{ active|length }}</b><span>On loan</span><small>limit {{ MAX_BOOKS }}</small></div></div>
 <div class="card stat"><div class="ico">🧾</div><div><b>{{ total }}</b><span>Total borrowed</span></div></div>
 <div class="card stat"><div class="ico">💰</div><div><b>Rs {{ paid }}</b><span>Fines paid</span></div></div>
 <div class="card stat {{ 'bad' if accruing }}"><div class="ico">⏳</div><div><b>Rs {{ accruing }}</b><span>Fines accruing</span></div></div>
</div>
<div class="card"><h3>Currently on loan</h3>{{ loans_table(active, now, titles, d, request.path, false, 'lt') }}</div>
<div class="card"><h3>Borrowing history</h3><table><thead><tr><th>Book</th><th>Issued</th><th>Returned</th><th>Fine</th></tr></thead><tbody>
{% for t in past %}<tr><td><b>{{ t.book_id }}</b> <span class="muted">{{ titles.get(t.book_id,'') }}</span></td><td>{{ t.issue_date|dt }}</td><td>{{ t.return_date|dt }}</td>
<td>{{ badge('Rs ' ~ t.fine, 'bad' if t.fine else 'ok') }}</td></tr>{% else %}<tr class="empty"><td colspan="4">No past loans.</td></tr>{% endfor %}</tbody></table></div>
{% endblock %}""",
    # ------------------------------------------------------------ circulation
    "circulation.html": r"""{% extends "base.html" %}{% from "macros.html" import loans_table with context %}
{% block title %}Issue / Return{% endblock %}
{% block body %}
<div class="grid two">
 <div class="card"><h3>📤 Issue a book</h3><form method="post" action="{{ url_for('issue', d=d) }}" class="stack">
  <label>Member<input name="member_id" list="mlist" value="{{ pre }}" placeholder="Start typing an ID…" autocomplete="off" required></label>
  <label>Book (only available copies are listed)<input name="book_id" list="blist" placeholder="Start typing an ID…" autocomplete="off" required></label>
  <button class="btn">Issue book</button></form>
  <datalist id="mlist">{% for m in members_list %}<option value="{{ m.member_id }}">{{ m.name }}</option>{% endfor %}</datalist>
  <datalist id="blist">{% for b in books_list %}<option value="{{ b.book_id }}">{{ b.title }} ({{ b.available }} left)</option>{% endfor %}</datalist></div>
 <div class="card"><h3>📏 Loan rules</h3><ul class="rules"><li>Loan period: <b>{{ LOAN_DAYS }} days</b></li><li>Max books per member: <b>{{ MAX_BOOKS }}</b></li>
  <li>Renewals: up to <b>{{ MAX_RENEWALS }}</b> (+{{ LOAN_DAYS }} days each, not when overdue)</li><li>Late fine: <b>Rs {{ FINE_PER_DAY }} / day</b></li></ul></div>
</div>
<div class="card"><h3>Books currently on loan</h3>
<div class="toolbar"><input class="search" type="search" placeholder="Search member, book…  (press /)" data-table="lt">
<select data-table="lt" data-attr="status"><option value="">All loans</option><option value="overdue">Overdue only</option><option value="ontime">On time only</option></select>
<span class="muted"><b id="lt-count">{{ rows|length }}</b> / {{ rows|length }}</span></div>
{{ loans_table(rows, now, titles, d, request.path) }}</div>
{% endblock %}""",
    # ------------------------------------------------------------ history
    "history.html": r"""{% extends "base.html" %}{% from "macros.html" import badge with context %}
{% block title %}History{% endblock %}
{% block actions %}<a class="btn ghost" href="{{ url_for('export', d=d, what='transactions') }}">⬇ Export CSV</a>{% endblock %}
{% block body %}
<div class="card"><div class="toolbar"><input class="search" type="search" placeholder="Search member or book…  (press /)" data-table="ht">
<select data-table="ht" data-attr="status"><option value="">All records</option><option value="issued">Issued</option><option value="returned">Returned</option></select>
<span class="muted"><b id="ht-count">{{ rows|length }}</b> / {{ rows|length }} records</span></div>
<table id="ht"><thead><tr><th data-sort>Member</th><th data-sort>Book</th><th data-sort>Issued</th><th data-sort>Due</th><th data-sort>Returned</th><th data-sort>Fine</th><th>Status</th></tr></thead><tbody>
{% for t in rows %}<tr data-text="{{ (t.member_id ~ ' ' ~ t.book_id ~ ' ' ~ titles.get(t.book_id,''))|lower }}" data-status="{{ t.status|lower }}">
<td><a href="{{ url_for('member', d=d, mid=t.member_id) }}">{{ t.member_id }}</a></td><td><b>{{ t.book_id }}</b> <span class="muted">{{ titles.get(t.book_id,'') }}</span></td>
<td data-v="{{ t.issue_date.strftime('%Y%m%d%H%M') }}">{{ t.issue_date|dt }}</td><td data-v="{{ t.due_date.strftime('%Y%m%d%H%M') }}">{{ t.due_date|dt }}</td>
<td data-v="{{ t.return_date.strftime('%Y%m%d%H%M') if t.return_date else '0' }}">{{ t.return_date|dt }}</td><td>{{ t.fine }}</td>
<td>{% if t.status=='Returned' %}{{ badge('Returned','ok') }}{% elif t.due_date < now %}{{ badge('Overdue','bad') }}{% else %}{{ badge('Issued','warn') }}{% endif %}</td></tr>
{% else %}<tr class="empty"><td colspan="7">No transactions yet.</td></tr>{% endfor %}</tbody></table></div>
{% endblock %}""",
    # ------------------------------------------------------------ reports
    "reports.html": r"""{% extends "base.html" %}{% from "macros.html" import bars with context %}
{% block title %}Reports{% endblock %}
{% block actions %}<a class="btn ghost" href="{{ url_for('export', d=d, what='books') }}">⬇ Books CSV</a>
<a class="btn ghost" href="{{ url_for('export', d=d, what='members') }}">⬇ Members CSV</a>
<a class="btn ghost" href="{{ url_for('export', d=d, what='transactions') }}">⬇ Transactions CSV</a>{% endblock %}
{% block body %}
<div class="grid stats">
 <div class="card stat"><div class="ico">💰</div><div><b>Rs {{ collected }}</b><span>Fines collected</span></div></div>
 <div class="card stat {{ 'bad' if accruing }}"><div class="ico">⏳</div><div><b>Rs {{ accruing }}</b><span>Fines accruing</span><small>on {{ overdue|length }} overdue loan(s)</small></div></div>
</div>
<div class="grid two">
 <div class="card"><h3>Copies by {{ dept.group_label|lower }}</h3>{{ bars(by_cat) }}</div>
 <div class="card"><h3>Most issued books</h3>{{ bars(top, '×') }}</div>
</div>
<div class="grid two">
 <div class="card"><h3>Top borrowers</h3>{{ bars(borrowers, '×') }}</div>
 <div class="card"><h3>⏰ Overdue books</h3><table><thead><tr><th>Member</th><th>Book</th><th>Late</th><th>Fine</th></tr></thead><tbody>
 {% for t in overdue %}<tr><td><a href="{{ url_for('member', d=d, mid=t.member_id) }}">{{ t.member_id }}</a></td><td>{{ t.book_id }} <span class="muted">{{ titles.get(t.book_id,'') }}</span></td>
 <td>{{ (now.date() - t.due_date.date()).days }} d</td><td>Rs {{ (now.date() - t.due_date.date()).days * FINE_PER_DAY }}</td></tr>
 {% else %}<tr class="empty"><td colspan="4">Nothing overdue 🎉</td></tr>{% endfor %}</tbody></table></div>
</div>
{% endblock %}""",
}

app.jinja_env.loader = DictLoader(TEMPLATES)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
