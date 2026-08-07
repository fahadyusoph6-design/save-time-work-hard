"""Heuristics that autofill job title, company and jobsite from a JD and its URL.

Everything here is a best guess; the user can always edit the fields.
"""
import re
from urllib.parse import urlparse

KNOWN_SITES = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "glassdoor": "Glassdoor",
    "ziprecruiter": "ZipRecruiter",
    "dice": "Dice",
    "monster": "Monster",
    "upwork": "Upwork",
    "wellfound": "Wellfound",
    "angel": "Wellfound",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "myworkdayjobs": "Workday",
    "workday": "Workday",
    "ashbyhq": "Ashby",
    "smartrecruiters": "SmartRecruiters",
    "builtin": "Built In",
    "remoteok": "Remote OK",
    "weworkremotely": "We Work Remotely",
    "otta": "Otta",
    "welcometothejungle": "Welcome to the Jungle",
    "hired": "Hired",
    "simplyhired": "SimplyHired",
    "careerbuilder": "CareerBuilder",
    "jobvite": "Jobvite",
    "icims": "iCIMS",
    "bamboohr": "BambooHR",
    "workable": "Workable",
    "recruitee": "Recruitee",
    "remote": "Remote.co",
    "flexjobs": "FlexJobs",
    "toptal": "Toptal",
}

# ATS hosts where the company slug is the first path segment or the subdomain.
PATH_COMPANY_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com")
SUBDOMAIN_COMPANY_HOSTS = ("myworkdayjobs.com", "bamboohr.com", "recruitee.com", "jobvite.com", "icims.com")

TITLE_LABEL = re.compile(r"^(?:job\s*title|title|position|role|job)\s*[:\-–—]\s*(.{2,100})$", re.I)
COMPANY_LABEL = re.compile(r"^(?:company(?:\s*name)?|employer|organi[sz]ation|client)\s*[:\-–—]\s*(.{2,80})$", re.I)
ABOUT_COMPANY = re.compile(
    r"^about\s+(?!the\b|this\b|us\b|you\b|our\b|the\s+role|the\s+job|the\s+team)(.{2,60}?)\s*[:.!]?$", re.I
)
HIRING = re.compile(r"\b([A-Z][\w&.\-']*(?:\s+[A-Z][\w&.\-']*){0,3})\s+is\s+(?:hiring|looking|seeking|searching)\b")
JOIN_AT = re.compile(r"\b(?:join|at)\s+([A-Z][\w&.\-']*(?:\s+[A-Z][\w&.\-']*){0,3})(?=[,.!]|\s+(?:as|we|is|and|team|to)\b)")
LOOKING_FOR = re.compile(
    r"\b(?i:we(?:'re|\s+are)\s+(?:looking\s+for|hiring|seeking)|seeking|hiring)\s+(?i:an?\s+|our\s+(?:next|first)\s+)?"
    r"((?:[A-Z][\w+#./\-]*\s*){1,7})",
)
TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|designer|analyst|scientist|architect|lead|director|consultant|specialist|"
    r"administrator|coordinator|intern|officer|head|vp|programmer|devops|sre|tester|qa|writer|recruiter|"
    r"associate|representative|technician|strategist|owner|marketer|accountant)\b",
    re.I,
)
STOP_COMPANIES = {"we", "our", "the", "this", "you", "us", "remote", "home", "a", "an"}


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t-–—|:,.")
    return value[:120]


def jobsite_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return ""
    if not host:
        return ""
    labels = host.split(".")
    for key, name in KNOWN_SITES.items():
        if key in labels:
            return name
    parts = [p for p in host.split(".") if p not in ("www", "jobs", "careers", "boards", "apply")]
    if len(parts) >= 2:
        return parts[-2].capitalize()
    return parts[0].capitalize() if parts else ""


def company_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]
    slug = ""
    if any(host.endswith(h) for h in PATH_COMPANY_HOSTS) and segments:
        slug = segments[0]
    elif any(host.endswith(h) for h in SUBDOMAIN_COMPANY_HOSTS):
        slug = host.split(".")[0]
    if not slug or slug in ("jobs", "embed", "careers", "o", "j"):
        return ""
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w)


def parse_jd(jd_text: str, job_url: str = "") -> dict:
    lines = [ln.strip() for ln in (jd_text or "").splitlines() if ln.strip()]
    title = ""
    company = ""

    for ln in lines[:40]:
        if not title and (m := TITLE_LABEL.match(ln)):
            title = _clean(m.group(1))
        if not company and (m := COMPANY_LABEL.match(ln)):
            company = _clean(m.group(1))

    if not company:
        for ln in lines:
            m = ABOUT_COMPANY.match(ln)
            if m and len(m.group(1).split()) <= 5:
                company = _clean(m.group(1))
                break

    text = "\n".join(lines)
    if not company and (m := HIRING.search(text)) and m.group(1).lower() not in STOP_COMPANIES:
        company = _clean(m.group(1))
    if not company:
        for m in JOIN_AT.finditer(text):
            cand = _clean(m.group(1))
            if cand.lower() not in STOP_COMPANIES and not TITLE_WORDS.search(cand):
                company = cand
                break
    if not company:
        company = company_from_url(job_url)

    if not title:
        # First short line that reads like a job title.
        for ln in lines[:8]:
            if (len(ln) <= 80 and len(ln.split()) <= 9 and TITLE_WORDS.search(ln) and not ln.endswith(".")
                    and not re.match(r"(?i)(about|we|our|you|join|at)\b", ln)):
                title = _clean(re.split(r"\s+[|@–—-]\s+|\s+at\s+", ln)[0])
                break
    if not title and (m := LOOKING_FOR.search(text)):
        cand = _clean(m.group(1))
        if TITLE_WORDS.search(cand):
            title = cand
    if not title and lines and len(lines[0]) <= 60 and not lines[0].endswith((".", "!")):
        title = _clean(lines[0])

    return {
        "job_title": title,
        "company_name": company,
        "jobsite_name": jobsite_from_url(job_url),
    }
