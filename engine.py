# -*- coding: utf-8 -*-
"""محرك قراءة ومطابقة أنصاف الأبيات مع ديوان حافظ وسلمان (گنجور)."""
import os, io, re, sys, json, base64, pickle, subprocess, shutil, urllib.request, html as _html
from collections import Counter

import numpy as np
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer


def _log(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass


# ------------------------------------------------------------- إعدادات المطابقة
POETS = ("hafez", "salman")
TOP_N = 3
MIN_SCORE, MIN_MARGIN = 72.0, 3.5
BONUS_PER, MAX_BONUS = 2.5, 5.0
WEAK_MARGIN, WEAK_SCORE = 3.5, 85.0
TFIDF_WEIGHT = 0.15
ALT_PENALTY = 0.98

# ------------------------------------------------------------- إعدادات المحرك السحابي
# المفاتيح بتتقرأ من st.secrets أو متغيرات البيئة (GEMINI_API_KEYS) — ممنوع كتابتها في الكود
DEFAULT_API_KEYS = []

PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]

JSON_STRUCTURE = '{"type":"object","properties":{"results":{"type":"array","items":{"type":"object","properties":{"page":{"type":"integer"},"text":{"type":"string"},"alternatives":{"type":"array","items":{"type":"string"}},"uncertain_words":{"type":"array","items":{"type":"string"}},"confidence":{"type":"string","enum":["high","medium","low"]}},"required":["page","text","alternatives","uncertain_words","confidence"]}}},"required":["results"]}'
RESPONSE_SCHEMA = json.loads(JSON_STRUCTURE)

DEFAULT_SYSTEM_INSTRUCTION = """You are an expert in Persian classical poetry (especially Hafez and Salman Savoji) and in reading old Nastaliq manuscript calligraphy.
I am sending you numbered manuscript images in exact order (PAGE 1, PAGE 2, ...). Each image contains ONE hemistich (half a line) of a Persian poem in old Nastaliq script.
RULES:
1. Read right-to-left. Pay extra attention to the FIRST words on the right side.
2. Transcribe only what is visibly written. Do NOT autocomplete or invent verses from memory.
3. Nastaliq drops or shifts dots (ب/پ/ت/ث/ن/ی, ج/چ/ح/خ, ر/ز/ژ, د/ذ, س/ش, ع/غ, ف/ق, ک/گ). Use meaning, meter, and grammar to decide.
4. Use standard Persian letters (ی ک گ چ پ ژ), not Arabic ي ك. No diacritics or punctuation.
5. Put your best full-hemistich reading in "text", and other plausible full-hemistich readings in "alternatives".
6. Process EVERY page in exact order (1 to N). Do not skip, merge, or reorder pages.
Return ONLY a valid JSON object with the "results" array matching the schema."""

# ------------------------------------------------------------- معالجة النصوص
_DIAC = re.compile(r"[\u0610-\u061a\u064B-\u0670\u065F\u06D6-\u06ED\u0640]")
_JUNK = re.compile(r"[^\u0600-\u06FF\s]|[\u060C\u061B\u061F\u066A-\u066D\u06D4]")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AR_NORM_MAP = str.maketrans({
    "ک": "ك", "ڪ": "ك", "گ": "ك", "ڭ": "ك",
    "ی": "ي", "ے": "ي", "ې": "ي", "ۍ": "ي", "ۓ": "ي", "ى": "ي", "ئ": "ي",
    "ہ": "ه", "ھ": "ه", "ۀ": "ه", "ۂ": "ه", "ة": "ه", "ۃ": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ؤ": "و",
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
    import stat
    def onerr(func, p, exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerr)


def fetch_ganjoor(dest="ganjoor-data", poets=POETS):
    if all(os.path.isdir(os.path.join(dest, "poets", p)) for p in poets):
        return dest
    if shutil.which("git") is None:
        raise RuntimeError("برنامج Git مش متثبت. نزّله من https://git-scm.com/download/win")
    _log("⏳ سحب نصوص گنجور...")
    if os.path.exists(dest):
        _rmtree(dest)
    _run_git(["clone", "--depth", "1", "--filter=blob:none", "--sparse",
              "https://github.com/ganjoor/ganjoor-data.git", dest])
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


idx = None


def _ensure_manual_index(target_idx):
    if getattr(target_idx, "ar_list", None) is not None:
        return target_idx
    target_idx.ar_list = [e["clean"].translate(_AR_NORM_MAP) for e in target_idx.entries]
    target_idx.ar_ns_list = [s.replace(" ", "") for s in target_idx.ar_list]
    target_idx.ar_words_list = [set(s.split()) for s in target_idx.ar_list]
    target_idx.rasm_words_list = [set(s.split()) for s in target_idx.rasm_list]
    return target_idx


def load_index(data_dir="ganjoor-data", cache="index_cache.pkl", log=_log):
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
    log("⏳ أول تشغيل: بيحمّل نصوص گنجور ويبني الفهرس...")
    fetch_ganjoor(data_dir)
    idx = _ensure_manual_index(build_index(data_dir))
    with open(cache, "wb") as f:
        pickle.dump({"poets": POETS, "idx": idx}, f)
    log(f"✅ تم بناء الفهرس: {len(idx.entries)} مصراع")
    return idx


# ------------------------------------------------------------- محرك البحث
def score_vector(raw_query):
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
        cov = min(1.0, len(q_ar_ns) / max(len(e_ar_ns), 1))

        if q_ar_ns == e_ar_ns:
            direct_scores[i] = 100.0
            match_types[i] = "تطابق تام"
        elif q_ar in e_ar and all(w in e_ar_words for w in q_ar_words):
            start_b = 1.5 if e_ar_ns.startswith(q_ar_ns) else 0.0
            direct_scores[i] = min(99.5, 95.5 + 2.5 * cov + start_b)
            match_types[i] = "تطابق مباشر بالكلمات"
        elif all(w in e_ar_words for w in q_ar_words):
            start_b = 1.0 if e_ar_ns.startswith(q_ar_words[0]) else 0.0
            direct_scores[i] = min(96.0, 92.5 + 2.5 * cov + start_b)
            match_types[i] = "تطابق بالكلمات"
        elif q_ar_ns in e_ar_ns or all(w in e_ar for w in q_ar_words):
            start_b = 1.5 if e_ar_ns.startswith(q_ar_ns) else 0.0
            direct_scores[i] = min(93.5, 88.5 + 3.0 * cov + start_b)
            match_types[i] = "تطابق جزئي بالنص"
        elif len(q_rasm_ns) >= 2:
            e_rasm = idx.rasm_list[i]
            e_rasm_ns = idx.rasm_ns_list[i]
            e_rasm_words = idx.rasm_words_list[i]
            if all(w in e_rasm_words for w in q_rasm_words):
                start_b = 1.0 if e_rasm_ns.startswith(q_rasm_words[0]) else 0.0
                direct_scores[i] = min(88.0, 84.0 + 2.5 * cov + start_b)
                match_types[i] = "تطابق برسم الخط (بدون نقط)"
            elif q_rasm_ns in e_rasm_ns or all(w in e_rasm for w in q_rasm_words):
                start_b = 1.0 if e_rasm_ns.startswith(q_rasm_ns) else 0.0
                direct_scores[i] = min(84.5, 80.0 + 2.5 * cov + start_b)
                match_types[i] = "تطابق جزئي برسم الخط"

    if len(q_ar_ns) >= 2:
        cd = lambda a, L, sc: process.cdist([a], L, scorer=sc, workers=-1)[0]
        base_vec = score_vector(raw_query)
        ar_part = cd(q_ar_ns, idx.ar_ns_list, fuzz.partial_ratio)
        ar_ts = cd(q_ar, idx.ar_list, fuzz.token_set_ratio)
        rasm_part = cd(q_rasm_ns, idx.rasm_ns_list, fuzz.partial_ratio)
        rasm_ts = cd(q_rasm, idx.rasm_list, fuzz.token_set_ratio)
        if len(q_ar_words) <= 2 and len(q_ar_ns) <= 12:
            short_f = 0.40 * ar_ts + 0.30 * ar_part + 0.15 * rasm_ts + 0.15 * rasm_part
            fuzzy_scores = np.maximum(base_vec, short_f * 0.92)
        else:
            mid_f = 0.35 * ar_ts + 0.25 * ar_part + 0.25 * rasm_ts + 0.15 * rasm_part
            fuzzy_scores = np.maximum(base_vec, mid_f * 0.95)
    else:
        fuzzy_scores = direct_scores.copy()

    combined_scores = np.maximum(direct_scores, fuzzy_scores)
    top_indices = combined_scores.argsort()[::-1][:max(30, top_n * 6)]
    raw_top = [
        {"score": float(combined_scores[i]), "entry": idx.entries[i], "match_type": match_types[i] or "تطابق تقريبي"}
        for i in top_indices if combined_scores[i] > 0
    ]
    tops = top_distinct(raw_top, n=top_n)

    exact_indices = np.where(direct_scores >= 80.0)[0]
    exact_order = exact_indices[np.argsort(direct_scores[exact_indices])[::-1]]
    exact_raw = [
        {"score": float(direct_scores[i]), "entry": idx.entries[i], "match_type": match_types[i]}
        for i in exact_order[:max_exact * 2]
    ]
    return {
        "query": raw_query,
        "tops": tops,
        "exact_matches": top_distinct(exact_raw, n=max_exact),
        "total_exact": int(len(exact_order)),
    }


# ------------------------------------------------------------- تجهيز الصور بدون أي قص
def prepare_uploaded_images(saved_files, out_dir="prepared_images"):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    paths, orig_names = [], []
    for idx_num, src_path in enumerate(saved_files, 1):
        base_name = os.path.basename(src_path)
        dst = os.path.join(out_dir, f"img_{idx_num:03d}.jpg")
        im = Image.open(src_path).convert("RGB")
        im.save(dst, format="JPEG", quality=95)
        paths.append(dst)
        orig_names.append(base_name)
    return paths, orig_names


def _stamp_image_for_api(img_path, page_num):
    from PIL import Image, ImageDraw
    im = Image.open(img_path).convert("RGB")
    max_dim = 1600
    if max(im.width, im.height) > max_dim:
        scale = max_dim / float(max(im.width, im.height))
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)

    banner_h = 34
    new_w = max(im.width, 240)
    canvas = Image.new("RGB", (new_w, im.height + banner_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (new_w, banner_h - 2)], fill=(30, 107, 87))
    label = f"PAGE {page_num}"
    draw.text((12, 9), label, fill=(255, 255, 255))
    draw.text((new_w // 2 - 24, 9), label, fill=(255, 255, 255))

    canvas.paste(im, ((new_w - im.width) // 2, banner_h))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ------------------------------------------------------------- استخراج النصوص من الصور
_KEY_MODE_CACHE = {}


def _collect_keys(extra_keys=None):
    """يجمع المفاتيح من st.secrets أو متغيرات البيئة أو القائمة المدمجة بالترتيب."""
    keys = []
    def _add(val):
        if not val:
            return
        if isinstance(val, str):
            for line in re.split(r"[\s,]+", val.strip()):
                if line and line not in keys:
                    keys.append(line)
        elif isinstance(val, (list, tuple)):
            for item in val:
                _add(item)
        elif isinstance(val, dict):
            for v in val.values():
                _add(v)

    _add(extra_keys)
    try:
        import streamlit as st
        for k_name in ("API_KEYS", "GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"):
            if k_name in st.secrets:
                _add(st.secrets[k_name])
        for v in st.secrets.values():
            if isinstance(v, str) and (v.startswith("AQ.") or v.startswith("AIza")):
                _add(v)
    except Exception:
        pass

    for env_k in ("API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        _add(os.environ.get(env_k))

    _add(DEFAULT_API_KEYS)
    return keys


def _get_system_instruction(prompt_path="prompt.txt"):
    if prompt_path and os.path.exists(prompt_path):
        try:
            with open(prompt_path, encoding="utf-8") as f:
                txt = f.read().strip()
            if txt:
                return txt
        except Exception:
            pass
    return DEFAULT_SYSTEM_INSTRUCTION


def _call_gemini_sdk(api_key, model_name, batch_items, system_instruction, use_vertex=False):
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, api_key=api_key) if use_vertex else genai.Client(api_key=api_key)
    contents = []
    for page_num, img_bytes in batch_items:
        contents.append(f"=== PAGE {page_num} ===")
        contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

    first_p, last_p = batch_items[0][0], batch_items[-1][0]
    contents.append(
        f"Read all {len(batch_items)} images above in exact order from page {first_p} to page {last_p}. "
        f"Return the JSON object with 'results' where each item has its exact 'page' number ({first_p}..{last_p})."
    )

    t_cfg = (
        types.ThinkingConfig(thinking_budget=8192)
        if model_name.startswith("gemini-2.5")
        else types.ThinkingConfig(thinking_level="high")
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        thinking_config=t_cfg,
    )

    resp = client.models.generate_content(model=model_name, contents=contents, config=config)
    if resp and resp.text:
        return resp.text
    raise RuntimeError("Empty response")


def _call_gemini_rest(api_key, model_name, batch_items, system_instruction, use_vertex=False):
    parts = []
    for page_num, img_bytes in batch_items:
        parts.append({"text": f"=== PAGE {page_num} ==="})
        parts.append({
            "inlineData": {
                "mimeType": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("ascii"),
            }
        })

    first_p, last_p = batch_items[0][0], batch_items[-1][0]
    parts.append({
        "text": (
            f"Read all {len(batch_items)} images above in exact order from page {first_p} to page {last_p}. "
            f"Return the JSON object with 'results' where each item has its exact 'page' number ({first_p}..{last_p})."
        )
    })

    thinking_cfg = {"thinkingBudget": 8192} if model_name.startswith("gemini-2.5") else {"thinkingLevel": "HIGH"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "thinkingConfig": thinking_cfg,
        },
    }

    url = (
        f"https://aiplatform.googleapis.com/v1beta1/publishers/google/models/{model_name}:generateContent"
        if use_vertex
        else f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("No candidates")
    for part in candidates[0].get("content", {}).get("parts") or []:
        if not part.get("thought") and part.get("text"):
            return part["text"]
    raise RuntimeError("No text part")


def _invoke_single_batch(batch_items, api_keys, system_instruction):
    last_err = None
    for model_name in FALLBACK_MODELS:
        for key_idx, key in enumerate(api_keys, 1):
            if key in _KEY_MODE_CACHE:
                modes = [_KEY_MODE_CACHE[key]]
            else:
                modes = [True, False] if key.startswith("AQ.") else [False, True]
            for use_vertex in modes:
                try:
                    try:
                        raw_json = _call_gemini_sdk(key, model_name, batch_items, system_instruction, use_vertex=use_vertex)
                    except ImportError:
                        raw_json = _call_gemini_rest(key, model_name, batch_items, system_instruction, use_vertex=use_vertex)
                    _KEY_MODE_CACHE[key] = use_vertex
                    return raw_json
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str.upper():
                        break
                    continue
    raise RuntimeError("تعذر معالجة الصور حالياً، يرجى المحاولة مرة أخرى.")


def read_images_with_gemini(image_paths, api_keys=None, prompt_path="prompt.txt", batch_size=15, progress_cb=None):
    if not image_paths:
        raise ValueError("لا توجد صور لمعالجتها.")

    keys = _collect_keys(api_keys)
    if not keys:
        raise RuntimeError("إعدادات الخدمة غير مكتملة.")

    system_instruction = _get_system_instruction(prompt_path)
    stamped_all = [(i, _stamp_image_for_api(p, i)) for i, p in enumerate(image_paths, 1)]

    all_results = []
    total_batches = (len(stamped_all) + batch_size - 1) // batch_size

    for b_idx in range(total_batches):
        batch = stamped_all[b_idx * batch_size : (b_idx + 1) * batch_size]
        if progress_cb:
            progress_cb(b_idx + 1, total_batches, batch[0][0], batch[-1][0])
        raw_batch_json = _invoke_single_batch(batch, keys, system_instruction)
        parsed = json.loads(re.sub(r"^```(?:json)?|```$", "", raw_batch_json.strip(), flags=re.M).strip())
        batch_list = _unwrap(parsed)
        if isinstance(batch_list, list):
            all_results.extend(batch_list)

    return json.dumps({"results": all_results}, ensure_ascii=False, indent=2)


# ------------------------------------------------------------- ربط القراءات بالصور
_WRAP_KEYS = ("results", "response", "result", "output", "images", "items", "data", "pages", "readings", "content", "text")


def _unwrap(data, depth=0):
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


def parse_readings(raw, image_paths=(), orig_names=()):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"[\[{]", raw)
    if m:
        raw = raw[m.start():]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("حدث خطأ أثناء قراءة البيانات المستخرجة.")

    data = _unwrap(data)
    if isinstance(data, dict):
        data = [{"file": k, "text": v} for k, v in data.items()]
    if not isinstance(data, list):
        raise ValueError("صيغة البيانات غير متوقعة.")

    image_paths = list(image_paths)
    orig_names = list(orig_names)

    by_page = {}
    unassigned = []
    for n, d in enumerate(data, 1):
        if isinstance(d, str):
            d = {"text": d, "page": n}
        p_num = d.get("page") or d.get("index") or d.get("order")
        try:
            p_num = int(p_num)
        except Exception:
            p_num = None
        if p_num is not None and p_num not in by_page:
            by_page[p_num] = d
        else:
            unassigned.append(d)

    total_count = len(image_paths) if image_paths else max(len(data), max(by_page.keys(), default=0))
    items = []

    for page_num in range(1, total_count + 1):
        d = by_page.get(page_num)
        if d is None and unassigned:
            d = unassigned.pop(0)
        if d is None:
            d = {"page": page_num, "text": "", "alternatives": [], "uncertain_words": [], "confidence": "low"}

        file_hint = str(d.get("file") or d.get("filename") or d.get("name") or "")
        display_name = (
            orig_names[page_num - 1]
            if page_num <= len(orig_names) and orig_names[page_num - 1]
            else (file_hint or f"image_{page_num}")
        )
        img_path = image_paths[page_num - 1] if page_num <= len(image_paths) else None

        alts = d.get("alternatives") or d.get("alts") or []
        if isinstance(alts, str):
            alts = [alts]
        uncertain = d.get("uncertain_words") or []
        if isinstance(uncertain, str):
            uncertain = [uncertain]

        items.append({
            "number": page_num,
            "name": display_name,
            "path": img_path,
            "reading": str(d.get("text") or d.get("reading") or "").strip(),
            "alts": [str(a).strip() for a in alts if str(a).strip()],
            "confidence": str(d.get("confidence") or "").lower(),
            "uncertain": [str(u).strip() for u in uncertain if str(u).strip()],
            "notes": [],
        })

    return items


# ------------------------------------------------------------- التحليل
def _adj(g):
    return g["score"] + g["bonus"]


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
            it["notes"].append("🔴 قراءة غير موثوقة: المرشحات ضعيفة ومتقاربة، راجع الصورة أو استخدم البحث اليدوي.")
        if it["confidence"] in ("low", "منخفض") and it["status"] == "AUTO":
            it["status"] = "REVIEW"
            it["notes"].append("🟡 الخط في الصورة غير واضح بالكامل — يُنصح بمراجعة الصورة.")
        if it["uncertain"]:
            it["notes"].append("❓ كلمات غير واضحة في المخطوطة: " + "، ".join(map(str, it["uncertain"])))
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
    return f"data:image/{_mime(path)};base64," + base64.b64encode(open(path, "rb").read()).decode()


FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;800'
             '&family=Noto+Naskh+Arabic:wght@400;600;700'
             '&family=Noto+Nastaliq+Urdu:wght@400;600;700&display=swap" rel="stylesheet">')
FONT_STACK = "'Vazirmatn','Noto Naskh Arabic','Segoe UI',Tahoma,sans-serif"
POEM_STACK = "'Noto Nastaliq Urdu','Vazirmatn','Noto Naskh Arabic',serif"


def _couplet_pair(couplet, matched=None):
    if not couplet:
        return []
    if len(couplet) > 2:
        mc = clean(matched or "")
        if mc and any(clean(t) == mc for t in couplet[-2:]):
            return couplet[-2:]
    return couplet[:2]


def beyt_html(couplet, matched=None):
    esc = _html.escape
    pair = _couplet_pair(couplet, matched)
    if len(pair) < 2:
        return ""
    mc = clean(matched or "")
    parts = [f'<span class="{"hem match" if mc and clean(t) == mc else "hem"}">{esc(t)}</span>' for t in pair]
    return f'<div class="beyt" dir="rtl">{parts[0]}<span class="sep">◆</span>{parts[1]}</div>'


def render_html(items):
    esc = _html.escape
    css = (
        ":root{--bg:#f6f2e8;--card:#fffdf8;--card-2:#fbf7ee;--text:#26231d;--muted:#777064;--line:#e5ddca;"
        "--green:#1e6b57;--green-2:#154f41;--green-soft:#e8f1ec;--gold:#b78e3c;--gold-soft:#f6ecd2;"
        "--hem:#f0ead9;--match:#f8e6a8;--link:#1e6b57;--thead:#f3ecdc}"
        "*{box-sizing:border-box}body{margin:0;padding:24px 14px;background:var(--bg);color:var(--text);"
        f"font-family:{FONT_STACK};line-height:1.8}}.wrap{{max-width:900px;margin:auto}}"
        ".hero{text-align:center;padding:4px 8px 18px;border-bottom:1px solid var(--line);margin-bottom:18px}"
        ".tablebox{overflow-x:auto;margin:18px 0}table{border-collapse:collapse;width:100%;background:var(--card);"
        "font-size:.88rem;border:1px solid var(--line);border-radius:12px;overflow:hidden}"
        "th,td{border-bottom:1px solid var(--line);padding:8px 12px;text-align:right}th{background:var(--thead)}"
        ".card{background:var(--card);border-radius:16px;padding:16px;margin:16px 0;border:1px solid var(--line)}"
        ".head{display:flex;gap:10px;align-items:center;margin-bottom:8px}"
        ".num{display:inline-grid;place-items:center;min-width:30px;height:30px;padding:0 7px;border-radius:8px;"
        "background:var(--green-soft);color:var(--green-2);font-weight:800}"
        ".fname{color:var(--muted);font-size:.85rem}.badge{color:#fff;border-radius:999px;padding:2px 12px;"
        "font-size:.8rem;font-weight:700;margin-inline-start:auto}"
        ".card img{display:block;margin:10px auto;max-width:100%;max-height:240px;border:1px solid var(--line);border-radius:10px}"
        ".read{background:var(--card-2);border:1px dashed var(--line);border-radius:10px;padding:8px 12px;margin:8px 0}"
        f".read .rt{{font-family:{POEM_STACK};font-size:1.15rem;line-height:2.3;color:var(--text)}}"
        ".cand{border:1px solid var(--line);border-right:4px solid var(--line);background:var(--card-2);"
        "padding:10px 14px;margin:10px 0;border-radius:12px}.cand.main{border-right-color:var(--green)}"
        ".cand-head{display:flex;justify-content:space-between;margin-bottom:4px}.c-title{font-weight:800}"
        f".verse,.beyt{{font-family:{POEM_STACK};font-size:1.2rem;line-height:2.4}}"
        ".beyt{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:4px 12px;margin:4px 0}"
        ".hem{background:var(--hem);padding:2px 10px;border-radius:8px;text-align:center}.hem.match{background:var(--match)}"
        ".sep{color:var(--gold);font-size:.65rem}.det,.note{font-size:.85rem;color:var(--muted)}"
        ".note.warn{background:var(--gold-soft);color:var(--text);padding:6px 10px;border-radius:8px}"
        "a{color:var(--link);text-decoration:none}bdi.l{unicode-bidi:isolate;direction:ltr}"
    )
    rows = "".join(
        f"<tr><td><bdi class='l'>{it['number']}</bdi></td><td><bdi class='l'>{esc(it['name'])}</bdi></td>"
        f"<td>{esc(BADGE[it['status']][0])}</td>"
        f"<td>{esc(_where(it['tops'][0]['entry']['refs'][0])) if it['tops'] else '—'}</td></tr>" for it in items)
    cards = []
    for it in items:
        label, color = BADGE[it["status"]]
        pill = label.replace("🟢", "").replace("🟡", "").replace("🔴", "").strip()
        c = [f'<div class="card"><div class="head"><span class="num"><bdi class="l">{it["number"]}</bdi></span>'
             f'<span class="fname"><bdi class="l">{esc(it["name"])}</bdi></span>'
             f'<span class="badge" style="background:{color}">{esc(pill)}</span></div>']
        if it["path"] and os.path.exists(it["path"]):
            c.append(f'<img src="{_img_src(it["path"])}" alt="">')
        c.append('<div class="read"><strong>النص المستخرج من الصورة:</strong>'
                 f'<div class="rt" dir="rtl">{esc(it["reading"] or "—")}</div>'
                 + ("<div>قراءات محتملة أخرى: " + " / ".join(f'<span dir="rtl">{esc(a)}</span>' for a in it["alts"]) + "</div>"
                    if it["alts"] else "") + "</div>")
        for k, g in enumerate(it["tops"]):
            e, r = g["entry"], g["entry"]["refs"][0]
            title = f"مرشح ضعيف {k+1}" if it["status"] == "WEAK" else ("الأقرب" if k == 0 else f"البديل {k}")
            score = f'<bdi class="l">{g["score"]:.1f}%</bdi>'
            if g["bonus"]:
                score += f' <span class="bonus">+{g["bonus"]:.1f} دعم القصيدة</span>'
            full = idx.couplets.get((r["url"], r["beyt_no"]), [])
            verse = "" if full else f'<div class="verse" dir="rtl">{esc(e["text"])}</div>'
            det = [_where(r)] + [f"نفس السطر أيضاً في: {_where(x)}" for x in (e["refs"][1:] + g["extra"])[:4]]
            c.append(f'<div class="cand{" main" if k == 0 else ""}">'
                     f'<div class="cand-head"><span class="c-title">{esc(title)}</span>'
                     f'<span class="score">تطابق {score}</span></div>'
                     + verse + beyt_html(full, e["text"])
                     + "".join(f'<div class="det" dir="rtl">{esc(d)}</div>' for d in det)
                     + f'<div class="det"><a href="{esc(r["url"])}" target="_blank">فتح في گنجور ↗</a></div></div>')
        if it["status"] in ("REVIEW", "WEAK") and it["tops"]:
            c.append(f'<div class="note warn">⚠️ الفرق بين الأول والثاني <bdi class="l">{it["margin"]:.1f}</bdi> نقطة — راجع الصورة.</div>')
        c += [f'<div class="note">{esc(n)}</div>' for n in it["notes"]]
        c.append("</div>")
        cards.append("".join(c))
    n_rev = sum(1 for it in items if it["status"] != "AUTO")
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>نتائج مطابقة الأبيات</title>'
            f'{FONT_LINK}<style>{css}</style></head><body><div class="wrap">'
            '<div class="hero"><h1>نتائج مطابقة الأبيات</h1>'
            f'<p>عدد الصور <bdi class="l">{len(items)}</bdi> · تحتاج مراجعة <bdi class="l">{n_rev}</bdi></p></div>'
            f'<div class="tablebox"><table><tr><th>#</th><th>الصورة</th><th>الحالة</th><th>الأقرب</th></tr>{rows}</table></div>'
            f'{"".join(cards)}</div></body></html>')