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
    page_title="盐城中考智700·双端版",
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
        /* 登录页卡片 */
        .login-card {
            background: white; padding: 30px; border-radius: 15px; 
            box-shadow: 0 10px 25px rgba(0,0,0,0.1); text-align: center;
            border: 1px solid #eee; margin-bottom: 20px;
        }
    </style>
    """, unsafe_allow_html=True)

local_css()

# 初始化 Session State (身份管理)
if 'role' not in st.session_state:
    st.session_state.role = None # None, 'student', 'parent'

# 读取 Key
if "DEEPSEEK_API_KEY" in st.secrets:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    # 🔴 本地调试 Key
    DEEPSEEK_API_KEY = "sk-4db012ee3d684f76ac67fa943c636cc2"

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
            "answer": question_data.get("answer", ""),
            "analysis": question_data.get("analysis", ""),
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
    return False, f"✅ 记忆保鲜中 ({days_diff}天)", "blue"

def generate_questions_batch(subject, type_choice, count=3):
    prompt = f"你是盐城中考出题专家。出{count}道【{subject}】【{type_choice}】。中考难度。严禁识图题。返回JSON Array包含content,options,answer,analysis。"
    try:
        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"system","content":"JSON Array Only"},{"role":"user","content":prompt}])
        return json.loads(re.sub(r'```json\s*|\s*```', '', res.choices[0].message.content))
    except: return []

def generate_daily_mix_automatically():
    prompt = "生成“盐城中考晨测”3道题：1.数学 2.英语 3.物理。返回纯JSON Array，必须含key 'content'。"
    try:
        res = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"system","content":"JSON Array Only. 'content' is mandatory."},{"role":"user","content":prompt}])
        return json.loads(re.sub(r'```json\s*|\s*```', '', res.choices[0].message.content))
    except: return []

# ================= 3. 登录页逻辑 =================
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""
        <div class="login-card">
            <h1>🎓 盐城中考智700</h1>
            <p style='color:grey'>请选择你的身份进入系统</p>
        </div>
        """, unsafe_allow_html=True)
        
        tab_student, tab_parent = st.tabs(["我是学生 🧑‍🎓", "我是家长 👨‍👩‍👧‍👦"])
        
        with tab_student:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 学生端进入", type="primary", use_container_width=True):
                st.session_state.role = 'student'
                st.rerun()
                
        with tab_parent:
            st.markdown("<br>", unsafe_allow_html=True)
            pwd = st.text_input("请输入家长密码", type="password", placeholder="默认: 8888")
            if st.button("🔐 家长端进入", use_container_width=True):
                if pwd == "8888":  # 这里设置你的密码
                    st.session_state.role = 'parent'
                    st.rerun()
                else:
                    st.error("密码错误")

# ================= 4. 学生端界面 =================
def student_interface():
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=50)
        st.markdown("### 🧑‍🎓 学生专属")
        menu = st.radio("功能", ["🏠 冲刺作战室", "📅 今日日报", "🤖 定向刷题", "📸 错题录入", "📓 自主复习"], label_visibility="collapsed")
        st.markdown("---")
        st.button("🚪 退出登录", on_click=lambda: st.session_state.update(role=None))

    if menu == "🏠 冲刺作战室":
        st.markdown("# ⚔️ 冲刺！向着710分")
        days = get_countdown()
        st.info(f"⏳ 距离盐城中考还有 **{days}** 天，乾坤未定，你我皆是黑马！")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 🧬 理科进度")
            st.write("数学"); st.progress(0.6)
            st.write("物理"); st.progress(0.7)
            st.write("化学"); st.progress(0.8)
        with col2:
            st.markdown("### 📚 文科进度")
            st.write("英语"); st.progress(0.9)
            st.write("语文"); st.progress(0.85)
            
    elif menu == "📅 今日日报":
        st.title("📅 今日任务")
        if st.button("🚀 生成题目", type="primary"):
            with st.spinner("AI 出题中..."):
                res = generate_daily_mix_automatically()
                if res: st.session_state.daily_tasks = res
        
        if "daily_tasks" in st.session_state:
            for i, q in enumerate(st.session_state.daily_tasks):
                with st.container(border=True):
                    st.write(f"**[{q.get('subject')}]** {q.get('content')}")
                    if q.get('options'): st.radio("选项", q['options'], key=f"s_d_{i}")
                    c1, c2 = st.columns([1,4])
                    if c1.button("💾 存错题", key=f"s_save_{i}"): save_mistake(q); st.success("已保存")
                    with c2.expander("查看答案"):
                        st.write(f"答案：{q.get('answer')}")
                        st.write(f"解析：{q.get('analysis')}")

    elif menu == "🤖 定向刷题":
        st.title("🤖 定向特训")
        c1, c2 = st.columns(2)
        sub = c1.selectbox("科目", ["数学", "英语", "物理", "化学"])
        typ = c2.selectbox("题型", ["选择题", "填空题"])
        if st.button("开始特训", type="primary"):
            st.session_state.ai_qs = generate_questions_batch(sub, typ, 3)
        
        if "ai_qs" in st.session_state:
            for i, q in enumerate(st.session_state.ai_qs):
                with st.container(border=True):
                    st.write(q.get('content'))
                    if q.get('options'): st.radio("选", q['options'], key=f"s_ai_{i}")
                    if st.button("💾 存错题", key=f"s_ai_s_{i}"): save_mistake(q); st.toast("保存成功")

    elif menu == "📸 错题录入":
        st.title("📸 拍照上传")
        c1, c2 = st.columns(2)
        up_sub = c1.selectbox("科目", ["数学", "物理", "化学", "英语", "语文"])
        up_note = c2.text_area("备注")
        up_file = st.file_uploader("传图", type=['jpg', 'png'])
        if up_file and st.button("☁️ 上传"):
            b64 = image_to_base64(up_file)
            if save_mistake({"subject":up_sub, "content":"📸 [图片题]", "analysis":up_note, "is_image_upload":True, "image_base64":b64}):
                st.success("上传成功！")

    elif menu == "📓 自主复习":
        st.title("📓 我的错题本")
        mistakes = load_mistakes()
        urgent = [m for m in mistakes if get_review_status(m['added_date'])[0]]
        if not urgent: st.success("今日无紧急复习任务！")
        else:
            for m in urgent:
                with st.container(border=True):
                    st.caption(f"[{m['subject']}] {get_review_status(m['added_date'])[1]}")
                    if m.get('is_image_upload'): 
                         try: st.image(base64.b64decode(m.get('image_base64','')))
                         except: pass
                    else: st.write(m.get('content'))
                    with st.expander("看解析"): st.write(m.get('analysis'))

# ================= 5. 家长端界面 =================
def parent_interface():
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2942/2942813.png", width=50)
        st.markdown("### 👨‍👩‍👧‍👦 家长监管")
        menu = st.radio("功能", ["📊 全维监管大屏", "🧐 检查作业情况"], label_visibility="collapsed")
        st.markdown("---")
        st.button("🚪 退出登录", on_click=lambda: st.session_state.update(role=None))

    mistakes = load_mistakes()
    
    if menu == "📊 全维监管大屏":
        st.title("📊 学习情况监控中心")
        
        # 统计卡片
        c1, c2, c3 = st.columns(3)
        c1.metric("总错题量", f"{len(mistakes)} 题", "知识漏洞")
        
        # 计算今日新增
        today_str = str(datetime.date.today())
        today_new = len([m for m in mistakes if m.get('added_date') == today_str])
        c2.metric("今日新增错题", f"{today_new} 题", "今日学习量")
        
        # 计算待复习
        need_review = len([m for m in mistakes if get_review_status(m.get('added_date'))[0]])
        c3.metric("待复习存量", f"{need_review} 题", "需督促")
        
        st.markdown("---")
        st.subheader("📈 学科薄弱点分析")
        
        if mistakes:
            # 简单的学科统计
            df = pd.DataFrame(mistakes)
            if 'subject' in df.columns:
                sub_counts = df['subject'].value_counts()
                st.bar_chart(sub_counts)
                st.caption("注：柱状图越高，代表该学科错题越多，需要重点关注。")
        else:
            st.info("暂无数据，请督促孩子多刷题。")

    elif menu == "🧐 检查作业情况":
        st.title("🧐 错题检查")
        st.info("这里展示所有错题的详细答案，方便家长抽查。")
        
        if not mistakes:
            st.write("暂无记录。")
        else:
            # 搜索筛选
            search = st.text_input("🔍 搜索关键词或日期")
            
            for m in mistakes:
                # 简单的过滤
                if search and search not in str(m): continue
                
                with st.container(border=True):
                    c_head1, c_head2 = st.columns([4, 1])
                    c_head1.markdown(f"**[{m.get('subject')}]** {m.get('added_date')}")
                    c_head2.markdown(f"<span style='color:red'>{get_review_status(m['added_date'])[1]}</span>", unsafe_allow_html=True)
                    
                    if m.get('is_image_upload'):
                         try: st.image(base64.b64decode(m.get('image_base64','')), width=300)
                         except: st.error("图片无法加载")
                         st.write(f"**学生备注：** {m.get('analysis')}")
                    else:
                        st.write(f"**题目：** {m.get('content')}")
                        st.markdown(f"**✅ 正确答案：** `{m.get('answer')}`")
                        st.markdown(f"**💡 解析：** {m.get('analysis')}")

# ================= 6. 程序入口 =================

if st.session_state.role == 'student':
    student_interface()
elif st.session_state.role == 'parent':
    parent_interface()
else:
    login_page()
