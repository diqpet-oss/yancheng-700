import streamlit as st
import datetime
from openai import OpenAI
import json
import re
import numpy as np
import pandas as pd
import os
import time
from PIL import Image
from streamlit_gsheets import GSheetsConnection
import base64
from io import BytesIO

# ================= 1. 配置与初始化 =================

st.set_page_config(
    page_title="盐城中考智700·Pro",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 🎨 UI 美化 (CSS) ---
def local_css():
    st.markdown("""
    <style>
        .stApp { background-color: #f8f9fa; }
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }
        /* 卡片样式 */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .stButton>button { border-radius: 20px; font-weight: bold; border: none; transition: all 0.3s; }
        .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

local_css()

# 读取 Key
if "DEEPSEEK_API_KEY" in st.secrets:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    # 🔴 本地调试 Key
    DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

BASE_URL = "https://api.deepseek.com"

# 连接数据库
conn = None
try:
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        conn = st.connection("gsheets", type=GSheetsConnection)
except:
    pass

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ================= 2. 核心逻辑函数 =================

def get_countdown():
    exam_date = datetime.date(2026, 6, 16)
    today = datetime.date.today()
    return (exam_date - today).days

def load_mistakes():
    if conn is None: return []
    try:
        df = conn.read(ttl=0)
        df = df.fillna("")
        return df.to_dict(orient="records")
    except: return []

def save_mistake(question_data):
    if conn is None:
        st.error("❌ 未连接云端数据库")
        return False
    try:
        existing_data = conn.read(ttl=0)
        new_row = {
            "subject": question_data.get("subject", "综合"),
            "content": question_data.get("content") or question_data.get("question") or "无内容",
            "options": str(question_data.get("options", [])),
            "answer": question_data.get("answer", "暂无答案"),
            "analysis": question_data.get("analysis", "暂无解析"),
            "function_formula": question_data.get("function_formula", ""),
            "added_date": str(datetime.date.today()),
            "review_count": 0,
            "is_image_upload": question_data.get("is_image_upload", False),
            "image_base64": question_data.get("image_base64", "")
        }
        if not new_row["is_image_upload"] and not existing_data.empty and "content" in existing_data.columns:
            if new_row["content"] in existing_data["content"].values: return False
        
        new_df = pd.DataFrame([new_row])
        updated_df = pd.concat([existing_data, new_df], ignore_index=True)
        conn.update(data=updated_df)
        return True
    except Exception as e:
        st.error(f"保存失败: {e}")
        return False

def image_to_base64(uploaded_file):
    try:
        bytes_data = uploaded_file.getvalue()
        img = Image.open(BytesIO(bytes_data))
        if img.mode != 'RGB': img = img.convert('RGB')
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, int(img.height * ratio)))
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=60)
        return base64.b64encode(buffered.getvalue()).decode()
    except: return ""

def get_review_status(added_date_str):
    try: added_date = datetime.datetime.strptime(str(added_date_str), "%Y-%m-%d").date()
    except: return False, "日期错误", "gray"
    days_diff = (datetime.date.today() - added_date).days
    if days_diff in [1, 3, 7, 15, 30]: return True, f"⚠️ 遗忘临界点 ({days_diff}天)", "red"
    elif days_diff == 0: return False, "🆕 今日新题", "green"
    elif days_diff > 30: return True, "📅 长期复习", "orange"
    return False, f"✅ 记忆保鲜 ({days_diff}天)", "blue"

# --- 🚀 核心修复：强力 Prompt ---
def generate_questions_batch(subject, type_choice, count=3):
    prompt = f"""
    你是盐城中考出题专家。出{count}道【{subject}】【{type_choice}】。中考难度。严禁识图题。
    【必须返回 JSON Array】，每个对象必须包含：
    - "content": 题目
    - "options": 选项列表(填空题为空)
    - "answer": 正确答案(必须生成)
    - "analysis": 详细解析(必须生成)
    """
    try:
        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"system","content":"JSON Array Only"},{"role":"user","content":prompt}])
        return json.loads(re.sub(r'```json\s*|\s*```', '', res.choices[0].message.content))
    except: return []

def generate_daily_mix_automatically():
    prompt = """
    生成“盐城中考晨测”3道题：1.数学 2.英语 3.物理。
    【必须返回 JSON Array】，每个对象必须包含：
    - "subject": 科目
    - "content": 题目
    - "options": 选项列表
    - "answer": 正确答案(绝对不能为空)
    - "analysis": 详细解析(绝对不能为空)
    """
    try:
        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"system","content":"JSON Array Only. 'answer' and 'analysis' fields are mandatory."},{"role":"user","content":prompt}])
        return json.loads(re.sub(r'```json\s*|\s*```', '', res.choices[0].message.content))
    except: return []

# ================= 3. 主界面逻辑 =================

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
    st.markdown("### 🚀 盐城中考智700")
    menu = st.radio("功能", ["🏠 冲刺作战室", "📅 今日智能日报", "🤖 定向特训", "📸 错题录入", "📓 云端错题本"], label_visibility="collapsed")
    st.markdown("---")
    days = get_countdown()
    st.markdown(f"""
    <div style="background-color:#e8f4fd; padding:15px; border-radius:10px; text-align:center; border:1px solid #d0e6fa;">
        <h4 style="margin:0; color:#007bff;">中考倒计时</h4>
        <h1 style="margin:0; color:#0056b3;">{days}</h1>
    </div>
    """, unsafe_allow_html=True)
    if conn: st.caption("✅ 云端数据库已连接")
    else: st.caption("⚠️ 本地离线模式")

# --- 1. 首页 ---
if menu == "🏠 冲刺作战室":
    st.markdown("# ⚔️ 决战中考 · 数据大屏")
    mistakes = load_mistakes()
    c1, c2, c3 = st.columns(3)
    c1.metric("🎯 目标总分", "710")
    c2.metric("📓 错题积累", f"{len(mistakes)}")
    c3.metric("🔥 待复习", f"{len([m for m in mistakes if get_review_status(m['added_date'])[0]])}")
    
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🧬 理科攻坚")
        st.write("数学"); st.progress(0.6)
        st.write("物理"); st.progress(0.7)
        st.write("化学"); st.progress(0.8)
    with col2:
        st.subheader("📚 文科积累")
        st.write("英语"); st.progress(0.9)
        st.write("语文"); st.progress(0.85)

# --- 2. 日报 (修复答案版) ---
elif menu == "📅 今日智能日报":
    st.title("📅 今日智能日报")
    st.info("💡 每日三题，保持手感。AI 已被强制要求必须给答案。")
    
    if st.button("🚀 生成今日任务", type="primary"):
        with st.spinner("AI 正在严谨出题并撰写解析..."):
            res = generate_daily_mix_automatically()
            if res: st.session_state.daily_tasks = res
    
    if "daily_tasks" in st.session_state:
        for i, q in enumerate(st.session_state.daily_tasks):
            with st.container(border=True):
                st.markdown(f"**第{i+1}题 [{q.get('subject','综合')}]**")
                st.write(q.get('content'))
                if q.get('options'): st.radio("选项", q['options'], key=f"d_o_{i}")
                
                c1, c2 = st.columns([1, 4])
                if c1.button("💾 存错题", key=f"d_s_{i}"): 
                    save_mistake(q); st.success("已保存")
                
                with c2.expander("🔍 查看答案与解析"):
                    # 双重保险：如果 AI 还是没给，显示提示
                    ans = q.get('answer') or "⚠️ AI未返回答案，请重试"
                    ana = q.get('analysis') or "⚠️ AI未返回解析，请重试"
                    st.markdown(f"**正确答案：** `{ans}`")
                    st.info(f"**解析：** {ana}")

# --- 3. 定向刷题 (修复答案版) ---
elif menu == "🤖 定向特训":
    st.title("🤖 定向特训")
    with st.container(border=True):
        c1, c2, c3 = st.columns([2,2,1])
        sub = c1.selectbox("科目", ["数学", "英语", "物理", "化学"])
        typ = c2.selectbox("题型", ["选择题", "填空题"])
        c3.write(""); c3.write("")
        if c3.button("✨ 生成", use_container_width=True, type="primary"):
            with st.spinner("生成中..."):
                st.session_state.ai_qs = generate_questions_batch(sub, typ, 3)

    if "ai_qs" in st.session_state:
        for i, q in enumerate(st.session_state.ai_qs):
            with st.container(border=True):
                st.write(q.get('content'))
                if q.get('options'): st.radio("选项", q['options'], key=f"ai_o_{i}")
                
                c1, c2 = st.columns([1, 4])
                if c1.button("💾 存错题", key=f"ai_s_{i}"): 
                    save_mistake(q); st.toast("已保存")
                
                with c2.expander("👀 查看解析"):
                    st.markdown(f"**答案：** `{q.get('answer')}`")
                    st.caption(f"**解析：** {q.get('analysis')}")

# --- 4. 错题录入 ---
elif menu == "📸 错题录入":
    st.title("📸 拍照错题归档")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        sub = c1.selectbox("科目", ["数学", "物理", "化学", "英语", "语文"])
        note = c2.text_area("备注")
        up = st.file_uploader("上传图片", type=['jpg', 'png'])
        if up and st.button("☁️ 上传到云端", type="primary"):
            b64 = image_to_base64(up)
            if save_mistake({"subject":sub, "content":"📸 [图片题]", "analysis":note, "is_image_upload":True, "image_base64":b64}):
                st.success("上传成功！")

# --- 5. 错题本 ---
elif menu == "📓 云端错题本":
    st.title("📓 云端智能错题本")
    mistakes = load_mistakes()
    if not mistakes: st.info("空空如也，快去刷题吧！")
    else:
        urgent = [m for m in mistakes if get_review_status(m['added_date'])[0]]
        tab1, tab2 = st.tabs([f"🔥 待复习 ({len(urgent)})", f"🗂️ 全部 ({len(mistakes)})"])
        
        def render_card(m):
            with st.container(border=True):
                st.markdown(f"**[{m['subject']}]** <small>{m['added_date']}</small> · {get_review_status(m['added_date'])[1]}", unsafe_allow_html=True)
                if m.get('is_image_upload'):
                    try: st.image(base64.b64decode(m['image_base64']))
                    except: st.error("图片错误")
                    st.write(f"备注：{m.get('analysis')}")
                else:
                    st.write(m.get('content'))
                    with st.expander("查看答案"):
                        st.write(f"答案：{m.get('answer')}")
                        st.write(f"解析：{m.get('analysis')}")

        with tab1:
            if not urgent: st.success("🎉 今日复习任务已完成！")
            else: 
                for m in urgent: render_card(m)
        with tab2:
            for m in mistakes: render_card(m)
