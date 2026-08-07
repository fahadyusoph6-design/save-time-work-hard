"""Rebuild pasted resume content with the formatting of a default resume (.docx).

How it works:
1. The default resume is analysed paragraph by paragraph and each paragraph is
   classified into a role (name, contact, tagline, heading, subheading, bullet,
   body). The first paragraph of each role becomes that role's *prototype*.
2. The pasted resume (HTML from the clipboard, or plain text) is parsed into
   blocks and classified into the same roles.
3. The default resume's body is emptied (page setup, headers/footers, styles and
   numbering are kept) and every input block is re-created by cloning the
   prototype paragraph of its role and filling it with the new text.
"""
import copy
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

BULLET_RE = re.compile(r"^\s*(?:[•·▪▫●○◦■□►▶➢➤✓✔*]|[-–—o](?=\s))[\s ]*")
CONTACT_RE = re.compile(r"@|\+?\d[\d\s().\-]{7,}\d|linkedin|github|https?://|www\.|\|", re.I)
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RANGE_RE = re.compile(
    rf"(?:{MONTH}\s*'?\d{{2,4}}|\b\d{{1,2}}/\d{{2,4}}|\b(?:19|20)\d{{2}})\s*(?:-|–|—|to)\s*"
    rf"(?:present|current|now|today|{MONTH}\s*'?\d{{2,4}}|\d{{1,2}}/\d{{2,4}}|(?:19|20)\d{{2}})",
    re.I,
)
SECTION_WORDS = {
    "summary", "profile", "objective", "experience", "employment", "history", "education", "skills",
    "competencies", "projects", "certifications", "certificates", "awards", "publications", "languages",
    "interests", "volunteer", "volunteering", "achievements", "accomplishments", "references", "training",
    "courses", "activities", "leadership", "technologies", "highlights", "qualifications", "expertise",
    "about", "honors", "patents", "affiliations", "memberships", "research", "strengths", "tools",
    "stack", "contact", "career", "overview",
}
HEADING_HINTS = {"h1", "h2", "h3", "h4", "h5", "h6"}
ROLE_FALLBACKS = {
    "name": ["heading", "tagline", "body"],
    "contact": ["tagline", "body"],
    "tagline": ["contact", "body"],
    "heading": ["subheading", "body"],
    "subheading": ["body"],
    "bullet": ["body"],
    "body": ["bullet", "subheading", "contact"],
}


class ResumeBuildError(ValueError):
    pass


# --------------------------------------------------------------------------- input model


@dataclass
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class Block:
    hint: str  # p | li | h1..h6
    runs: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def bold_ratio(self) -> float:
        total = sum(len(r.text.strip()) for r in self.runs)
        if not total:
            return 0.0
        return sum(len(r.text.strip()) for r in self.runs if r.bold) / total


def _normalise_block(block: Block) -> Block | None:
    runs = []
    for r in block.runs:
        # Runs of 3+ spaces are how people align dates by hand; treat them as a tab.
        text = re.sub(r"[  ]{3,}", "\t", r.text)
        text = re.sub(r"[  ]*\t[ \t ]*", "\t", text.replace(" ", " "))
        if runs and runs[-1].text.endswith((" ", "\t")):
            text = text.lstrip(" ")
        if not text:
            continue
        if runs and (runs[-1].bold, runs[-1].italic, runs[-1].underline) == (r.bold, r.italic, r.underline):
            runs[-1].text += text
        else:
            runs.append(TextRun(text, r.bold, r.italic, r.underline))
    # Trim the block.
    while runs and not runs[0].text.strip():
        runs.pop(0)
    while runs and not runs[-1].text.strip():
        runs.pop()
    if not runs:
        return None
    runs[0].text = runs[0].text.lstrip()
    runs[-1].text = runs[-1].text.rstrip()
    block.runs = runs

    if block.hint not in HEADING_HINTS and (m := BULLET_RE.match(block.text)) and len(block.text) > m.end():
        block.hint = "li"
        cut = m.end()
        while cut and block.runs:
            first = block.runs[0]
            if len(first.text) <= cut:
                cut -= len(first.text)
                block.runs.pop(0)
            else:
                first.text = first.text[cut:]
                cut = 0
    return block if block.text.strip() else None


class _ClipboardHTMLParser(HTMLParser):
    """Turns clipboard HTML (Word, Google Docs, browsers) into Blocks."""

    BLOCK_TAGS = {"p", "div", "li", "tr", "blockquote", "pre", "section", "article", "header", "footer",
                  "ul", "ol", "table", "dt", "dd"} | HEADING_HINTS
    VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "col", "wbr", "area", "base", "source"}
    SKIP_TAGS = {"style", "script", "head", "title", "xml", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.current: Block | None = None
        self.stack = [{"tag": "", "bold": False, "italic": False, "underline": False, "ignore": False,
                       "tab": False, "pre": False}]

    # -- block handling
    def _flush(self):
        if self.current is not None and (b := _normalise_block(self.current)):
            self.blocks.append(b)
        self.current = None

    def _start_block(self, hint: str):
        if self.current is not None and not self.current.text.strip():
            # Nested empty wrappers (<li><p>…) keep the more specific hint.
            if not (self.current.hint in HEADING_HINTS | {"li"} and hint == "p"):
                self.current.hint = hint
            return
        self._flush()
        self.current = Block(hint)

    def _ensure_block(self) -> Block:
        if self.current is None:
            self.current = Block("p")
        return self.current

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = (attrs.get("style") or "").lower().replace(" ", "")
        cls = (attrs.get("class") or "").lower()

        if tag == "br":
            hint = self.current.hint if self.current else "p"
            self._flush()
            self.current = Block(hint)
            return
        if tag in ("td", "th") and self.current is not None and self.current.text.strip():
            self.current.runs.append(TextRun("\t"))

        if tag in self.BLOCK_TAGS and tag not in ("ul", "ol", "table"):
            if tag in HEADING_HINTS:
                hint = tag
            elif tag == "li" or "msolistparagraph" in cls or "mso-list:l" in style:
                hint = "li"
            else:
                hint = "p"
            self._start_block(hint)
        elif tag in ("ul", "ol", "table"):
            self._flush()

        if tag in self.VOID_TAGS:
            return

        parent = self.stack[-1]
        state = dict(parent, tag=tag, tab=False)
        if tag in ("b", "strong"):
            state["bold"] = True
        if tag in ("i", "em"):
            state["italic"] = True
        if tag == "u":
            state["underline"] = True
        if tag == "pre":
            state["pre"] = True
        if m := re.search(r"font-weight:([a-z0-9]+)", style):
            state["bold"] = m.group(1) in ("bold", "bolder", "600", "700", "800", "900")
        if m := re.search(r"font-style:([a-z]+)", style):
            state["italic"] = m.group(1) in ("italic", "oblique")
        if m := re.search(r"text-decoration(?:-line)?:([a-z\-]+)", style):
            state["underline"] = "underline" in m.group(1)
        if tag in self.SKIP_TAGS or "display:none" in style:
            state["ignore"] = True
        if "mso-list:ignore" in style:
            state["ignore"] = True
            self._ensure_block().hint = "li"
        if "mso-tab-count" in style:
            state["tab"] = True
            self._ensure_block().runs.append(TextRun("\t"))
        self.stack.append(state)

    def handle_endtag(self, tag):
        if tag in self.VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break
        if tag in self.BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        state = self.stack[-1]
        if state["ignore"] or state["tab"]:
            return
        if state["pre"]:
            for i, line in enumerate(data.split("\n")):
                if i:
                    self._flush()
                    self.current = Block("p")
                self._ensure_block().runs.append(TextRun(line, state["bold"], state["italic"], state["underline"]))
            return
        text = re.sub(r"[ \t\r\n]+", " ", data)
        if not text or (text == " " and self.current is None):
            return
        self._ensure_block().runs.append(TextRun(text, state["bold"], state["italic"], state["underline"]))

    def close(self):
        super().close()
        self._flush()


def parse_input(html: str, text: str) -> list[Block]:
    blocks: list[Block] = []
    if html and html.strip():
        parser = _ClipboardHTMLParser()
        parser.feed(html)
        parser.close()
        blocks = parser.blocks
    if not blocks and text:
        for line in text.replace("\r\n", "\n").split("\n"):
            if b := _normalise_block(Block("p", [TextRun(line)])):
                blocks.append(b)
    return blocks


# --------------------------------------------------------------------------- classification


def _is_section_heading(text: str, hint: str, bold_ratio: float) -> bool:
    t = text.strip().rstrip(":").strip()
    if not t or len(t) > 50 or "\t" in t or DATE_RANGE_RE.search(t) or CONTACT_RE.search(t):
        return False
    if hint in HEADING_HINTS:
        return True
    words = re.findall(r"[a-z]+", t.lower())
    if words and len(words) <= 4 and any(w in SECTION_WORDS for w in words):
        return True
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and t.upper() == t and len(words) <= 3 and bold_ratio >= 0.5


def _is_subheading(text: str, bold_ratio: float) -> bool:
    if len(text) > 160:
        return False
    if "\t" in text or DATE_RANGE_RE.search(text):
        return True
    return bold_ratio >= 0.6 and not text.rstrip().endswith(".")


def classify(items) -> list[str]:
    """items: iterable of (text, hint, bold_ratio). Returns a role per item."""
    roles = []
    seen_name = seen_heading = False
    for text, hint, bold_ratio in items:
        if not seen_name:
            role = "name"
            seen_name = True
        elif hint == "li":
            role = "bullet"
        elif _is_section_heading(text, hint, bold_ratio):
            role = "heading"
            seen_heading = True
        elif not seen_heading:
            role = "contact" if CONTACT_RE.search(text) else ("tagline" if len(text) <= 90 else "body")
        elif _is_subheading(text, bold_ratio):
            role = "subheading"
        else:
            role = "body"
        roles.append(role)
    return roles


# --------------------------------------------------------------------------- default resume analysis


_MISSING = object()


@dataclass
class Prototype:
    element: object  # detached deep copy of a <w:p>
    segment_rprs: list  # rPr (or None) per tab-separated segment
    prefix_runs: list  # runs that render a typed bullet ("•\t") on the prototype
    uppercase: bool
    bold: bool
    italic: bool


def _style_chain(style):
    while style is not None:
        yield style
        style = style.base_style


def _effective(run: Run, para: Paragraph, attr: str) -> bool:
    value = getattr(run.font, attr)
    if value is not None:
        return bool(value)
    rstyle = run._r.rPr.rStyle if run._r.rPr is not None else None
    if rstyle is not None:
        for s in _style_chain(run.style):
            if (v := getattr(s.font, attr)) is not None:
                return bool(v)
    for s in _style_chain(para.style):
        if (v := getattr(s.font, attr)) is not None:
            return bool(v)
    return False


def _is_list_paragraph(para: Paragraph) -> bool:
    pPr = para._p.pPr
    if pPr is not None and pPr.numPr is not None:
        num_id = pPr.numPr.numId
        return num_id is None or num_id.val != 0
    for s in _style_chain(para.style):
        sp = s.element.pPr
        if sp is not None and sp.numPr is not None:
            return True
    name = (para.style.name or "").lower() if para.style is not None else ""
    return "list" in name or bool(BULLET_RE.match(para.text))


def _run_text(r_el) -> str:
    out = []
    for child in r_el:
        if child.tag == qn("w:t"):
            out.append(child.text or "")
        elif child.tag == qn("w:tab"):
            out.append("\t")
    return "".join(out)


def _in_hyperlink(r_el) -> bool:
    return r_el.getparent() is not None and r_el.getparent().tag == qn("w:hyperlink")


def _make_prototype(p_el, para: Paragraph, hint: str) -> Prototype:
    runs = [r for r in p_el.iter(qn("w:r")) if r.find(qn("w:t")) is not None or r.find(qn("w:tab")) is not None]

    # Typed bullets ("•<tab>text") keep their glyph runs verbatim.
    prefix_runs = []
    text = para.text
    m = BULLET_RE.match(text) if hint == "li" else None
    if m and (p_el.pPr is None or p_el.pPr.numPr is None):
        needed = m.end()
        while runs and needed > 0:
            r = runs.pop(0)
            needed -= len(_run_text(r))
            prefix_runs.append(copy.deepcopy(r))

    # rPr per tab-separated segment; prefer runs that are not inside hyperlinks.
    segments, pending, fallback = [], _MISSING, _MISSING
    for r in runs:
        rpr = r.find(qn("w:rPr"))
        for child in r:
            if child.tag == qn("w:t") and (child.text or "").strip():
                if fallback is _MISSING:
                    fallback = rpr
                if pending is _MISSING and not _in_hyperlink(r):
                    pending = rpr
            elif child.tag == qn("w:tab") and pending is not _MISSING:
                segments.append(pending)
                pending = _MISSING
    if pending is not _MISSING:
        segments.append(pending)
    if not segments:
        segments = [None if fallback is _MISSING else fallback]

    text_runs = [Run(r, para) for r in runs if _run_text(r).strip()]
    letters = [c for c in text if c.isalpha()]
    return Prototype(
        element=copy.deepcopy(p_el),
        segment_rprs=[copy.deepcopy(s) if s is not None else None for s in segments],
        prefix_runs=prefix_runs,
        uppercase=bool(letters) and text.upper() == text,
        bold=bool(text_runs) and _effective(text_runs[0], para, "bold"),
        italic=bool(text_runs) and _effective(text_runs[0], para, "italic"),
    )


@dataclass
class Template:
    prototypes: dict  # role -> Prototype
    subheadings: list  # all distinct subheading prototypes
    spacer: object | None  # empty <w:p> used before section headings, if the default does that


def analyse_default(doc) -> Template:
    body = doc.element.body
    paragraphs = []
    for p_el in body.iter(qn("w:p")):
        # Skip VML fallbacks of text boxes (they duplicate the DrawingML content).
        if any(a.tag.endswith("}Fallback") for a in p_el.iterancestors()):
            continue
        paragraphs.append(p_el)

    entries = []  # (p_el, para, text, hint, bold_ratio)
    for p_el in paragraphs:
        para = Paragraph(p_el, doc._body)
        text = para.text
        if not text.strip():
            continue
        style_name = (para.style.name or "").lower() if para.style is not None else ""
        if _is_list_paragraph(para):
            hint = "li"
        elif style_name.startswith("heading") or style_name == "title":
            hint = "h2"
        else:
            hint = "p"
        runs = [Run(r, para) for r in p_el.iter(qn("w:r"))]
        total = sum(len(_run_text(r._r).strip()) for r in runs) or 1
        bold = sum(len(_run_text(r._r).strip()) for r in runs if _effective(r, para, "bold"))
        entries.append((p_el, para, text, hint, bold / total))

    if not entries:
        raise ResumeBuildError("The default resume has no text to learn the styling from.")

    roles = classify((t, h, b) for _, _, t, h, b in entries)
    prototypes, subheadings, sub_signatures = {}, [], set()
    for (p_el, para, _text, hint, _b), role in zip(entries, roles):
        if role == "subheading":
            proto = _make_prototype(p_el, para, hint)
            sig = (proto.bold, proto.italic, "\t" in _text)
            if sig not in sub_signatures:
                sub_signatures.add(sig)
                subheadings.append(proto)
            prototypes.setdefault(role, proto)
        elif role not in prototypes:
            prototypes[role] = _make_prototype(p_el, para, hint)

    # Does the default put an empty paragraph before section headings?
    spacer, with_spacer, heading_count = None, 0, 0
    for (p_el, *_), role in zip(entries, roles):
        if role != "heading":
            continue
        heading_count += 1
        prev = p_el.getprevious()
        if prev is not None and prev.tag == qn("w:p") and not "".join(prev.itertext()).strip():
            with_spacer += 1
            spacer = spacer if spacer is not None else copy.deepcopy(prev)
    if heading_count == 0 or with_spacer * 2 < heading_count:
        spacer = None

    return Template(prototypes, subheadings, spacer)


# --------------------------------------------------------------------------- output


def _new_run(rpr, text: str, flags: tuple | None, uppercase: bool):
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    run = Run(r, None)
    run.text = text.upper() if uppercase else text
    if flags is not None:
        bold, italic, underline = flags
        run.font.bold = True if bold else None
        run.font.italic = True if italic else None
        run.font.underline = True if underline else None
    return r


def _build_paragraph(proto: Prototype, block: Block, use_input_format: bool, force_bold=False, prefix=""):
    p = copy.deepcopy(proto.element)
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)
    pPr = p.find(qn("w:pPr"))
    if pPr is not None:
        for tag in ("w:sectPr", "w:pPrChange"):
            for el in pPr.findall(qn(tag)):
                pPr.remove(el)
    for r in proto.prefix_runs:
        p.append(copy.deepcopy(r))

    segs = proto.segment_rprs
    seg = 0
    runs = list(block.runs)
    if prefix:
        runs.insert(0, TextRun(prefix))
    for tr in runs:
        flags = (tr.bold or force_bold, tr.italic, tr.underline) if use_input_format or force_bold else None
        for k, piece in enumerate(tr.text.split("\t")):
            if k:
                p.append(_new_run(segs[min(seg, len(segs) - 1)], "\t", None, False))
                seg += 1
            if piece:
                p.append(_new_run(segs[min(seg, len(segs) - 1)], piece, flags, proto.uppercase))
    return p


def _pick_prototype(template: Template, role: str, block: Block):
    if role == "subheading" and len(template.subheadings) > 1:
        want = (block.bold_ratio >= 0.5, any(r.italic for r in block.runs), "\t" in block.text)

        def score(p):
            return (p.bold == want[0]) + (p.italic == want[1]) + 2 * (("\t" in "".join(
                _run_text(r) for r in p.element.iter(qn("w:r")))) == want[2])

        return max(template.subheadings, key=score), role
    if role in template.prototypes:
        return template.prototypes[role], role
    for alt in ROLE_FALLBACKS.get(role, []):
        if alt in template.prototypes:
            return template.prototypes[alt], alt
    return next(iter(template.prototypes.values())), "body"


def build_resume(default_path: str, html: str, text: str) -> bytes:
    blocks = parse_input(html, text)
    if not blocks:
        raise ResumeBuildError("The resume input is empty.")
    try:
        doc = Document(default_path)
    except Exception as exc:  # noqa: BLE001 - python-docx raises several types
        raise ResumeBuildError(f"Could not open the default resume: {exc}") from exc
    template = analyse_default(doc)

    body = doc.element.body
    sect_pr = body.find(qn("w:sectPr"))
    for child in list(body):
        if child is not sect_pr:
            body.remove(child)

    def append(el):
        if sect_pr is not None:
            sect_pr.addprevious(el)
        else:
            body.append(el)

    roles = classify((b.text, b.hint, b.bold_ratio) for b in blocks)
    emitted = 0
    for block, role in zip(blocks, roles):
        proto, used_role = _pick_prototype(template, role, block)
        if role == "heading" and template.spacer is not None and emitted:
            append(copy.deepcopy(template.spacer))

        # Tabbed subheadings ("Company<tab>Dates") take each segment's look from the default instead.
        use_input = role in ("body", "bullet") or (
            role == "subheading" and 0 < block.bold_ratio < 1 and "\t" not in block.text)
        force_bold = role in ("heading", "subheading") and used_role == "body"
        prefix = "• " if role == "bullet" and used_role != "bullet" else ""
        append(_build_paragraph(proto, block, use_input, force_bold, prefix))
        emitted += 1

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
