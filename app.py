"""Job application tracker (Firebase Firestore).
Paste a job link -> extracts title + company -> logs it to Firestore with today's date
and status "Applied". The table is shown below and the Status column is a dropdown.
"""
import hmac
import json
import datetime as dt
from urllib.parse import urlparse

import requests
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from bs4 import BeautifulSoup

STATUSES = ["🟡 Applied", "🟢 Interview", "🔴 Rejected", "🟢 Offer"]
# map plain names (older rows) to the emoji versions
PLAIN_TO_EMOJI = {x.split(" ", 1)[1]: x for x in STATUSES}
COLLECTION = "job_applications"
COLS = ["job_title", "company", "date_applied", "status", "url"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

st.set_page_config(page_title="Job Tracker", page_icon="📋", layout="wide")


# ---------- login ----------
def check_login():
    if st.session_state.get("authed"):
        return
    st.title("🔒 Job Tracker")
    with st.form("login"):
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        ok = st.form_submit_button("Log in")
    if ok:
        good_user = hmac.compare_digest(user, st.secrets["login"]["username"])
        good_pwd = hmac.compare_digest(pwd, st.secrets["login"]["password"])
        if good_user and good_pwd:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong username or password.")
    st.stop()


check_login()


@st.cache_resource
def db():
    if not firebase_admin._apps:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ---------- extraction ----------
def _find_jobposting(node):
    """Search JSON-LD (nested / @graph / lists) for a JobPosting object."""
    if isinstance(node, list):
        for n in node:
            r = _find_jobposting(n)
            if r:
                return r
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return node
        for v in node.values():
            r = _find_jobposting(v)
            if r:
                return r
    return None


def _split_title(text):
    """Handle strings like 'Data Analyst at Acme | LinkedIn' or 'Data Analyst - Acme'."""
    text = text.split("|")[0].strip()
    for sep in (" at ", " - ", " – ", " — ", " @ "):
        if sep in text:
            a, b = text.split(sep, 1)
            return a.strip(), b.strip()
    return text, ""


def extract(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = company = ""

    # 1) Structured data (most reliable: Greenhouse, Lever, Workday, many boards)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            job = _find_jobposting(json.loads(tag.string or ""))
        except Exception:
            continue
        if job:
            title = job.get("title", "") or ""
            org = job.get("hiringOrganization")
            company = org.get("name", "") if isinstance(org, dict) else (org or "")
            break

    # 2) Open Graph / <title> fallback
    if not title:
        og = soup.find("meta", property="og:title")
        raw = og["content"] if og and og.get("content") else (soup.title.string if soup.title else "")
        title, company_guess = _split_title(raw or "")
        company = company or company_guess
    if not company:
        site = soup.find("meta", property="og:site_name")
        company = site["content"] if site and site.get("content") else urlparse(url).netloc.replace("www.", "")

    return title.strip(), company.strip()


# ---------- database ----------
def add_job(title, company, url):
    db().collection(COLLECTION).add({
        "job_title": title,
        "company": company,
        "date_applied": dt.date.today().isoformat(),
        "status": STATUSES[0],
        "url": url,
        "created_at": firestore.SERVER_TIMESTAMP,
    })


def load_jobs():
    docs = db().collection(COLLECTION).order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    rows = []
    for d in docs:
        row = d.to_dict()
        row.pop("created_at", None)
        row["id"] = d.id
        row["status"] = PLAIN_TO_EMOJI.get(row.get("status"), row.get("status"))
        rows.append(row)
    return rows


def save_edits():
    """Called when the table is edited (status dropdown, title, company)."""
    edits = st.session_state["tbl"].get("edited_rows", {})
    rows = st.session_state["rows"]
    for idx, changes in edits.items():
        db().collection(COLLECTION).document(rows[int(idx)]["id"]).update(changes)


# ---------- UI ----------
st.title("📋 Job Application Tracker")
if st.button("Log out"):
    st.session_state["authed"] = False
    st.rerun()

with st.form("add", clear_on_submit=True):
    url = st.text_input("Paste a job link", placeholder="https://...")
    submitted = st.form_submit_button("Log application")

if submitted and url.strip():
    url = url.strip()
    try:
        title, company = extract(url)
        if not title:
            raise ValueError("Couldn't find a job title on that page.")
        add_job(title, company, url)
        st.success(f"Logged: **{title}** @ **{company}**")
    except Exception as e:
        st.warning(f"Couldn't auto-extract ({e}). Added a blank row — edit it below.")
        add_job("(edit me)", urlparse(url).netloc.replace("www.", ""), url)

rows = load_jobs()
st.session_state["rows"] = rows

st.subheader(f"Applications ({len(rows)})")
if rows:
    st.data_editor(
        rows,
        key="tbl",
        on_change=save_edits,
        hide_index=True,
        width="stretch",
        column_order=COLS,
        disabled=["date_applied", "url"],
        column_config={
            "job_title": "Job title",
            "company": "Company",
            "date_applied": "Date",
            "status": st.column_config.SelectboxColumn("Status", options=STATUSES, required=True),
            "url": st.column_config.LinkColumn("Link", display_text="open"),
        },
    )
else:
    st.info("No applications yet — paste a link above.")