# -*- coding: utf-8 -*-
"""محرك مطابقة أنصاف الأبيات مع ديوان حافظ وسلمان (گنجور) — بدون أي API. يستخدمه app.py."""
import os, re, sys, json, pickle, subprocess, shutil, html as _html
from collections import Counter

import numpy as np
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer


def _log(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            text = " ".join(str(a) for a in args)
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace") + "\n")
            sys.stdout.flush()
        except Exception:
            pass


# ------------------------------------------------------------- إعدادات
POETS = ("hafez", "salman")
TOP_N = 3
MIN_SCORE, MIN_MARGIN = 72.0, 3.5
BONUS_PER, MAX_BONUS = 2.5, 5.0          # دعم القصيدة المشتركة بين الصور
WEAK_MARGIN, WEAK_SCORE = 3.5, 85.0
TFIDF_WEIGHT = 0.15                      # وزن مطابقة n-gram الحرفية
PDF_DPI = 120                            # دقة تحويل صفحات الـ PDF لصور (أعلى = أوضح وأكبر حجم)
ALT_PENALTY = 0.98                       # القراءات البديلة وزنها أقل بقليل من القراءة الأساسية

# ------------------------------------------------------------- معالجة النصوص
_DIAC = re.compile(r"[\u0610-\u061a\u064B-\u0670\u065F\u06D6-\u06ED\u0640]")
_JUNK = re.compile(r"[^\u0600-\u06FF\s]|[\u060C\u061B\u061F\u066A-\u066D\u06D4]")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AR_NORM_MAP = str.maketrans({
    "ک": "ك", "ڪ": "ك", "گ": "ك", "ڭ": "ك",
    "ی": "ي", "ے": "ي", "ې": "ي", "ۍ": "ي", "ۓ": "ي", "ى": "ي", "ئ": "ي",
    "ہ": "ه", "ھ": "ه", "ۀ": "ه", "ۂ": "ه", "ة": "ه", "ۃ": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ؤ": "و",
    "پ": "ب", "چ": "ج", "ژ": "ز", "ڤ": "ف", "ڨ": "ف",
})
_RASM = {
    "غ": "ع", "ج": "ح", "چ": "ح", "خ": "ح",
    "پ": "ب", "ت": "ب", "ث": "ب", "ن": "ب", "ی": "ب", "ي": "ب", "ئ": "ب", "ى": "ب",
    "ز": "ر", "ژ": "ر", "ذ": "د", "ش": "س", "ض": "ص", "ظ": "ط",
    "ق": "ف", "گ": "ک", "ك": "ک", "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ؤ": "و",
}

def clean(text):
    t = _DIAC.sub("", text or "")
    t = t.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ة", "ه")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("ٱ", "ا")
    t = t.replace("\u200c", " ").replace("\u200f", "").replace("\u200e", "")
    t = _JUNK.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()

def ar_norm(text):
    """توحيد الحروف الفارسية والعربية لتسهيل البحث المباشر بالكيبورد العربي أو الفارسي."""
    return clean(text).translate(_AR_NORM_MAP)

def rasm(text):
    return "".join(_RASM.get(c, c) for c in clean(text))

def rasm_nospace(text):
    return rasm(text).replace(" ", "")

# ------------------------------------------------------------- فهرس گنجور
def _run_git(args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()[-700:]
        raise RuntimeError(f"أمر git فشل ({' '.join(args[:2])}):\n{detail}")

def _rmtree(path):
    """حذف مجلد حتى لو فيه ملفات read-only (مشكلة .git على Windows)."""
    import stat
    def onerr(func, p, exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerr)

def fetch_ganjoor(dest="ganjoor-data", poets=POETS):
    ready = all(os.path.isdir(os.path.join(dest, "poets", p)) for p in poets)
    if ready:
        return dest
    if shutil.which("git") is None:
        raise RuntimeError("برنامج Git مش متثبت. نزّله من https://git-scm.com/download/win "
                           "وثبّته (Next لحد الآخر) وبعدين شغّل البرنامج تاني.")
    _log("⏳ سحب نصوص گنجور...")
    if os.path.exists(dest):
        _rmtree(dest)                                   # بقايا محاولة فاشلة قبل كده
    _run_git(["clone", "--depth", "1", "--filter=blob:none", "--sparse",
              "https://github.com/ganjoor/ganjoor-data.git", dest])
    # ملاحظة: في وضع cone ملفات الجذر (زي manifest.json) بتتسحب تلقائياً، وإدخالها هنا بيعمل خطأ في Git الحديث
    _run_git(["-C", dest, "sparse-checkout", "set", *[f"poets/{p}" for p in poets]])
    _run_git(["-C", dest, "checkout"])
    return dest

def _poem_number(title, fallback):
    m = re.search(r"\d+", title.translate(_DIGITS))
    return int(m.group()) if m else fallback

def _hemistich_label(pos):
    p = str(pos).strip().lower()
    if p in ("right", "0"): return "المصراع الأول"
    if p in ("left", "1"): return "المصراع الثاني"
    return "—"

class Index:
    def __init__(self):
        self.entries, self._by_clean, self.couplets = [], {}, {}

    def add(self, text, ref):
        c = clean(text)
        if len(c) < 3:
            return
        if c in self._by_clean:
            self.entries[self._by_clean[c]]["refs"].append(ref)
            return
        self._by_clean[c] = len(self.entries)
        words = c.split()
        self.entries.append({"text": text.strip(), "clean": c, "rasm": rasm(c),
                             "rasm_ns": rasm_nospace(c),
                             "head_ns": rasm_nospace(" ".join(words[:2])), "refs": [ref]})

    def finalize(self):
        self.rasm_list = [e["rasm"] for e in self.entries]
        self.rasm_ns_list = [e["rasm_ns"] for e in self.entries]
        self.head_ns_list = [e["head_ns"] for e in self.entries]
        # فهرس n-gram حرفي (2-4) على الرسم بدون مسافات — بيلقط التشابه حتى لو كلمة اتقرأت غلط
        self.tfidf = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), sublinear_tf=True)
        self.tfidf_mat = self.tfidf.fit_transform(self.rasm_ns_list)
        return self

def build_index(ganjoor_dir="ganjoor-data", poets=POETS):
    idx = Index()
    names = {}
    mp = os.path.join(ganjoor_dir, "manifest.json")
    if os.path.exists(mp):
        try:
            names = {p["FullUrl"].strip("/"): p["Nickname"]
                     for p in json.load(open(mp, encoding="utf-8")).get("Poets", [])}
        except Exception:
            pass
    for poet in poets:
        for root, _, fs in os.walk(os.path.join(ganjoor_dir, "poets", poet)):
            for f in fs:
                if not f.endswith(".json") or f in ("_cat.json", "poet.json"):
                    continue
                try:
                    d = json.load(open(os.path.join(root, f), encoding="utf-8"))
                except Exception:
                    continue
                if "Verses" not in d:
                    continue
                title, url = d.get("Title", ""), "https://ganjoor.net" + d.get("FullUrl", "")
                for v in sorted(d["Verses"], key=lambda x: x.get("VOrder", x.get("VerseOrder", 0))):
                    if str(v.get("Position", "")).strip().lower() == "comment":
                        continue
                    txt = v.get("Text") or ""
                    beyt = (v.get("CoupletIndex", 0) or 0) + 1
                    idx.couplets.setdefault((url, beyt), []).append(txt.strip())
                    idx.add(txt, {"poet": names.get(poet, poet), "poem_title": title,
                                  "poem_no": _poem_number(title, ""), "beyt_no": beyt,
                                  "hemistich": _hemistich_label(v.get("Position", "")), "url": url})
    return idx.finalize()

idx = None   # بيتملي من load_index()

def _ensure_manual_index(target_idx):
    """تجهيز قوائم البحث المباشر السريع (بالعربي والفارسي والرسم) في الذاكرة بدون إعادة بناء الكاش."""
    if getattr(target_idx, "ar_list", None) is not None:
        return target_idx
    target_idx.ar_list = [e["clean"].translate(_AR_NORM_MAP) for e in target_idx.entries]
    target_idx.ar_ns_list = [s.replace(" ", "") for s in target_idx.ar_list]
    target_idx.ar_words_list = [set(s.split()) for s in target_idx.ar_list]
    target_idx.rasm_words_list = [set(s.split()) for s in target_idx.rasm_list]
    return target_idx

def load_index(data_dir="ganjoor-data", cache="index_cache.pkl", log=_log):
    """يحمّل الفهرس من الكاش لو موجود (ثواني)، وإلا يسحب گنجور ويبنيه (أول مرة بس)."""
    global idx
    if idx is not None:
        return _ensure_manual_index(idx)
    if os.path.exists(cache):
        try:
            with open(cache, "rb") as f:
                saved = pickle.load(f)
            if saved.get("poets") == POETS:
                idx = _ensure_manual_index(saved["idx"])
                log(f"✅ الفهرس جاهز من الكاش: {len(idx.entries)} مصراع")
                return idx
        except Exception:
            pass
    log("⏳ أول تشغيل: بيحمّل نصوص گنجور ويبني الفهرس (دقيقة أو اتنين، مرة واحدة بس)...")
    fetch_ganjoor(data_dir)
    idx = _ensure_manual_index(build_index(data_dir))
    with open(cache, "wb") as f:
        pickle.dump({"poets": POETS, "idx": idx}, f)
    log(f"✅ تم بناء الفهرس: {len(idx.entries)} مصراع")
    return idx

# ------------------------------------------------------------- محرك البحث
def score_vector(raw_query):
    """سكور لكل مصراع في الفهرس (0-100) لقراءة واحدة."""
    q = clean(raw_query)
    n = len(idx.entries)
    if not q:
        return np.zeros(n)
    q_ns, q_rasm = rasm_nospace(q), rasm(q)
    q2 = rasm_nospace(" ".join(q.split()[:2]))
    q3 = rasm_nospace(" ".join(q.split()[:3]))
    cd = lambda a, L, sc: process.cdist([a], L, scorer=sc, workers=-1)[0]
    a = cd(q_ns, idx.rasm_ns_list, fuzz.ratio)
    c = cd(q_ns, idx.rasm_ns_list, fuzz.partial_ratio)
    h2 = cd(q2, idx.head_ns_list, fuzz.ratio)
    p2 = cd(q2, [s[:max(len(q2), 4)] for s in idx.rasm_ns_list], fuzz.ratio)
    p3 = cd(q3, [s[:max(len(q3), 6)] for s in idx.rasm_ns_list], fuzz.ratio)
    ts = cd(q_rasm, idx.rasm_list, fuzz.token_set_ratio)

    full = 0.30 * a + 0.25 * (0.5 * h2 + 0.5 * p2) + 0.20 * c + 0.25 * ts
    prefix = (0.50 * p2 + 0.25 * p3 + 0.10 * a + 0.15 * ts) * 0.97
    prefix = prefix * (prefix >= 70)
    fuzzy = np.maximum(full, prefix)

    cos = (idx.tfidf_mat @ idx.tfidf.transform([q_ns]).T).toarray().ravel() * 100
    return (1 - TFIDF_WEIGHT) * fuzzy + TFIDF_WEIGHT * cos

def search(readings, top_k=20):
    """readings = [القراءة الأساسية, بدائل...] — ناخد أعلى سكور لكل مصراع عبر كل القراءات."""
    vecs = [score_vector(r) * (1.0 if i == 0 else ALT_PENALTY) for i, r in enumerate(readings) if clean(r)]
    if not vecs:
        return []
    s = np.max(vecs, axis=0)
    order = s.argsort()[::-1][:top_k]
    return [{"score": float(s[i]), "entry": idx.entries[i]} for i in order]

def top_distinct(results, n=TOP_N, dup_ratio=90):
    groups = []
    for r in results:
        for g in groups:
            if fuzz.ratio(g["entry"]["clean"], r["entry"]["clean"]) >= dup_ratio:
                g["extra"].extend(r["entry"]["refs"])
                break
        else:
            if len(groups) < n:
                groups.append({**r, "extra": [], "bonus": 0.0, "support": []})
    return groups

def manual_search(raw_query, top_n=TOP_N, max_exact=50):
    """
    بحث مباشر ومرن في كل الداتا (حافظ وسلمان):
    يدعم البحث بحرف، أو كلمة، أو جزء من كلمة، أو عدة كلمات متفرقة/متتالية، أو مصراع كامل
    سواء بالحروف العربية أو الفارسية أو بدون نقط (رسم الخط).
    يرجع:
      - tops: أقرب 3 تطابقات (الأقرب + البدائل)
      - exact_matches: الأبيات المتطابقة في الداتا
      - total_exact: إجمالي عدد الأبيات المتطابقة في الداتا
    """
    _ensure_manual_index(idx)
    q_clean = clean(raw_query)
    if not q_clean:
        return {"query": raw_query, "tops": [], "exact_matches": [], "total_exact": 0}

    q_ar = q_clean.translate(_AR_NORM_MAP)
    q_ar_ns = q_ar.replace(" ", "")
    q_rasm = rasm(q_clean)
    q_rasm_ns = q_rasm.replace(" ", "")
    q_ar_words = [w for w in q_ar.split() if w]
    q_rasm_words = [w for w in q_rasm.split() if w]

    n = len(idx.entries)
    direct_scores = np.zeros(n, dtype=float)
    match_types = [""] * n

    for i in range(n):
        e_ar = idx.ar_list[i]
        e_ar_ns = idx.ar_ns_list[i]
        e_ar_words = idx.ar_words_list[i]
        e_len = max(len(e_ar_ns), 1)
        cov = min(1.0, len(q_ar_ns) / e_len)

        # 1) تطابق تام للمصراع أو تطابق كامل للكلمات بالحروف
        if q_ar_ns == e_ar_ns:
            direct_scores[i] = 100.0
            match_types[i] = "تطابق تام"
        elif q_ar in e_ar and all(w in e_ar_words for w in q_ar_words):
            start_bonus = 1.5 if e_ar_ns.startswith(q_ar_ns) else 0.0
            direct_scores[i] = min(99.5, 95.5 + 2.5 * cov + start_bonus)
            match_types[i] = "تطابق مباشر بالكلمات"
        elif all(w in e_ar_words for w in q_ar_words):
            start_bonus = 1.0 if e_ar_ns.startswith(q_ar_words[0]) else 0.0
            direct_scores[i] = min(96.0, 92.5 + 2.5 * cov + start_bonus)
            match_types[i] = "تطابق بالكلمات"
        elif q_ar_ns in e_ar_ns or all(w in e_ar for w in q_ar_words):
            start_bonus = 1.5 if e_ar_ns.startswith(q_ar_ns) else 0.0
            direct_scores[i] = min(93.5, 88.5 + 3.0 * cov + start_bonus)
            match_types[i] = "تطابق جزئي بالنص"
        elif len(q_rasm_ns) >= 2:
            # 2) تطابق على مستوى رسم الخط (بدون نقط — مفيد جداً لقراءة المخطوطات)
            e_rasm = idx.rasm_list[i]
            e_rasm_ns = idx.rasm_ns_list[i]
            e_rasm_words = idx.rasm_words_list[i]
            if all(w in e_rasm_words for w in q_rasm_words):
                start_bonus = 1.0 if e_rasm_ns.startswith(q_rasm_words[0]) else 0.0
                direct_scores[i] = min(88.0, 84.0 + 2.5 * cov + start_bonus)
                match_types[i] = "تطابق برسم الخط (بدون نقط)"
            elif q_rasm_ns in e_rasm_ns or all(w in e_rasm for w in q_rasm_words):
                start_bonus = 1.0 if e_rasm_ns.startswith(q_rasm_ns) else 0.0
                direct_scores[i] = min(84.5, 80.0 + 2.5 * cov + start_bonus)
                match_types[i] = "تطابق جزئي برسم الخط"

    # حساب السكور التقريبي (Fuzzy + TF-IDF) عشان دايماً نطلع أقرب 3 حتى لو فيه خطأ إملائي
    if len(q_ar_ns) >= 2:
        cd = lambda a, L, sc: process.cdist([a], L, scorer=sc, workers=-1)[0]
        base_vec = score_vector(raw_query)
        ar_part = cd(q_ar_ns, idx.ar_ns_list, fuzz.partial_ratio)
        ar_ts = cd(q_ar, idx.ar_list, fuzz.token_set_ratio)
        rasm_part = cd(q_rasm_ns, idx.rasm_ns_list, fuzz.partial_ratio)
        rasm_ts = cd(q_rasm, idx.rasm_list, fuzz.token_set_ratio)

        if len(q_ar_words) <= 2 and len(q_ar_ns) <= 12:
            # لو المستخدم كاتب كلمة واحدة أو كلمتين (أو كام حرف) في أي مكان في البيت
            short_fuzzy = 0.40 * ar_ts + 0.30 * ar_part + 0.15 * rasm_ts + 0.15 * rasm_part
            fuzzy_scores = np.maximum(base_vec, short_fuzzy * 0.92)
        else:
            mid_fuzzy = 0.35 * ar_ts + 0.25 * ar_part + 0.25 * rasm_ts + 0.15 * rasm_part
            fuzzy_scores = np.maximum(base_vec, mid_fuzzy * 0.95)
    else:
        fuzzy_scores = direct_scores.copy()

    combined_scores = np.maximum(direct_scores, fuzzy_scores)

    # ترتيب كل النتائج لأقرب 3
    top_indices = combined_scores.argsort()[::-1][:max(30, top_n * 6)]
    raw_top_results = [
        {
            "score": float(combined_scores[i]),
            "entry": idx.entries[i],
            "match_type": match_types[i] or "تطابق تقريبي",
        }
        for i in top_indices
        if combined_scores[i] > 0
    ]
    tops = top_distinct(raw_top_results, n=top_n)

    # جمع كل الأبيات المتطابقة فعلياً في الداتا
    exact_indices = np.where(direct_scores >= 80.0)[0]
    exact_order = exact_indices[np.argsort(direct_scores[exact_indices])[::-1]]
    total_exact = int(len(exact_order))

    exact_raw = [
        {
            "score": float(direct_scores[i]),
            "entry": idx.entries[i],
            "match_type": match_types[i],
        }
        for i in exact_order[:max_exact * 2]
    ]
    exact_matches = top_distinct(exact_raw, n=max_exact)

    return {
        "query": raw_query,
        "tops": tops,
        "exact_matches": exact_matches,
        "total_exact": total_exact,
    }

# ------------------------------------------------------------- PDF -> صور (صفحة = صورة)
def _autocrop(path, pad=8, white_thresh=245):
    """يقص الفراغ الأبيض حوالين الصورة (صفحة A4 فيها المصراع في النص) ويحفظ فوق نفس الملف."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        mask = im.convert("L").point(lambda x: 255 if x < white_thresh else 0)
        box = mask.getbbox()
        if not box:
            return
        l, t, r, b = box
        box = (max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad))
        im.crop(box).save(path, quality=90)
    except Exception as e:
        _log("⚠️ تعذر قص الصورة:", e)

def pdf_to_images(pdf_path, out_dir="pdf_pages", dpi=PDF_DPI):
    """يحوّل كل صفحة في الـ PDF لصورة JPEG بترقيم page_001.jpg ... بنفس ترتيب الصفحات."""
    import fitz  # PyMuPDF
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths = []
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi)
        out = os.path.join(out_dir, f"page_{i:03d}.jpg")
        pix.save(out, jpg_quality=90)
        _autocrop(out)                       # قص الهوامش البيضاء حوالين المصراع
        paths.append(out)
    _log(f"📄 {os.path.basename(pdf_path)}: {len(paths)} صفحة اتحولت لصور")
    return paths

# ------------------------------------------------------------- قراءة JSON
def _norm(s):
    return re.sub(r"[^0-9a-z]", "", s.lower())

def _find_image(file_hint, number, image_paths):
    if not image_paths:
        return None
    hint = _norm(file_hint)
    if hint:
        for p in image_paths:
            nb = _norm(os.path.basename(p))
            if nb == hint or hint in nb or nb in hint:
                return p
    if number and 1 <= number <= len(image_paths):
        return image_paths[number - 1]
    return None

_WRAP_KEYS = ("response", "result", "results", "output", "images", "items", "data", "pages", "readings", "content", "text")

def _unwrap(data, depth=0):
    """يفك أي تغليف: نص JSON جوه نص، أو قاموس زي {"response": "[...]"} أو {"results": [...]}."""
    if depth > 5:
        return data
    if isinstance(data, str):
        t = re.sub(r"^```(?:json)?|```$", "", data.strip(), flags=re.M).strip()
        if t[:1] in "[{":
            try:
                return _unwrap(json.loads(t), depth + 1)
            except json.JSONDecodeError:
                return data
        return data
    if isinstance(data, dict):
        for k in _WRAP_KEYS:
            if k in data and isinstance(data[k], (list, str, dict)):
                inner = _unwrap(data[k], depth + 1)
                if isinstance(inner, list):
                    return inner
                if isinstance(inner, dict) and k != "text":
                    return inner
    return data

def load_readings(json_path, image_paths=()):
    return parse_readings(open(json_path, encoding="utf-8").read(), image_paths)

def parse_readings(raw, image_paths=()):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()   # لو Gemini لفّه في ```
    m = re.search(r"[\[{]", raw)                                              # تجاهل أي كلام قبل أول [ أو {
    if m:
        raw = raw[m.start():]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"الـ JSON فيه خطأ (سطر {e.lineno}، عمود {e.colno}): {e.msg}. "
                         "اتأكد إنك نسخته كله من Gemini.")
    data = _unwrap(data)
    if isinstance(data, dict):
        data = [{"file": k, "text": v} for k, v in data.items()]
    items = []
    for n, d in enumerate(data, 1):
        if isinstance(d, str):
            d = {"text": d}
        number = d.get("page") or d.get("index") or d.get("order") or n
        try: number = int(number)
        except Exception: number = n
        file_hint = str(d.get("file") or d.get("filename") or d.get("name") or "")
        alts = d.get("alternatives") or d.get("alts") or []
        if isinstance(alts, str): alts = [alts]
        items.append({
            "number": number,
            "name": file_hint or f"image_{number}",
            "path": _find_image(file_hint, number, list(image_paths)),
            "reading": str(d.get("text") or d.get("reading") or "").strip(),
            "alts": [str(a).strip() for a in alts if str(a).strip()],
            "confidence": str(d.get("confidence") or "").lower(),
            "uncertain": d.get("uncertain_words") or [],
            "notes": [],
        })
    return items

# ------------------------------------------------------------- التحليل
def _adj(g): return g["score"] + g["bonus"]

def _status(tops):
    if not tops:
        return "NO_MATCH", 0.0
    margin = _adj(tops[0]) - (_adj(tops[1]) if len(tops) > 1 else 0.0)
    return ("AUTO" if _adj(tops[0]) >= MIN_SCORE and margin >= MIN_MARGIN else "REVIEW"), margin

def _poem_keys(g):
    return {(r["poet"], r["poem_title"]) for r in g["entry"]["refs"] + g["extra"]}

def analyze(items):
    for it in items:
        qs = ([it["reading"]] if it["reading"] else []) + it["alts"]
        it["tops"] = top_distinct(search(qs)) if qs else []
        it["status"], it["margin"] = _status(it["tops"])

    # دعم القصيدة المشتركة
    auto = {i: _poem_keys(it["tops"][0]) for i, it in enumerate(items) if it["status"] == "AUTO"}
    for i, it in enumerate(items):
        for g in it["tops"]:
            ks = _poem_keys(g)
            g["support"] = [items[j]["name"] for j, k in auto.items() if j != i and ks & k]
            g["bonus"] = min(MAX_BONUS, BONUS_PER * len(g["support"]))
        it["tops"].sort(key=_adj, reverse=True)
        it["status"], it["margin"] = _status(it["tops"])
        if it["tops"] and it["tops"][0]["support"]:
            it["notes"].append(f"🔗 {len(it['tops'][0]['support'])} صورة مؤكدة من نفس القصيدة تدعم هذا الاختيار.")

    for it in items:
        if it["status"] == "REVIEW" and it["margin"] < WEAK_MARGIN and _adj(it["tops"][0]) < WEAK_SCORE:
            it["status"] = "WEAK"
            it["notes"].append("🔴 قراءة غير موثوقة: المرشحات ضعيفة ومتقاربة، غالباً القراءة نفسها غلط. "
                               "اطلب من Gemini يعيد قراءة الصورة دي أو اكتبها يدوياً.")
        if it["confidence"] in ("low", "منخفض") and it["status"] == "AUTO":
            it["status"] = "REVIEW"
            it["notes"].append("🟡 Gemini نفسه قال إن ثقته منخفضة في القراءة — راجع الصورة.")
        if it["uncertain"]:
            it["notes"].append("❓ كلمات غير مؤكدة حسب Gemini: " + "، ".join(map(str, it["uncertain"])))
    return items

# ------------------------------------------------------------- التقرير HTML
BADGE = {"AUTO": ("🟢 مؤكد", "#17703a"), "REVIEW": ("🟡 يحتاج مراجعة", "#8a5a00"),
         "WEAK": ("🔴 قراءة غير موثوقة", "#b3261e"), "NO_MATCH": ("🔴 لا يوجد تطابق", "#b3261e")}

def _where(r):
    return f"{r['poet']} · {r['poem_title']} · البيت {r['beyt_no']} ({r['hemistich']})"

def _mime(path):
    e = os.path.splitext(path)[1].lower().strip(".")
    return "jpeg" if e in ("jpg", "jpeg") else e

def _img_src(path):
    import base64
    return f"data:image/{_mime(path)};base64," + base64.b64encode(open(path, "rb").read()).decode()

FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800'
             '&family=Noto+Naskh+Arabic:wght@400;500;600;700'
             '&family=Noto+Nastaliq+Urdu:wght@400;500;600;700&display=swap" rel="stylesheet">')
FONT_STACK = "'Vazirmatn','Noto Naskh Arabic','Segoe UI',Tahoma,Arial,sans-serif"
POEM_STACK = "'Noto Nastaliq Urdu','Vazirmatn','Noto Naskh Arabic',Georgia,serif"


def _couplet_pair(couplet, matched=None):
    """يرجع المصراعين الفعليين للبيت حتى لو الكاش فيه سطر عنوان قبله."""
    if not couplet:
        return []
    if len(couplet) > 2:
        mc = clean(matched or "")
        if mc and any(clean(t) == mc for t in couplet[-2:]):
            return couplet[-2:]
    return couplet[:2]


def beyt_html(couplet, matched=None):
    """البيت كامل: المصراعين جنب بعض (الأول يمين والتاني شمال)، والمصراع المطابق متظلّل."""
    esc = _html.escape
    pair = _couplet_pair(couplet, matched)
    if len(pair) < 2:
        return ""
    mc = clean(matched or "")
    parts = []
    for t in pair:
        cls = "hem match" if mc and clean(t) == mc else "hem"
        parts.append(f'<span class="{cls}">{esc(t)}</span>')
    return f'<div class="beyt" dir="rtl">{parts[0]}<span class="sep">◆</span>{parts[1]}</div>'


def render_html(items):
    esc = _html.escape
    css = """
:root{
--bg:#f6f2e8;--card:#fffdf8;--card-2:#fbf7ee;--text:#26231d;--muted:#777064;--line:#e5ddca;
--green:#1e6b57;--green-2:#154f41;--green-soft:#e8f1ec;--gold:#b78e3c;--gold-soft:#f6ecd2;
--hem:#f0ead9;--match:#f8e6a8;--link:#1e6b57;--thead:#f3ecdc;
--shadow:0 18px 40px -34px rgba(62,46,18,.55);
}
@media (prefers-color-scheme: dark){:root{
--bg:#14161a;--card:#1e2126;--card-2:#23272e;--text:#ecebe6;--muted:#adadb2;--line:#3a3d44;
--green:#4cc27a;--green-2:#8fe0ae;--green-soft:#1c2f22;--gold:#d9b464;--gold-soft:#3a3118;
--hem:#2b2f37;--match:#5a4a10;--link:#8cc0ff;--thead:#2b2f37;
--shadow:0 18px 40px -34px rgba(0,0,0,.8);
}}
*{box-sizing:border-box}
html{color-scheme:light dark}
body{margin:0;padding:26px 16px 46px;background:var(--bg);color:var(--text);font-family:__FONT__;
line-height:1.8;overflow-wrap:anywhere;-webkit-font-smoothing:antialiased}
.wrap{max-width:900px;margin:auto}
.hero{position:relative;text-align:center;padding:4px 8px 22px;margin-bottom:8px}
.hero .orn{color:var(--gold);font-size:1.1rem;line-height:1;margin-bottom:6px}
.hero h1{font-size:clamp(1.6rem,4vw,2.15rem);margin:2px 0 6px;font-weight:800;line-height:1.5}
.hero p{margin:0 auto;color:var(--muted);font-size:.95rem}
.hero:after{content:"";position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:min(220px,65%);
height:1px;background:linear-gradient(90deg,transparent,var(--gold),transparent)}
.tablebox{overflow-x:auto;margin:22px 0}
table{border-collapse:separate;border-spacing:0;width:100%;background:var(--card);color:var(--text);
font-size:.88rem;border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{border-bottom:1px solid var(--line);padding:9px 12px;text-align:right;vertical-align:top}
tr:last-child td{border-bottom:none}
th{background:var(--thead);font-weight:700}
.card{background:var(--card);color:var(--text);border-radius:18px;padding:16px 18px;margin:18px 0;
border:1px solid var(--line);box-shadow:var(--shadow)}
.head{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;margin-bottom:8px}
.num{display:inline-grid;place-items:center;min-width:30px;height:30px;padding:0 7px;border-radius:9px;
background:var(--green-soft);color:var(--green-2);font-weight:800;font-size:.92rem}
.fname{color:var(--muted);font-size:.85rem}
.badge{color:#fff;border-radius:999px;padding:2px 12px;font-size:.8rem;font-weight:700;
margin-inline-start:auto;white-space:nowrap}
.card img{display:block;margin:10px auto 12px;width:auto;max-width:100%;max-height:220px;object-fit:contain;
border:1px solid var(--line);border-radius:12px;box-shadow:0 14px 30px -24px rgba(0,0,0,.45)}
.read{background:var(--card-2);border:1px dashed var(--line);border-radius:12px;padding:9px 12px 8px;
margin:8px 0 12px;color:var(--muted);font-size:.85rem}
.read-label{display:block;font-size:.75rem;font-weight:700;color:var(--gold);letter-spacing:.02em}
.read .rt{font-family:__POEM__;font-size:1.18rem;line-height:2.4;color:var(--text);padding:2px 0}
.cand{border:1px solid var(--line);border-right:4px solid var(--line);background:var(--card-2);
color:var(--text);padding:10px 14px;margin:10px 0;border-radius:12px}
.cand.main{border-right-color:var(--green);background:linear-gradient(180deg,var(--green-soft),transparent)}
.cand-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:2px}
.c-title{font-weight:800;font-size:.95rem}
.score{font-size:.82rem;color:var(--muted);font-variant-numeric:tabular-nums}
.bonus{color:var(--green);font-weight:600}
.verse{font-family:__POEM__;font-size:clamp(1.15rem,2.4vw,1.4rem);line-height:2.5;margin:4px 0;
text-align:center;color:var(--text)}
.beyt{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:2px 14px;margin:2px 0 8px;
font-family:__POEM__;font-size:clamp(1.05rem,2.2vw,1.3rem);line-height:2.45}
.hem{background:var(--hem);color:var(--text);padding:2px 10px;border-radius:8px;text-align:center}
.hem.match{background:var(--match)}
.sep{color:var(--gold);font-size:.65rem}
.det{font-size:.84rem;color:var(--muted);line-height:1.8}
.note{font-size:.87rem;margin:5px 0;color:var(--muted);line-height:1.8}
.note.warn{background:var(--gold-soft);color:var(--text);padding:6px 10px;border-radius:10px;margin:8px 0}
a{color:var(--link);text-decoration:none;border-bottom:1px dotted currentColor}
a:hover{border-bottom-style:solid}
bdi.l{unicode-bidi:isolate;direction:ltr}
.footer{text-align:center;color:var(--muted);font-size:.78rem;line-height:1.9;margin-top:30px}
@media (max-width:640px){
.beyt{grid-template-columns:1fr;gap:2px}
.beyt .sep{display:none}
body{padding:18px 10px 34px}
.card{padding:14px 14px}
.tablebox{display:none}
}
@media print{
body{background:#fff;color:#000;padding:0}
.card{box-shadow:none;break-inside:avoid}
a{color:#000}
}
""".replace("__FONT__", FONT_STACK).replace("__POEM__", POEM_STACK)
    rows = "".join(
        f"<tr><td><bdi class='l'>{it['number']}</bdi></td><td><bdi class='l'>{esc(it['name'])}</bdi></td>"
        f"<td>{esc(BADGE[it['status']][0])}</td>"
        f"<td>{esc(_where(it['tops'][0]['entry']['refs'][0])) if it['tops'] else '—'}</td></tr>" for it in items)
    cards = []
    for it in items:
        label, color = BADGE[it["status"]]
        pill_label = label.replace("🟢", "").replace("🟡", "").replace("⚠️", "").strip()
        c = [f'<div class="card"><div class="head"><span class="num"><bdi class="l">{it["number"]}</bdi></span>'
             f'<span class="fname"><bdi class="l">{esc(it["name"])}</bdi></span>'
             f'<span class="badge" style="background:{color}">{esc(pill_label)}</span></div>']
        if it["path"] and os.path.exists(it["path"]):
            c.append(f'<img src="{_img_src(it["path"])}" alt="">')
        c.append('<div class="read"><span class="read-label">القراءة من الصورة</span>'
                 f'<div class="rt" dir="rtl">{esc(it["reading"] or "—")}</div>'
                 + ("<div>بدائل: " + " / ".join(f'<span dir="rtl">{esc(a)}</span>' for a in it["alts"]) + "</div>"
                    if it["alts"] else "")
                 + "</div>")
        for k, g in enumerate(it["tops"]):
            e, r = g["entry"], g["entry"]["refs"][0]
            title = f"مرشح ضعيف {k+1}" if it["status"] == "WEAK" else ("الأقرب" if k == 0 else f"البديل {k}")
            score = f'<bdi class="l">{g["score"]:.1f}%</bdi>'
            if g["bonus"]:
                score += f' <span class="bonus"><bdi class="l">+{g["bonus"]:.1f}</bdi> دعم القصيدة</span>'
            full = idx.couplets.get((r["url"], r["beyt_no"]), [])
            verse = "" if full else f'<div class="verse" dir="rtl">{esc(e["text"])}</div>'
            det = [_where(r)] + [f"نفس السطر أيضاً في: {_where(x)}" for x in (e["refs"][1:] + g["extra"])[:4]]
            c.append(f'<div class="cand{" main" if k == 0 else ""}">'
                     f'<div class="cand-head"><span class="c-title">{esc(title)}</span>'
                     f'<span class="score">تطابق {score}</span></div>'
                     + verse
                     + beyt_html(full, e["text"])
                     + "".join(f'<div class="det" dir="rtl">{esc(d)}</div>' for d in det)
                     + f'<div class="det"><a href="{esc(r["url"])}" target="_blank" rel="noopener">فتح في گنجور ↗</a></div></div>')
        if it["status"] in ("REVIEW", "WEAK") and it["tops"]:
            c.append(f'<div class="note warn">⚠️ الفرق بين الأول والثاني <bdi class="l">{it["margin"]:.1f}</bdi> '
                     'نقطة — راجع الصورة.</div>')
        c += [f'<div class="note">{esc(n)}</div>' for n in it["notes"]]
        c.append("</div>")
        cards.append("".join(c))
    n_rev = sum(1 for it in items if it["status"] != "AUTO")
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>نتائج مطابقة الأبيات</title>'
            f'{FONT_LINK}<style>{css}</style></head><body><div class="wrap">'
            '<div class="hero"><div class="orn">❖</div><h1>نتائج مطابقة الأبيات</h1>'
            f'<p>عدد الصفحات <bdi class="l">{len(items)}</bdi> · تحتاج مراجعة <bdi class="l">{n_rev}</bdi></p></div>'
            f'<div class="tablebox"><table><tr><th>#</th><th>الملف</th><th>الحالة</th><th>الأقرب</th></tr>{rows}</table></div>'
            f'{"".join(cards)}<div class="footer">النصوص من '
            '<a href="https://ganjoor.net" target="_blank" rel="noopener">گنجور</a> · تقرير محلي</div>'
            '</div></body></html>')


def run(json_source, image_paths=()):
    """json_source = نص JSON مباشرة، أو مسار ملف .json"""
    image_paths = sorted(image_paths)
    if os.path.exists(str(json_source)):
        readings = load_readings(json_source, image_paths)
    else:
        readings = parse_readings(json_source, image_paths)
    items = analyze(readings)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(render_html(items))
    _log("📊", dict(Counter(it["status"] for it in items)))
    return items

# ------------------------------------------------------------- التشغيل في Colab
