import streamlit as st
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import plotly.graph_objects as go
import io
import requests
from sqlalchemy import create_engine, text

# ----------------- 0. OPTIMALLASHTIRILGAN BAZA ULANISHI -----------------
# O'zingizning to'liq parolingiz bilan almashtiring:
DB_URI = "postgresql+psycopg2://postgres.vgcsnlgmebbcvdpuaxpg:Vikor-metan2018@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

@st.cache_resource
def get_engine():
    return create_engine(
        DB_URI,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True
    )

engine = get_engine()

# ----------------- 1. DIZAYN VA SOZLAMALAR -----------------
st.set_page_config(page_title="Zavod ERP — Onlayn Boshqaruv", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    .main { background-color: #F8FAFC; }
    .erp-header {
        background: linear-gradient(90deg, #0F4C81 0%, #1E3A8A 100%);
        padding: 16px 24px;
        border-radius: 12px;
        color: #FFFFFF;
        font-size: 22px;
        font-weight: 700;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .stMetric {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        padding: 12px !important;
    }
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E2E8F0;
    }
</style>
""", unsafe_allow_html=True)

DEFAULT_BOT_TOKEN = "@Vikor_Planing_bot"
DEFAULT_CHAT_ID = "6517126357"

# ----------------- 2. JADVALLARNI YARATISH & KESHLANGAN SO'ROVLAR -----------------
def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS materials (
                id SERIAL PRIMARY KEY,
                plant_name TEXT,
                item_name TEXT,
                origin_type TEXT,
                unit TEXT,
                min_limit REAL,
                current_stock REAL,
                last_price REAL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS finished_goods (
                id SERIAL PRIMARY KEY,
                plant_name TEXT,
                product_name TEXT,
                unit TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_recipes (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES finished_goods(id) ON DELETE CASCADE,
                material_id INTEGER REFERENCES materials(id) ON DELETE CASCADE,
                norm_quantity REAL,
                UNIQUE(product_id, material_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_logs (
                id SERIAL PRIMARY KEY,
                plant_name TEXT,
                material_id INTEGER REFERENCES materials(id) ON DELETE CASCADE,
                action_type TEXT,
                supplier_type TEXT,
                quantity REAL,
                price_som REAL,
                operator_name TEXT,
                date_time TEXT,
                notes TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS production_output_logs (
                id SERIAL PRIMARY KEY,
                plant_name TEXT,
                product_id INTEGER REFERENCES finished_goods(id) ON DELETE CASCADE,
                produced_qty REAL,
                operator_name TEXT,
                prod_date TEXT,
                created_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS production_plans (
                id SERIAL PRIMARY KEY,
                plant_name TEXT,
                product_id INTEGER UNIQUE REFERENCES finished_goods(id) ON DELETE CASCADE,
                daily_plan REAL DEFAULT 0,
                monthly_plan REAL DEFAULT 0,
                yearly_plan REAL DEFAULT 0
            )
        """))

init_db()

# Tezlikni oshiruvchi keshli funksiyalar (60 soniya)
@st.cache_data(ttl=60)
def load_products(plant):
    with engine.connect() as conn:
        return pd.read_sql_query(text("SELECT * FROM finished_goods WHERE plant_name = :p"), conn, params={"p": plant})

@st.cache_data(ttl=60)
def load_materials(plant):
    with engine.connect() as conn:
        return pd.read_sql_query(text("SELECT * FROM materials WHERE plant_name = :p"), conn, params={"p": plant})

@st.cache_data(ttl=60)
def load_plans(plant):
    with engine.connect() as conn:
        q = text("""
            SELECT pp.product_id, fg.product_name, fg.unit, pp.daily_plan, pp.monthly_plan, pp.yearly_plan
            FROM production_plans pp
            JOIN finished_goods fg ON pp.product_id = fg.id
            WHERE pp.plant_name = :p
        """)
        return pd.read_sql_query(q, conn, params={"p": plant})

def clear_cache_and_rerun():
    st.cache_data.clear()
    st.rerun()

# Telegram va PDF
def send_telegram_file(file_bytes, filename, bot_token, chat_id, caption=""):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
        files = {'document': (filename, file_bytes)}
        data = {'chat_id': chat_id, 'caption': caption}
        r = requests.post(url, files=files, data=data)
        return r.status_code == 200
    except Exception:
        return False

def generate_pdf(df, title):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=20, leftMargin=20, topMargin=25, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(f"<b>{title}</b>", styles['Title']))
    elements.append(Paragraph(f"Sana: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 14))
    
    data = [df.columns.tolist()] + df.astype(str).values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F4C81")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
    ]))
    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    return buffer

PLANTS = {
    "Metan ishlab chiqarish zavodi": {"logo": "⛽"},
    "Propan ishlab chiqarish zavodi": {"logo": "🔥"},
    "Velosiped ishlab chiqarish zavodi": {"logo": "🚲"},
    "Boshqa ehtiyot qismlar majmuasi": {"logo": "⚙️"}
}

# ----------------- 3. CHAP PANEL -----------------
st.sidebar.markdown("### 🏢 Korxona Tanlash")
selected_plant = st.sidebar.selectbox("Faol zavod:", list(PLANTS.keys()))
p_logo = PLANTS[selected_plant]["logo"]

st.sidebar.markdown("---")
st.sidebar.markdown(f"#### 📁 {p_logo} {selected_plant}")

df_p_cached = load_products(selected_plant)
existing_prods = df_p_cached['product_name'].tolist() if not df_p_cached.empty else []

with st.sidebar.expander(f"📂 Mahsulotlar katalogi ({len(existing_prods)} ta)", expanded=True):
    if existing_prods:
        for p in existing_prods:
            st.markdown(f"└ 📦 **{p}**")
    else:
        st.caption("Katalogda mahsulotlar yo'q.")

if st.sidebar.button("🔄 Yangilash (Keshni tozalash)"):
    clear_cache_and_rerun()

st.sidebar.markdown("---")
menu = st.sidebar.radio("📋 Asosiy Bo'limlar:", [
    "🎯 Prognoz & Ishlab Chiqarish Rejasi",
    "🛠️ Tahrirlash & O'chirish (Boshqaruv)",
    "📐 1. Norma-Rasxod & Mahsulotlar (Jadval)",
    "🏭 2. Kunlik Ishlab Chiqarish & Avto-Sarf",
    "📥 3. Yangi Kirim (Xaridlar)",
    "📊 4. 24/7 Monitoring & Ombordagi Qoldiqlar",
    "⏳ 5. Logistika & Xarid Ogohlantirishi",
    "📑 6. Hisobotlar (Excel, PDF & Telegram)",
    "📈 7. Narx va Sarf Dinamikasi"
])

# -------------------------------------------------------------
# BO'LIM: PROGNOZ VA ISHLAB CHIQARISH REJASI
# -------------------------------------------------------------
if menu == "🎯 Prognoz & Ishlab Chiqarish Rejasi":
    st.markdown(f"<div class='erp-header'>🎯 {selected_plant} — Ishlab Chiqarish Rejalari va Prognoz</div>", unsafe_allow_html=True)
    
    df_p = load_products(selected_plant)
    if df_p.empty:
        st.warning("⚠️ Rejalashtirish uchun avval mahsulotlar katalogini shakllantiring.")
    else:
        with engine.begin() as conn:
            for _, prod in df_p.iterrows():
                conn.execute(text("""
                    INSERT INTO production_plans (plant_name, product_id, daily_plan, monthly_plan, yearly_plan)
                    VALUES (:plant, :pid, 0, 0, 0)
                    ON CONFLICT (product_id) DO NOTHING
                """), {"plant": selected_plant, "pid": int(prod['id'])})

        t_plans, t_analytics, t_raw_forecast = st.tabs([
            "📝 Rejalarni Kiritish / Tahrirlash",
            "📊 Reja vs Haqiqat Dinamikasi (Fact)",
            "🔮 Reja Asosida Xomashyo Ehtiyoji Prognozi"
        ])

        with t_plans:
            st.markdown("#### 🎯 Kunlik, oylik va yillik rejalarni belgilang:")
            df_plan_data = load_plans(selected_plant)
            
            edited_plans = st.data_editor(
                df_plan_data,
                column_config={
                    "product_id": st.column_config.NumberColumn("ID", disabled=True),
                    "product_name": st.column_config.TextColumn("Tayyor Mahsulot", disabled=True),
                    "unit": st.column_config.TextColumn("Birlik", disabled=True),
                    "daily_plan": st.column_config.NumberColumn("Kunlik Reja", min_value=0.0, step=1.0),
                    "monthly_plan": st.column_config.NumberColumn("Oylik Reja", min_value=0.0, step=10.0),
                    "yearly_plan": st.column_config.NumberColumn("Yillik Reja", min_value=0.0, step=100.0)
                },
                disabled=["product_id", "product_name", "unit"],
                hide_index=True,
                use_container_width=True
            )

            if st.button("💾 Barcha Rejalarni Saqlash", type="primary"):
                with engine.begin() as conn:
                    for _, r in edited_plans.iterrows():
                        conn.execute(text("""
                            UPDATE production_plans
                            SET daily_plan = :d, monthly_plan = :m, yearly_plan = :y
                            WHERE product_id = :pid
                        """), {"d": float(r['daily_plan']), "m": float(r['monthly_plan']), "y": float(r['yearly_plan']), "pid": int(r['product_id'])})
                st.success("✅ Ishlab chiqarish rejalari saqlandi!")
                clear_cache_and_rerun()

        with t_analytics:
            st.markdown("#### 📈 Rejaning amalda bajarilishi tahlili")
            now = datetime.now()
            cur_month = now.strftime("%Y-%m")
            cur_year = now.strftime("%Y")

            with engine.connect() as conn:
                prod_stats = pd.read_sql_query(text("""
                    SELECT product_id, 
                           SUM(CASE WHEN prod_date LIKE :cm THEN produced_qty ELSE 0 END) AS cur_month_fact,
                           SUM(CASE WHEN prod_date LIKE :cy THEN produced_qty ELSE 0 END) AS cur_year_fact,
                           SUM(produced_qty) AS all_time_fact
                    FROM production_output_logs
                    WHERE plant_name = :p
                    GROUP BY product_id
                """), conn, params={"cm": f"{cur_month}%", "cy": f"{cur_year}%", "p": selected_plant})

            df_plan_data = load_plans(selected_plant)
            df_plan_data['product_id'] = pd.to_numeric(df_plan_data['product_id'], errors='coerce').fillna(0).astype(int)
            prod_stats['product_id'] = pd.to_numeric(prod_stats['product_id'], errors='coerce').fillna(0).astype(int)

            df_merged_stats = pd.merge(df_plan_data, prod_stats, on="product_id", how="left").fillna(0)
            
            df_merged_stats['Oylik Bajarilish %'] = df_merged_stats.apply(
                lambda x: round((x['cur_month_fact'] / x['monthly_plan'] * 100), 1) if x['monthly_plan'] > 0 else 0.0, axis=1
            )
            df_merged_stats['Yillik Bajarilish %'] = df_merged_stats.apply(
                lambda x: round((x['cur_year_fact'] / x['yearly_plan'] * 100), 1) if x['yearly_plan'] > 0 else 0.0, axis=1
            )

            st.dataframe(
                df_merged_stats[['product_name', 'unit', 'monthly_plan', 'cur_month_fact', 'Oylik Bajarilish %', 'yearly_plan', 'cur_year_fact', 'Yillik Bajarilish %']].rename(
                    columns={
                        'product_name': 'Mahsulot', 'unit': 'Birlik',
                        'monthly_plan': 'Oylik Reja', 'cur_month_fact': 'Shu oyda ishlab chiqarildi',
                        'yearly_plan': 'Yillik Reja', 'cur_year_fact': 'Shu yilda ishlab chiqarildi'
                    }
                ),
                use_container_width=True
            )

            fig_plan = go.Figure()
            fig_plan.add_trace(go.Bar(x=df_merged_stats['product_name'], y=df_merged_stats['monthly_plan'], name='Oylik Reja', marker_color='#0F4C81'))
            fig_plan.add_trace(go.Bar(x=df_merged_stats['product_name'], y=df_merged_stats['cur_month_fact'], name='Amalda (Fakt)', marker_color='#16A34A'))
            fig_plan.update_layout(barmode='group', title=f"Oylik Reja va Haqiqiy Ishlab Chiqarish ({cur_month})")
            st.plotly_chart(fig_plan, use_container_width=True)

        with t_raw_forecast:
            st.markdown("#### 🔮 Rejani bajarish uchun zarur xomashyo ehtiyoji:")
            target_period = st.selectbox("Prognoz davrini tanlang:", ["Oylik reja asosida", "Yillik reja asosida"])
            plan_col = "monthly_plan" if target_period == "Oylik reja asosida" else "yearly_plan"

            req_query = text(f"""
                SELECT m.id AS material_id, m.item_name, m.origin_type, m.unit, m.current_stock, m.last_price,
                       SUM(r.norm_quantity * pp.{plan_col}) AS total_required
                FROM product_recipes r
                JOIN production_plans pp ON r.product_id = pp.product_id
                JOIN materials m ON r.material_id = m.id
                WHERE pp.plant_name = :p
                GROUP BY m.id, m.item_name, m.origin_type, m.unit, m.current_stock, m.last_price
            """)
            with engine.connect() as conn:
                df_forecast = pd.read_sql_query(req_query, conn, params={"p": selected_plant})

            if not df_forecast.empty:
                df_forecast['Kamomad (Sotib olish kerak)'] = (df_forecast['total_required'] - df_forecast['current_stock']).apply(lambda x: x if x > 0 else 0.0)
                df_forecast['Kerakli mablag\' (so\'m)'] = df_forecast['Kamomad (Sotib olish kerak)'] * df_forecast['last_price']

                total_budget = df_forecast['Kerakli mablag\' (so\'m)'].sum()
                c_fc1, c_fc2 = st.columns(2)
                c_fc1.metric("📦 Tanlangan davr:", target_period)
                c_fc2.metric("💰 Talab etiladigan xarid byudjeti:", f"{total_budget:,.0f} so'm")

                st.dataframe(
                    df_forecast[['item_name', 'origin_type', 'unit', 'total_required', 'current_stock', 'Kamomad (Sotib olish kerak)', 'last_price', 'Kerakli mablag\' (so\'m)']].rename(
                        columns={
                            'item_name': 'Xomashyo / Detal', 'origin_type': 'Turi', 'unit': 'Birlik',
                            'total_required': 'Reja uchun jami talab', 'current_stock': 'Omborda mavjud',
                            'last_price': 'Oxirgi narx (so\'m)'
                        }
                    ),
                    use_container_width=True
                )
            else:
                st.info("Retsepturalar yoki reja miqdorlari kiritilmagan.")

# -------------------------------------------------------------
# BO'LIM: TAHRIRLASH VA O'CHIRISH (BOSHQARUV)
# -------------------------------------------------------------
elif menu == "🛠️ Tahrirlash & O'chirish (Boshqaruv)":
    st.markdown(f"<div class='erp-header'>🛠️ {selected_plant} — Ma'lumotlarni Tahrirlash va O'chirish</div>", unsafe_allow_html=True)

    tab_mat_edit, tab_prod_edit, tab_log_edit = st.tabs([
        "🔩 Xomashyo va Narxlarni Tahrirlash / O'chirish",
        "📦 Tayyor Mahsulotlarni Tahrirlash / O'chirish",
        "📑 Kirim Tarixi va Narxlarni To'g'rilash"
    ])

    with tab_mat_edit:
        df_m = load_materials(selected_plant)
        if not df_m.empty:
            sel_m_item = st.selectbox("Tahrirlash yoki o'chirish uchun xomashyo:", df_m['item_name'].tolist(), key="sel_m_edit")
            target_mat = df_m[df_m['item_name'] == sel_m_item].iloc[0]

            with st.form("edit_mat_form"):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    new_name = st.text_input("Xomashyo nomi:", value=target_mat['item_name'])
                    new_origin = st.selectbox("Ta'minot manbai:", ["Mahalliy", "Import (Xitoy/Chet el)"], 
                                              index=0 if target_mat['origin_type'] == "Mahalliy" else 1)
                    new_unit = st.selectbox("Birligi:", ["tonna", "dona", "kg", "litr", "metr", "m3"], 
                                            index=["tonna", "dona", "kg", "litr", "metr", "m3"].index(target_mat['unit']) if target_mat['unit'] in ["tonna", "dona", "kg", "litr", "metr", "m3"] else 0)
                with col_e2:
                    new_stock = st.number_input("Ombordagi hozirgi qoldiq:", value=float(target_mat['current_stock']), step=1.0)
                    new_limit = st.number_input("Kritik chegara:", value=float(target_mat['min_limit']), step=1.0)
                    new_price = st.number_input("Joriy narxi (so'm):", value=float(target_mat['last_price']), step=1000.0)

                save_changes = st.form_submit_button("💾 Saqlash", type="primary")
                
            if save_changes:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE materials 
                        SET item_name = :name, origin_type = :org, unit = :u, min_limit = :l, current_stock = :s, last_price = :p
                        WHERE id = :id
                    """), {"name": new_name.strip(), "org": new_origin, "u": new_unit, "l": new_limit, "s": new_stock, "p": new_price, "id": int(target_mat['id'])})
                st.success(f"✅ '{new_name}' yangilandi!")
                clear_cache_and_rerun()

            st.markdown("---")
            if st.button(f"❌ '{sel_m_item}' xomashyosini o'chirish", type="secondary"):
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM materials WHERE id = :id"), {"id": int(target_mat['id'])})
                st.success(f"'{sel_m_item}' o'chirildi!")
                clear_cache_and_rerun()
        else:
            st.info("Xomashyolar mavjud emas.")

    with tab_prod_edit:
        df_p = load_products(selected_plant)
        if not df_p.empty:
            sel_p_item = st.selectbox("Tahrirlash yoki o'chirish uchun mahsulot:", df_p['product_name'].tolist(), key="sel_p_edit")
            target_prod = df_p[df_p['product_name'] == sel_p_item].iloc[0]

            with st.form("edit_prod_form"):
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    edit_p_name = st.text_input("Mahsulot nomi:", value=target_prod['product_name'])
                with col_p2:
                    edit_p_unit = st.selectbox("Birligi:", ["dona", "tonna", "komplekt"], 
                                               index=["dona", "tonna", "komplekt"].index(target_prod['unit']) if target_prod['unit'] in ["dona", "tonna", "komplekt"] else 0)
                save_p_btn = st.form_submit_button("💾 Mahsulotni Yangilash", type="primary")

            if save_p_btn:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE finished_goods SET product_name = :name, unit = :u WHERE id = :id"), 
                                 {"name": edit_p_name.strip(), "u": edit_p_unit, "id": int(target_prod['id'])})
                st.success(f"✅ Mahsulot yangilandi!")
                clear_cache_and_rerun()

            st.markdown("---")
            if st.button(f"❌ '{sel_p_item}' mahsulotini o'chirish"):
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM finished_goods WHERE id = :id"), {"id": int(target_prod['id'])})
                st.success(f"'{sel_p_item}' o'chirildi!")
                clear_cache_and_rerun()
        else:
            st.info("Mahsulotlar katalogi bo'sh.")

    with tab_log_edit:
        with engine.connect() as conn:
            logs_df = pd.read_sql_query(text("""
                SELECT sl.id, sl.date_time AS "Sana", m.item_name AS "Tovar", sl.action_type AS "Harakat", 
                       sl.quantity AS "Miqdor", sl.price_som AS "Narx (so'm)", sl.operator_name AS "Mas'ul", sl.notes AS "Izoh"
                FROM stock_logs sl
                JOIN materials m ON sl.material_id = m.id
                WHERE sl.plant_name = :p
                ORDER BY sl.id DESC LIMIT 30
            """), conn, params={"p": selected_plant})
        
        if not logs_df.empty:
            st.dataframe(logs_df, use_container_width=True)
            sel_log_id = st.selectbox("O'chirmoqchi bo'lgan amalingiz ID raqami:", logs_df['id'].tolist())
            if st.button("❌ Tanlangan amalni o'chirish"):
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM stock_logs WHERE id = :id"), {"id": int(sel_log_id)})
                st.success(f"Amal (ID: {sel_log_id}) o'chirildi!")
                clear_cache_and_rerun()
        else:
            st.info("Kirim-chiqimlar tarixi bo'sh.")

# -------------------------------------------------------------
# BO'LIM 1: NORMA-RASXOD VA MAHSULOTLAR
# -------------------------------------------------------------
elif menu == "📐 1. Norma-Rasxod & Mahsulotlar (Jadval)":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Sarf Normalari (BOM)</div>", unsafe_allow_html=True)
    
    t_recipe, t_add_prod, t_add_mat = st.tabs([
        "📋 Mahsulotga Sarf Normalarini Kiritish (Jadval)",
        "➕ Yangi Tayyor Mahsulot Ochish",
        "🔩 Yangi Xomashyo / Qism Qo'shish"
    ])
    
    with t_recipe:
        df_p = load_products(selected_plant)
        df_m = load_materials(selected_plant)
        
        if df_p.empty or df_m.empty:
            st.warning("⚠️ Norma-rasxod kiritish uchun avval mahsulot va xomashyo kiritilgan bo'lishi lozim.")
        else:
            sel_product = st.selectbox("Tayyor mahsulotni tanlang:", df_p['product_name'].tolist())
            pid = int(df_p[df_p['product_name'] == sel_product]['id'].values[0])
            
            with engine.connect() as conn:
                current_recipes = pd.read_sql_query(text("""
                    SELECT m.id as material_id, m.item_name, m.unit, r.norm_quantity
                    FROM product_recipes r
                    JOIN materials m ON r.material_id = m.id
                    WHERE r.product_id = :pid
                """), conn, params={"pid": pid})
            
            table_data = []
            for _, m_row in df_m.iterrows():
                match = current_recipes[current_recipes['material_id'] == m_row['id']]
                curr_val = float(match['norm_quantity'].values[0]) if not match.empty else 0.0
                table_data.append({
                    "Xomashyo ID": m_row['id'],
                    "Xomashyo / Detal": m_row['item_name'],
                    "O'lchov birligi": m_row['unit'],
                    "1 dona mahsulot uchun norma sarfi": curr_val
                })
            
            df_editor_source = pd.DataFrame(table_data)
            edited_recipe_df = st.data_editor(
                df_editor_source,
                column_config={
                    "Xomashyo ID": st.column_config.NumberColumn(disabled=True),
                    "Xomashyo / Detal": st.column_config.TextColumn(disabled=True),
                    "O'lchov birligi": st.column_config.TextColumn(disabled=True),
                    "1 dona mahsulot uchun norma sarfi": st.column_config.NumberColumn(min_value=0.0, format="%.5f")
                },
                disabled=["Xomashyo ID", "Xomashyo / Detal", "O'lchov birligi"],
                hide_index=True,
                use_container_width=True
            )
            
            if st.button(f"💾 '{sel_product}' Normasini Saqlash", type="primary"):
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM product_recipes WHERE product_id = :pid"), {"pid": pid})
                    for _, row in edited_recipe_df.iterrows():
                        qty = float(row['1 dona mahsulot uchun norma sarfi'])
                        if qty > 0:
                            conn.execute(text("""
                                INSERT INTO product_recipes (product_id, material_id, norm_quantity)
                                VALUES (:pid, :mid, :qty)
                            """), {"pid": pid, "mid": int(row['Xomashyo ID']), "qty": qty})
                st.success(f"✅ '{sel_product}' sarf normalari saqlandi!")
                clear_cache_and_rerun()

    with t_add_prod:
        with st.form("new_product_form"):
            new_p_name = st.text_input("Yangi Tayyor Mahsulot Nomi:")
            new_p_unit = st.selectbox("O'lchov birligi:", ["dona", "tonna", "komplekt"])
            if st.form_submit_button("Katalogga Qo'shish"):
                if new_p_name.strip():
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO finished_goods (plant_name, product_name, unit) VALUES (:p, :n, :u)"),
                                     {"p": selected_plant, "n": new_p_name.strip(), "u": new_p_unit})
                    st.success(f"'{new_p_name}' katalogga qo'shildi!")
                    clear_cache_and_rerun()

    with t_add_mat:
        with st.form("new_material_form"):
            new_m_name = st.text_input("Xomashyo nomi:")
            c_mat1, c_mat2 = st.columns(2)
            with c_mat1:
                new_m_origin = st.selectbox("Ta'minot turi:", ["Mahalliy", "Import (Xitoy/Chet el)"])
                new_m_unit = st.selectbox("Birligi:", ["tonna", "dona", "kg", "litr", "metr", "m3"])
            with c_mat2:
                new_m_min = st.number_input("Minimal chegara:", min_value=0.01, step=1.0)
                new_m_stock = st.number_input("Boshlang'ich qoldiq:", min_value=0.0, step=1.0)
                new_m_price = st.number_input("Boshlang'ich narx (so'm):", min_value=0.0, step=1000.0)
            
            if st.form_submit_button("Xomashyoni Ro'yxatga Olish"):
                if new_m_name.strip():
                    with engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO materials (plant_name, item_name, origin_type, unit, min_limit, current_stock, last_price)
                            VALUES (:p, :n, :org, :u, :min, :stk, :pr)
                        """), {"p": selected_plant, "n": new_m_name.strip(), "org": new_m_origin, "u": new_m_unit, "min": new_m_min, "stk": new_m_stock, "pr": new_m_price})
                    st.success(f"'{new_m_name}' bazaga qo'shildi!")
                    clear_cache_and_rerun()

# -------------------------------------------------------------
# BO'LIM 2: KUNLIK ISHLAB CHIQARISH VA AVTO-SARF
# -------------------------------------------------------------
elif menu == "🏭 2. Kunlik Ishlab Chiqarish & Avto-Sarf":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Ishlab Chiqarish va Sarf</div>", unsafe_allow_html=True)
    
    df_p = load_products(selected_plant)
    if not df_p.empty:
        col_form, col_preview = st.columns([1, 1])
        with col_form:
            st.markdown("#### 📝 Ishlab chiqarish hisoboti")
            with st.form("prod_submit_form"):
                prod_date_val = st.date_input("Sana:", value=date.today())
                operator_fio = st.text_input("Mas'ul (F.I.O):", placeholder="Abdullayev O.")
                target_product = st.selectbox("Mahsulot:", df_p['product_name'].tolist())
                prod_qty = st.number_input("Miqdor:", min_value=1.0, step=1.0)
                submit_btn = st.form_submit_button("Tasdiqlash va Ombordan Sarflash", type="primary")
                
        pid = int(df_p[df_p['product_name'] == target_product]['id'].values[0])
        with engine.connect() as conn:
            recipe_df = pd.read_sql_query(text("""
                SELECT m.id as mat_id, m.item_name, m.unit, m.current_stock, r.norm_quantity
                FROM product_recipes r
                JOIN materials m ON r.material_id = m.id
                WHERE r.product_id = :pid
            """), conn, params={"pid": pid})
        
        with col_preview:
            st.markdown(f"#### 🔍 1 dona '{target_product}' sarf tarkibi:")
            if not recipe_df.empty:
                preview_data = recipe_df.copy()
                preview_data['Jami sarf'] = preview_data['norm_quantity'] * prod_qty
                st.dataframe(
                    preview_data[['item_name', 'unit', 'norm_quantity', 'Jami sarf', 'current_stock']].rename(
                        columns={'item_name': 'Xomashyo', 'unit': 'Birlik', 'norm_quantity': 'Norma', 'current_stock': 'Omborda'}
                    ), use_container_width=True
                )
            else:
                st.error("⚠️ Ushbu mahsulot normasini avval 1-bo'limda kiriting!")
                
        if submit_btn:
            if not operator_fio.strip():
                st.error("Mas'ul xodim nomini yozish majburiy!")
            elif recipe_df.empty:
                st.error("Norma kiritilmagan!")
            else:
                can_proceed = True
                for _, r in recipe_df.iterrows():
                    if (r['norm_quantity'] * prod_qty) > r['current_stock']:
                        can_proceed = False
                        st.error(f"❌ Omborda yetarli emas: {r['item_name']}")
                
                if can_proceed:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with engine.begin() as conn:
                        for _, r in recipe_df.iterrows():
                            spent = float(r['norm_quantity'] * prod_qty)
                            new_balance = float(r['current_stock'] - spent)
                            conn.execute(text("UPDATE materials SET current_stock = :b WHERE id = :id"), {"b": new_balance, "id": int(r['mat_id'])})
                            conn.execute(text("""
                                INSERT INTO stock_logs (plant_name, material_id, action_type, supplier_type, quantity, price_som, operator_name, date_time, notes)
                                VALUES (:p, :mid, 'SARF', 'Ishlab chiqarish', :qty, 0, :op, :dt, :nt)
                            """), {"p": selected_plant, "mid": int(r['mat_id']), "qty": spent, "op": operator_fio, "dt": str(prod_date_val), "nt": f"{prod_qty} dona {target_product} uchun"})
                        
                        conn.execute(text("""
                            INSERT INTO production_output_logs (plant_name, product_id, produced_qty, operator_name, prod_date, created_at)
                            VALUES (:p, :pid, :qty, :op, :dt, :ca)
                        """), {"p": selected_plant, "pid": pid, "qty": float(prod_qty), "op": operator_fio, "dt": str(prod_date_val), "ca": now_str})
                    st.success(f"✅ {prod_qty} dona {target_product} qabul qilindi!")
                    clear_cache_and_rerun()
                    
        st.markdown("---")
        with engine.connect() as conn:
            logs_prod = pd.read_sql_query(text("""
                SELECT pol.prod_date AS "Sana", fg.product_name AS "Mahsulot", pol.produced_qty AS "Miqdor", 
                       fg.unit AS "Birlik", pol.operator_name AS "Mas'ul"
                FROM production_output_logs pol
                JOIN finished_goods fg ON pol.product_id = fg.id
                WHERE pol.plant_name = :p
                ORDER BY pol.id DESC LIMIT 10
            """), conn, params={"p": selected_plant})
        st.dataframe(logs_prod, use_container_width=True)
    else:
        st.info("Katalog bo'sh.")

# -------------------------------------------------------------
# BO'LIM 3: YANGI KIRIM (XARIDLAR)
# -------------------------------------------------------------
elif menu == "📥 3. Yangi Kirim (Xaridlar)":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Omborga Kirim</div>", unsafe_allow_html=True)
    
    df_m = load_materials(selected_plant)
    if not df_m.empty:
        with st.form("inflow_form"):
            c_i1, c_i2 = st.columns(2)
            with c_i1:
                item_chosen = st.selectbox("Xomashyo / Detal:", df_m['item_name'].tolist())
                source_type = st.selectbox("Ta'minot manbai:", ["Mahalliy ta'minotchi", "Import (Xitoy/Chet el)", "Boshqa ombor"])
                fio_in = st.text_input("Qabul qiluvchi mas'ul:")
            with c_i2:
                in_qty = st.number_input("Kirim miqdori:", min_value=0.001, step=1.0, format="%.4f")
                in_price = st.number_input("1 birlik xarid narxi (so'm):", min_value=0.0, step=1000.0)
                in_note = st.text_input("Invoys / Shartnoma raqami:")
                
            if st.form_submit_button("Omborga Kirimni Saqlash", type="primary"):
                mid = int(df_m[df_m['item_name'] == item_chosen]['id'].values[0])
                now_t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with engine.begin() as conn:
                    conn.execute(text("UPDATE materials SET current_stock = current_stock + :qty, last_price = :pr WHERE id = :id"),
                                 {"qty": float(in_qty), "pr": float(in_price), "id": mid})
                    conn.execute(text("""
                        INSERT INTO stock_logs (plant_name, material_id, action_type, supplier_type, quantity, price_som, operator_name, date_time, notes)
                        VALUES (:p, :mid, 'KIRIM', :src, :qty, :pr, :op, :dt, :nt)
                    """), {"p": selected_plant, "mid": mid, "src": source_type, "qty": float(in_qty), "pr": float(in_price), "op": fio_in, "dt": now_t, "nt": in_note})
                st.success(f"✅ {in_qty} miqdorda {item_chosen} qabul qilindi!")
                clear_cache_and_rerun()
    else:
        st.info("Xomashyolar ro'yxati bo'sh.")

# -------------------------------------------------------------
# BO'LIM 4: MONITORING VA BARCHA QOLDIQLAR
# -------------------------------------------------------------
elif menu == "📊 4. 24/7 Monitoring & Ombordagi Qoldiqlar":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Ombor Zaxiralari Nazorati</div>", unsafe_allow_html=True)
    
    df_m = load_materials(selected_plant)
    if not df_m.empty:
        low_stock = df_m[df_m['current_stock'] <= df_m['min_limit']]
        c1, c2, c3 = st.columns(3)
        c1.metric("Jami xomashyo turlari", f"{len(df_m)} xil")
        c2.metric("Kritik kamayganlar", f"{len(low_stock)} xil", delta=f"-{len(low_stock)}" if len(low_stock) else "0", delta_color="inverse")
        c3.metric("Baza holati", "🟢 Supabase (Kesh faol)")
        
        if not low_stock.empty:
            st.error("🚨 Zaxirasi kritik kamaygan tovarlar:")
            st.dataframe(low_stock.rename(columns={
                'item_name': 'Nomi', 'origin_type': 'Turi', 'unit': 'Birlik',
                'min_limit': 'Kritik chegara', 'current_stock': 'Qoldiq', 'last_price': 'Narx (so\'m)'
            }), use_container_width=True)
            
        st.markdown("#### 📦 Barcha xomashyolar:")
        st.dataframe(df_m.rename(columns={
            'id': 'ID', 'item_name': 'Nomi', 'origin_type': 'Turi',
            'unit': 'Birlik', 'min_limit': 'Minimal chegara', 'current_stock': 'Mavjud qoldiq', 'last_price': 'Joriy narx'
        }), use_container_width=True)
        
        fig = px.bar(df_m, x='item_name', y='current_stock', color='origin_type', title="Ombor qoldiqlari balansi")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Ombor bo'sh.")

# -------------------------------------------------------------
# BO'LIM 5: LOGISTIKA VA XARID OGOHLANTIRISHI
# -------------------------------------------------------------
elif menu == "⏳ 5. Logistika & Xarid Ogohlantirishi":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Logistika va Zaxira Muddati Tahlili</div>", unsafe_allow_html=True)
    
    df_m = load_materials(selected_plant)
    with engine.connect() as conn:
        logs_usage = pd.read_sql_query(text("""
            SELECT material_id, SUM(quantity) as total_used 
            FROM stock_logs 
            WHERE plant_name = :p AND action_type = 'SARF'
            GROUP BY material_id
        """), conn, params={"p": selected_plant})
        
    if not df_m.empty:
        df_lead = pd.merge(df_m, logs_usage, left_on='id', right_on='material_id', how='left').fillna(0)
        df_lead['kunlik_sarf'] = (df_lead['total_used'] / 30).apply(lambda x: x if x > 0 else 1.0)
        df_lead['yetish_kuni'] = (df_lead['current_stock'] / df_lead['kunlik_sarf']).round(1)
        
        def calculate_status(row):
            if row['origin_type'] == 'Import (Xitoy/Chet el)' and row['yetish_kuni'] <= 60:
                return "🚨 Zudlik bilan importga buyurtma (2 oylik xavf)"
            elif row['origin_type'] == 'Mahalliy' and row['yetish_kuni'] <= 30:
                return "⚠️ Mahalliy buyurtma berish zarur (1 oylik xavf)"
            return "✅ Yetarli zaxira"
            
        df_lead['Holat'] = df_lead.apply(calculate_status, axis=1)
        st.dataframe(df_lead[['item_name', 'origin_type', 'current_stock', 'unit', 'kunlik_sarf', 'yetish_kuni', 'Holat']].rename(
            columns={'item_name': 'Tovar', 'origin_type': 'Turi', 'current_stock': 'Qoldiq', 'kunlik_sarf': 'Kunlik o\'rtacha sarf', 'yetish_kuni': 'Necha kunga yetadi'}
        ), use_container_width=True)

# -------------------------------------------------------------
# BO'LIM 6: HISOBOTLAR (EXCEL, PDF VA TELEGRAM)
# -------------------------------------------------------------
elif menu == "📑 6. Hisobotlar (Excel, PDF & Telegram)":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Hujjatlar va Telegram Hisobot</div>", unsafe_allow_html=True)
    rep_kind = st.radio("Hisobot turi:", ["Ombor qoldiqlari ro'yxati", "Kunlik ishlab chiqarish jurnali", "Barcha kirim-chiqimlar auditi"])
    
    with engine.connect() as conn:
        if rep_kind == "Ombor qoldiqlari ro'yxati":
            df_export = pd.read_sql_query(text("""
                SELECT item_name AS "Tovar Nomi", origin_type AS "Turi", current_stock AS "Qoldiq", unit AS "Birligi", 
                       min_limit AS "Kritik Me'yor", last_price AS "Joriy Narxi (so'm)"
                FROM materials WHERE plant_name = :p
            """), conn, params={"p": selected_plant})
        elif rep_kind == "Kunlik ishlab chiqarish jurnali":
            df_export = pd.read_sql_query(text("""
                SELECT pol.prod_date AS "Sana", fg.product_name AS "Tayyor Mahsulot", pol.produced_qty AS "Miqdor", 
                       fg.unit AS "Birlik", pol.operator_name AS "Mas'ul"
                FROM production_output_logs pol
                JOIN finished_goods fg ON pol.product_id = fg.id
                WHERE pol.plant_name = :p
                ORDER BY pol.prod_date DESC
            """), conn, params={"p": selected_plant})
        else:
            df_export = pd.read_sql_query(text("""
                SELECT sl.date_time AS "Sana", m.item_name AS "Tovar", sl.action_type AS "Amal", 
                       sl.quantity AS "Miqdor", sl.price_som AS "Narx (so'm)", sl.operator_name AS "Mas'ul", sl.notes AS "Izoh"
                FROM stock_logs sl
                JOIN materials m ON sl.material_id = m.id
                WHERE sl.plant_name = :p
                ORDER BY sl.id DESC
            """), conn, params={"p": selected_plant})
        
    st.dataframe(df_export, use_container_width=True)
    
    c_btn1, c_btn2 = st.columns(2)
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Hisobot')
    excel_bytes = excel_buf.getvalue()
    c_btn1.download_button("📥 Excel (.xlsx) yuklab olish", excel_bytes, f"{selected_plant}_{date.today()}.xlsx")
    
    pdf_bytes = generate_pdf(df_export, f"{selected_plant} - Hisobot")
    c_btn2.download_button("📥 PDF (.pdf) yuklab olish", pdf_bytes, f"{selected_plant}_{date.today()}.pdf")
    
    st.markdown("---")
    with st.expander("Telegram hisobot parametrlarini sozlash"):
        t_token = st.text_input("Bot Token:", value=DEFAULT_BOT_TOKEN)
        t_chat = st.text_input("Chat ID:", value=DEFAULT_CHAT_ID)
        t_fmt = st.selectbox("Format:", ["Excel (.xlsx)", "PDF (.pdf)"])
        if st.button("🚀 Telegramga Yuborish"):
            if t_token and t_chat:
                fb = excel_bytes if t_fmt == "Excel (.xlsx)" else pdf_bytes.getvalue()
                fn = f"Hisobot_{selected_plant}.{'xlsx' if t_fmt == 'Excel (.xlsx)' else 'pdf'}"
                if send_telegram_file(fb, fn, t_token, t_chat, f"🏭 {selected_plant} hisoboti"):
                    st.success("✅ Telegramga yuborildi!")
                else:
                    st.error("❌ Yuborishda xatolik yuz berdi.")

# -------------------------------------------------------------
# BO'LIM 7: NARX VA SARF DINAMIKASI
# -------------------------------------------------------------
elif menu == "📈 7. Narx va Sarf Dinamikasi":
    st.markdown(f"<div class='erp-header'>{p_logo} {selected_plant} — Narx va Sarf Grafigi</div>", unsafe_allow_html=True)
    
    with engine.connect() as conn:
        df_l = pd.read_sql_query(text("""
            SELECT sl.date_time, m.item_name, sl.action_type, sl.quantity, sl.price_som 
            FROM stock_logs sl
            JOIN materials m ON sl.material_id = m.id
            WHERE sl.plant_name = :p
        """), conn, params={"p": selected_plant})
    
    if not df_l.empty:
        df_l['date_time'] = pd.to_datetime(df_l['date_time'])
        df_p_history = df_l[(df_l['action_type'] == 'KIRIM') & (df_l['price_som'] > 0)]
        if not df_p_history.empty:
            st.markdown("#### 💰 Xarid narxlari dinamikasi")
            fig1 = px.line(df_p_history, x='date_time', y='price_som', color='item_name', markers=True)
            st.plotly_chart(fig1, use_container_width=True)
            
        df_usage_history = df_l[df_l['action_type'] == 'SARF']
        if not df_usage_history.empty:
            st.markdown("#### 📉 Sarflangan detallar hajmi")
            fig2 = px.bar(df_usage_history, x='date_time', y='quantity', color='item_name')
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Harakatlar tarixi bo'sh.")