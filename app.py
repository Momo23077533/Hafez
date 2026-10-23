# -*- coding: utf-8 -*-
"""واجهة الموقع (Streamlit) — رفع الصور مباشرةً والقراءة والمطابقة التلقائية بضغطة زر."""
import os, tempfile, html, re, unicodedata
import streamlit as st
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

_PERSIAN_AR = str.maketrans({
    "ک": "ك", "ڪ": "ك",
    "ی": "ي", "ے": "ي", "ې": "ي", "ۍ": "ي", "ۓ": "ي",
    "ہ": "ه", "ھ": "ه", "ۀ": "ه", "ۂ": "ه",
    "ۃ": "ة", "ٱ": "ا",
    "پ": "ب", "چ": "ج", "ژ": "ز", "گ": "ك", "ڤ": "ف", "ڨ": "ف", "ڭ": "ك",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_INVISIBLES = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"),
    None,
)


def _arabic_copy(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.translate(_PERSIAN_AR).translate(_INVISIBLES)
    text = _DIACRITICS.sub("", text).replace("\u0640", "")
    return re.sub(r"\s+", " ", text).strip()


def _matched_hemistich(full, matched_text):
    mc = engine.clean(matched_text or "")
    if full and mc:
        for t in full:
            if engine.clean(t) == mc:
                return t
    return matched_text or (full[0] if full else "")


st.set_page_config(page_title="مطابقة أبيات حافظ", page_icon="📜", layout="centered",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800&family=Noto+Naskh+Arabic:wght@400;500;600;700&family=Noto+Nastaliq+Urdu:wght@400;500;600;700&display=swap');
:root{
  --paper:#f6f2e8;--card:#fffdf8;--card-2:#fbf7ee;--ink:#26231d;--muted:#777064;
  --line:#e5ddca;--green:#1e6b57;--green-2:#154f41;--green-soft:#e8f1ec;
  --gold:#b78e3c;--gold-soft:#f6ecd2;--shadow:0 22px 50px -42px rgba(62,46,18,.55);
}
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"]{direction:rtl;}
html,body,.stApp{background:var(--paper);color:var(--ink);}
.stApp{
  background:radial-gradient(1100px 520px at 100% -8%,#eee3cb 0%,rgba(238,227,203,0) 60%),
             radial-gradient(900px 520px at -10% 105%,#e6eee7 0%,rgba(230,238,231,0) 58%),var(--paper) !important;
  font-family:'Vazirmatn','Noto Naskh Arabic','Segoe UI',Tahoma,sans-serif;text-align:right;
}
[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stHeader"]{background:transparent !important;}
[data-testid="stToolbar"],#MainMenu,footer,[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none !important;}
[data-testid="stMainBlockContainer"],.block-container{max-width:900px;padding:2.4rem 1.25rem 4rem;}
[data-testid="stMarkdownContainer"]{direction:rtl;text-align:right;}
[data-testid="stMarkdownContainer"] .verse,[data-testid="stMarkdownContainer"] .beyt,
[data-testid="stMarkdownContainer"] .beyt *,[data-testid="stMarkdownContainer"] .reading-text,
[data-testid="stMarkdownContainer"] .hero-kicker{font-family:'Noto Nastaliq Urdu','Vazirmatn','Noto Naskh Arabic',serif !important;}
.hero{position:relative;text-align:center;padding:.4rem .5rem 1.5rem;margin:0 0 .6rem;}
.hero-orn{color:var(--gold);font-size:1.2rem;margin-bottom:.5rem;}
.hero-kicker{display:inline-block;font-size:1rem;line-height:2;color:var(--gold);}
.hero h1{font-size:clamp(1.85rem,4.6vw,2.5rem);font-weight:800;margin:.1rem 0 .5rem;text-align:center;}
.hero p{max-width:650px;margin:0 auto;color:var(--muted);line-height:1.9;font-size:.96rem;text-align:center;}
.hero::after{content:"";position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:min(230px,65%);height:1px;
  background:linear-gradient(90deg,transparent,var(--gold),transparent);}
.step{display:flex;align-items:center;gap:.75rem;margin:0 0 .85rem;}
.step-num{flex:0 0 auto;width:2.15rem;height:2.15rem;display:grid;place-items:center;border-radius:50%;
  background:var(--green-soft);border:1px solid rgba(30,107,87,.18);color:var(--green-2);font-weight:800;font-size:.95rem;}
.step-title{font-size:1.08rem;font-weight:800;color:var(--ink);}
.step-hint{font-size:.82rem;color:var(--muted);margin-top:.1rem;}
.st-key-step_upload,.st-key-step_run,.st-key-step_direct,[class*="st-key-result_"]{
  background:var(--card) !important;border:1px solid var(--line) !important;border-radius:18px !important;
  padding:1.1rem 1.15rem 1.25rem !important;box-shadow:var(--shadow);margin-bottom:.65rem;
}
[data-testid="stFileUploaderDropzone"]{
  background:var(--card-2) !important;border:1.5px dashed var(--line) !important;border-radius:14px !important;padding:1.1rem !important;
}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button{border-radius:12px !important;font-weight:700 !important;min-height:2.85rem;}
[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,var(--green) 0%,var(--green-2) 100%) !important;border:0 !important;color:#fff !important;
}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.85rem;margin:.5rem 0 1rem;}
.stat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:.8rem 1rem;box-shadow:var(--shadow);}
.stat-label{display:flex;align-items:center;gap:.4rem;font-size:.84rem;font-weight:600;color:var(--muted);}
.stat-value{font-size:1.6rem;font-weight:800;color:var(--green-2);}
.dot{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;}
.dot-green{background:#2e9b63;}.dot-gold{background:#d7a52a;}
[data-testid="stImage"]{display:flex;justify-content:center;max-width:100%;}
[data-testid="stImage"] img{border-radius:14px;border:1px solid var(--line);max-width:100%;height:auto;}
.res-head{display:flex;align-items:center;gap:.65rem;flex-wrap:wrap;margin:0 0 .55rem;}
.res-num{display:inline-grid;place-items:center;min-width:2.1rem;height:2.1rem;padding:0 .5rem;border-radius:10px;
  background:var(--green-soft);color:var(--green-2);font-weight:800;font-size:.95rem;}
.res-file{color:var(--muted);font-size:.85rem;direction:ltr;unicode-bidi:isolate;}
.pill{color:#fff;border-radius:999px;padding:.12rem .7rem;font-size:.8rem;font-weight:700;margin-inline-start:auto;}
.ai-read-box{background:var(--card-2);border:1px dashed var(--line);border-radius:12px;padding:.55rem .9rem;margin:.55rem 0;}
.ai-read-label{font-size:.76rem;font-weight:700;color:var(--gold);}
.reading-text{font-size:1.15rem;line-height:2.3;color:var(--ink);}
[class*="st-key-cand_top_"],[class*="st-key-cand_alt_"]{position:relative;}
[class*="st-key-copy_top_"],[class*="st-key-copy_alt_"]{position:absolute;bottom:1.7rem;left:1rem;height:1.9rem;margin:0;padding:0;z-index:3;}
[class*="st-key-copy_top_"]{width:72px;}[class*="st-key-copy_alt_"]{width:30px;}
[class*="st-key-copy_top_"] [data-testid="stCode"],[class*="st-key-copy_alt_"] [data-testid="stCode"]{
  background:transparent !important;border:0 !important;padding:0 !important;margin:0 !important;width:100% !important;height:1.9rem !important;overflow:visible !important;
}
[class*="st-key-copy_top_"] [data-testid="stCode"] pre,[class*="st-key-copy_alt_"] [data-testid="stCode"] pre{display:none !important;}
[class*="st-key-copy_top_"] [data-testid="stCode"] > div:last-child,[class*="st-key-copy_alt_"] [data-testid="stCode"] > div:last-child{
  top:0 !important;left:0 !important;right:auto !important;visibility:visible !important;opacity:1 !important;
}
[class*="st-key-copy_top_"] [data-testid="stCode"] button,[class*="st-key-copy_alt_"] [data-testid="stCode"] button{
  display:flex;align-items:center;justify-content:center;gap:.35rem;visibility:visible !important;opacity:1 !important;
  width:1.9rem;height:1.9rem;padding:0;color:var(--green-2);background:var(--card);border:1px solid var(--line);border-radius:8px;
}
[class*="st-key-copy_top_"] [data-testid="stCode"] button{width:72px;padding:0 .6rem;color:#fff;background:var(--green);border-color:transparent;}
[class*="st-key-copy_top_"] [data-testid="stCode"] button::after{content:"نسخ";font-size:.78rem;font-weight:700;}
.cand{border:1px solid var(--line);border-right:4px solid var(--line);background:var(--card-2);border-radius:12px;padding:.8rem 1rem;margin:.7rem 0;}
.cand.main{border-right-color:var(--green);background:linear-gradient(180deg,rgba(232,241,236,.8),rgba(255,253,248,.55));}
.cand-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;margin-bottom:.15rem;}
.cand-title{font-weight:800;color:var(--ink);font-size:.95rem;}
.score{font-size:.82rem;color:var(--muted);}.bonus{color:var(--green);font-weight:600;}
.mtype{display:inline-block;background:var(--gold-soft);color:#6e5015;border-radius:999px;padding:.05rem .55rem;font-size:.74rem;font-weight:700;margin-inline-start:.35rem;}
.verse{font-size:clamp(1.15rem,2.4vw,1.4rem);line-height:2.5;text-align:center;padding:.35rem 0;color:var(--ink);}
.beyt{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:.15rem .9rem;margin:.1rem 0 .35rem;font-size:clamp(1.05rem,2.2vw,1.3rem);line-height:2.45;}
.hem{background:var(--hem,#f0ead9);padding:.15rem .55rem;border-radius:8px;text-align:center;}
.hem.match{background:var(--match,#f8e6a8);}
.sep{color:var(--gold);font-size:.65rem;}.meta{font-size:.84rem;color:var(--muted);line-height:1.8;}
.cand-link{width:max-content;margin-inline-end:auto;margin-top:.25rem;font-size:.87rem;}
.cand-link a{color:var(--green);font-weight:700;text-decoration:none;border-bottom:1px dotted rgba(30,107,87,.45);}
.note{font-size:.85rem;color:var(--muted);margin:.3rem 0 .1rem;}.note.warn{background:#fbe9e7;color:#7a221c;border-radius:10px;padding:.5rem .75rem;margin:.45rem 0;}
.sub-sec-title{font-size:1.05rem;font-weight:800;color:var(--green-2);margin:.9rem 0 .35rem;}
.footer{text-align:center;color:var(--muted);font-size:.78rem;margin-top:2.6rem;}
bdi.l{direction:ltr;unicode-bidi:isolate;}
@media(max-width:640px){.beyt{grid-template-columns:1fr;gap:.1rem;}.beyt .sep{display:none;}}
</style>
""", unsafe_allow_html=True)


def step(num, title, hint=""):
    hint_html = f'<div class="step-hint">{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="step"><span class="step-num">{num}</span>'
        f'<div><div class="step-title">{title}</div>{hint_html}</div></div>',
        unsafe_allow_html=True,
    )


def render_candidate_card(g, title, cand_key, copy_key, is_main=False):
    e, r = g["entry"], g["entry"]["refs"][0]
    score = f'<bdi class="l">{g["score"]:.1f}%</bdi>'
    if g.get("bonus"):
        score += f' <span class="bonus"><bdi class="l">+{g["bonus"]:.1f}</bdi> دعم القصيدة</span>'
    mtype_html = f'<span class="mtype">{html.escape(g["match_type"])}</span>' if g.get("match_type") else ""
    full = engine.idx.couplets.get((r["url"], r["beyt_no"]), [])
    pair = engine._couplet_pair(full, e["text"])
    verse = "" if len(pair) >= 2 else f'<div class="verse" dir="rtl">{html.escape(e["text"])}</div>'
    extra = [f"نفس السطر أيضاً في: {engine._where(x)}" for x in (e["refs"][1:] + g.get("extra", []))[:4]]
    matched_part = _matched_hemistich(pair, e["text"])
    copy_text = _arabic_copy(matched_part)
    with st.container(key=cand_key):
        st.markdown(
            f'<div class="cand{" main" if is_main else ""}">'
            f'<div class="cand-head"><span class="cand-title">{html.escape(title)}{mtype_html}</span>'
            f'<span class="score">تطابق {score}</span></div>'
            + verse
            + engine.beyt_html(pair, e["text"])
            + f'<div class="meta" dir="rtl">{html.escape(engine._where(r))}</div>'
            + "".join(f'<div class="meta" dir="rtl">{html.escape(x)}</div>' for x in extra)
            + f'<div class="cand-link"><a href="{html.escape(r["url"])}" target="_blank" rel="noopener">'
            'فتح في گنجور ↗</a></div></div>',
            unsafe_allow_html=True,
        )
        with st.container(key=copy_key):
            st.code(copy_text, language=None)


st.markdown(
    '<div class="hero"><div class="hero-orn">❖</div>'
    '<div class="hero-kicker">دیوانِ حافظ · سلمانِ ساوجی</div>'
    '<h1>مطابقة أنصاف الأبيات بالذكاء الاصطناعي</h1>'
    '<p>ارفع صور المخطوطات مباشرةً وسيقوم النموذج بقراءتها ومطابقتها تلقائياً بالترتيب مع ديوان حافظ وسلمان في گنجور.</p>'
    '</div>',
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="⏳ تجهيز فهرس گنجور... (أول مرة فقط)")
def get_index():
    return engine.load_index()


try:
    get_index()
except Exception as e:
    st.error(f"❌ مشكلة في تجهيز البيانات:\n\n{e}")
    st.stop()


with st.container(border=True, key="step_upload"):
    step("١", "ارفع صور المخطوطات مباشرةً", "ارفع صورة واحدة أو عدة صور معاً — سيتم حفظها وعرض نتائجها بنفس ترتيب رفعها بالضبط بدون أي قص.")
    files = st.file_uploader(
        "الصور",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if files:
        st.caption(f"✅ تم اختيار {len(files)} صورة بالترتيب: " + " ، ".join(f"({i}) {f.name}" for i, f in enumerate(files, 1)))


with st.container(border=True, key="step_run"):
    step("٢", "قراءة الصور والمطابقة التلقائية", "يعمل تلقائياً بنموذج Gemini 3.5 Flash-Lite (بمستوى تفكير High) مع ربط كل صورة بقراءتها.")

    with st.expander("⚙️ خيارات متقدمة (إدخال JSON يدوي أو مفتاح إضافي - اختياري)"):
        custom_key = st.text_input("مفتاح API إضافي (اختياري — المفاتيح الأساسية مدمجة بالفعل)", type="password")
        manual_json_text = st.text_area(
            "أو الصق JSON خارجي هنا (اتركه فارغاً للقراءة التلقائية بالذكاء الاصطناعي)",
            height=130,
            placeholder='{"results": [{"page": 1, "text": "...", "alternatives": [], "uncertain_words": [], "confidence": "high"}]}',
        )

    if st.button("✨ ابدأ القراءة والمطابقة التلقائية", type="primary", use_container_width=True):
        if not files:
            st.warning("⚠️ ارفع صورة واحدة على الأقل الأول.")
        else:
            tmp = tempfile.mkdtemp(prefix="hafez_imgs_")
            saved = []
            for idx_f, f in enumerate(files, 1):
                p = os.path.join(tmp, f"{idx_f:03d}_{f.name}")
                with open(p, "wb") as out:
                    out.write(f.getbuffer())
                saved.append(p)

            orig_names = [f.name for f in files]
            try:
                paths, _ = engine.prepare_uploaded_images(saved, out_dir=os.path.join(tmp, "ready"))
                if manual_json_text.strip():
                    with st.spinner("⏳ جاري تحليل الـ JSON المدخل ومطابقة الأبيات..."):
                        raw_json = manual_json_text.strip()
                        readings = engine.parse_readings(raw_json, paths, orig_names)
                        st.session_state["items"] = engine.analyze(readings)
                        st.session_state["last_json"] = raw_json
                else:
                    status_box = st.empty()
                    def _prog(b_idx, total_b, p_start, p_end):
                        status_box.info(f"🤖 جاري قراءة الصور ({p_start} إلى {p_end}) عبر Gemini 3.5 Flash-Lite (Thinking: High)...")

                    with st.spinner("⏳ جاري قراءة المخطوطات بالذكاء الاصطناعي ومطابقتها مع گنجور..."):
                        raw_json = engine.read_images_with_gemini(
                            paths,
                            api_keys=custom_key.strip() if custom_key.strip() else None,
                            prompt_path=os.path.join(HERE, "prompt.txt"),
                            progress_cb=_prog,
                        )
                        status_box.empty()
                        readings = engine.parse_readings(raw_json, paths, orig_names)
                        st.session_state["items"] = engine.analyze(readings)
                        st.session_state["last_json"] = raw_json
            except Exception as e:
                st.error(f"❌ حصلت مشكلة أثناء المعالجة: {e}")


with st.container(border=True, key="step_direct"):
    step(
        "🔍",
        "البحث المباشر في الداتا كلها (مراجعة يدوية)",
        "اكتب أي كلمة أو حرف شايفه في الصورة (بالعربي أو الفارسي أو بدون نقط) للبحث المباشر في ديوان حافظ وسلمان.",
    )
    sc1, sc2 = st.columns([3.2, 1])
    with sc1:
        direct_query = st.text_input(
            "نص البحث المباشر",
            placeholder="اكتب كلمة أو حرف أو جزء من البيت للبحث في الداتا كلها...",
            label_visibility="collapsed",
            key="direct_search_input",
        )
    with sc2:
        do_direct_search = st.button("بحث في الداتا", type="primary", use_container_width=True, key="btn_direct_search")

    if do_direct_search or direct_query.strip():
        q_val = direct_query.strip()
        if q_val:
            res = engine.manual_search(q_val, top_n=3, max_exact=50)
            tops, exact_matches, total_exact = res["tops"], res["exact_matches"], res["total_exact"]
            if not tops and not exact_matches:
                st.info("لا توجد نتائج مطابقة لهذا النص.")
            else:
                st.markdown(f'<div class="sub-sec-title">⭐ أقرب ٣ تطابقات لـ «{html.escape(q_val)}»</div>', unsafe_allow_html=True)
                for k, g in enumerate(tops):
                    title = "الأقرب" if k == 0 else f"البديل {k}"
                    render_candidate_card(g, title, f"cand_top_direct_{k}" if k == 0 else f"cand_alt_direct_{k}",
                                          f"copy_top_direct_{k}" if k == 0 else f"copy_alt_direct_{k}", is_main=(k == 0))
                top_cleans = {g["entry"]["clean"] for g in tops}
                extra_exacts = [g for g in exact_matches if g["entry"]["clean"] not in top_cleans]
                if exact_matches and extra_exacts:
                    with st.expander(f"📚 عرض باقي الأبيات المتطابقة ({len(extra_exacts)} نتيجة إضافية من إجمالي {total_exact})"):
                        for m_idx, g in enumerate(extra_exacts):
                            render_candidate_card(g, f"تطابق {m_idx + 1 + len(tops)}",
                                                  f"cand_top_exact_{m_idx}", f"copy_top_exact_{m_idx}", is_main=False)


items = st.session_state.get("items")
if items:
    cnt = {k: sum(1 for it in items if it["status"] == k) for k in engine.BADGE}
    n_rev = len(items) - cnt["AUTO"]
    st.markdown(
        '<div class="stats">'
        f'<div class="stat"><div class="stat-label">عدد الصور</div><div class="stat-value">{len(items)}</div></div>'
        f'<div class="stat"><div class="stat-label"><span class="dot dot-green"></span>مؤكد</div><div class="stat-value">{cnt["AUTO"]}</div></div>'
        f'<div class="stat"><div class="stat-label"><span class="dot dot-gold"></span>تحتاج مراجعة</div><div class="stat-value">{n_rev}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    d1, d2 = st.columns([1.35, 1])
    with d1:
        report = engine.render_html(items).encode("utf-8")
        st.download_button("📥 تحميل التقرير الكامل (HTML)", report, file_name="hafez_report.html",
                           mime="text/html", use_container_width=True)
    with d2:
        only_review = st.checkbox("اعرض اللي يحتاج مراجعة بس")

    if st.session_state.get("last_json"):
        with st.expander("📄 عرض الـ JSON المستخرج من Gemini"):
            st.code(st.session_state["last_json"], language="json")

    for i, it in enumerate(items):
        if only_review and it["status"] == "AUTO":
            continue
        label, color = engine.BADGE[it["status"]]
        pill_label = label.replace("🟢", "").replace("🟡", "").replace("🔴", "").strip()
        with st.container(border=True, key=f"result_{i}"):
            st.markdown(
                f'<div class="res-head"><span class="res-num">{html.escape(str(it["number"]))}</span>'
                f'<span class="res-file"><bdi class="l">{html.escape(str(it["name"]))}</bdi></span>'
                f'<span class="pill" style="background:{color}">{html.escape(pill_label)}</span></div>',
                unsafe_allow_html=True,
            )

            if it["path"] and os.path.exists(it["path"]):
                st.image(it["path"], width=460)

            alts_html = (
                '<div class="meta">بدائل مقترحة: ' + " ، ".join(html.escape(a) for a in it["alts"]) + "</div>"
                if it["alts"] else ""
            )
            st.markdown(
                '<div class="ai-read-box"><div class="ai-read-label">قراءة الذكاء الاصطناعي للصورة:</div>'
                f'<div class="reading-text" dir="rtl">{html.escape(it["reading"] or "—")}</div>{alts_html}</div>',
                unsafe_allow_html=True,
            )

            for k, g in enumerate(it["tops"]):
                title = f"مرشح ضعيف {k + 1}" if it["status"] == "WEAK" else ("الأقرب" if k == 0 else f"البديل {k}")
                cand_key = f"cand_top_{i}" if k == 0 else f"cand_alt_{i}_{k}"
                copy_key = f"copy_top_{i}" if k == 0 else f"copy_alt_{i}_{k}"
                render_candidate_card(g, title, cand_key, copy_key, is_main=(k == 0))

            if it["status"] in ("REVIEW", "WEAK") and it["tops"]:
                st.markdown(
                    f'<div class="note warn">⚠️ الفرق بين الأول والثاني <bdi class="l">{it["margin"]:.1f}</bdi> نقطة — راجع الصورة.</div>',
                    unsafe_allow_html=True,
                )
            for n in it["notes"]:
                st.markdown(f'<div class="note">{html.escape(n)}</div>', unsafe_allow_html=True)

            with st.expander("🔍 بحث يدوي مباشر لهذه الصورة (لو قراءة الـ AI غلط)"):
                row_q = st.text_input(
                    "اكتب كلمة أو حرف من الصورة",
                    placeholder="اكتب كلمة أو حرف شايفه في الصورة دي...",
                    label_visibility="collapsed",
                    key=f"row_manual_q_{i}",
                )
                if row_q.strip():
                    row_res = engine.manual_search(row_q.strip(), top_n=3, max_exact=20)
                    for rk, rg in enumerate(row_res["tops"]):
                        r_title = "الأقرب يدوياً" if rk == 0 else f"البديل اليدوي {rk}"
                        render_candidate_card(rg, r_title,
                                              f"cand_top_row_{i}_{rk}" if rk == 0 else f"cand_alt_row_{i}_{rk}",
                                              f"copy_top_row_{i}_{rk}" if rk == 0 else f"copy_alt_row_{i}_{rk}",
                                              is_main=(rk == 0))

st.markdown(
    '<div class="footer">النصوص من <a href="https://ganjoor.net" target="_blank" rel="noopener">گنجور</a> · '
    'القراءة بواسطة Gemini 3.5 Flash-Lite والمطابقة محلياً</div>',
    unsafe_allow_html=True,
)