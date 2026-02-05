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

# --- 🎨 UI 美化核心样式 (CSS) ---
def local_css():
    st.markdown("""
    <style>
        /* 全局背景微调 */
        .stApp {
            background-color: #f8f9fa;
        }
        /* 顶部边距调整 */
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        /* 卡片容器样式 */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        /* 按钮圆角化 */
        .stButton>button {
            border-radius: 20px;
            font-weight: bold;
            border: none;
            transition: all 0.3s;
        }
        /* 主按钮悬停效果 */
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        /* 侧边栏美化 */
        section[data-testid="stSidebar"] {
            background-color: #ffffff;
            border-right: 1px solid #f0f0f0;
        }
        /* 标题样式 */
        h1, h2, h3 {
            font-family: 'Helvetica Neue', sans-serif;
            color: #333;
        }
        /* 进度条颜色 */
        .stProgress > div > div > div > div {
            background-image: linear-gradient(to right, #4facfe 0%, #00f2fe 100%);
        }
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

# ================= 2. 核心逻辑函数 (保持不变) =================

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
    
    # 返回状态，文字，以及对应的颜色
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

def plot_function(formula_str):
    try:
        if not formula_str or pd.isna(formula_str): return
        x = np.linspace(-5, 5, 100)
        y = eval(formula_str.replace("^", "**"), {"__builtins__":None}, {"x":x,"np":np,"sin":np.sin,"cos":np.cos,"abs":np.abs})
        st.line_chart(pd.DataFrame({"x":x,"y":y}), x="x", y="y", height=200)
    except: pass

# ================= 3. 侧边栏 (美化版) =================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
    st.markdown("### 🚀 盐城中考智700")
    st.markdown("---")
    
    # 使用 emoji 增加视觉引导
    menu = st.radio(
        "功能导航", 
        ["🏠 冲刺作战室", "📅 今日智能日报", "🤖 定向特训", "📸 错题录入", "📓 云端错题本"], 
        index=0,
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    days = get_countdown()
    # 倒计时卡片
    st.markdown(f"""
    <div style="background-color:#e8f4fd; padding:15px; border-radius:10px; text-align:center; border:1px solid #d0e6fa;">
        <h4 style="margin:0; color:#007bff;">中考倒计时</h4>
        <h1 style="margin:0; color:#0056b3; font-size: 3em;">{days}</h1>
        <small>天道酬勤，厚积薄发</small>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    if conn:
        st.markdown('✅ <small style="color:green">云数据库已连接</small>', unsafe_allow_html=True)
    else:
        st.markdown('⚠️ <small style="color:orange">本地离线模式</small>', unsafe_allow_html=True)

# ================= 4. 主页面逻辑 =================

if menu == "🏠 冲刺作战室":
    # 顶部 Hero 区域
    st.markdown("""
    # 🎓 个人冲刺作战大屏
    <span style='color:grey; font-size: 1.1em;'>数据驱动复习，让每一分努力都算数。</span>
    """, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 关键指标卡片 (Metrics)
    mistakes = load_mistakes()
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("🎯 目标总分", "710 分", "冲刺盐中")
    with c2: st.metric("🌍 地生得分", "38.5 分", "已锁定")
    with c3: st.metric("📓 错题库存", f"{len(mistakes)} 题", "待消灭")
    with c4: st.metric("🔥 学习状态", "Excellent", "保持手感")

    st.markdown("---")
    
    # 进度条区域
    col_l, col_r = st.columns([1, 1])
    
    with col_l:
        st.subheader("🧬 理科攻坚")
        with st.container(border=True):
            st.write("**数学** (目标 145)")
            st.progress(0.60)
            st.caption("⚡ 重点：二次函数、圆")
            st.write("**物理** (目标 95)")
            st.progress(0.70)
            st.write("**化学** (目标 68)")
            st.progress(0.80)

    with col_r:
        st.subheader("📚 文科积累")
        with st.container(border=True):
            st.write("**英语** (目标 140)")
            st.progress(0.90)
            st.caption("📝 重点：作文书写")
            st.write("**语文** (目标 130)")
            st.progress(0.85)
            st.write("**政史** (目标 96)")
            st.progress(0.95)

elif menu == "📅 今日智能日报":
    st.title("📅 今日智能日报")
    st.info("💡 每日三题（数+英+物），保持题感，拒绝题海战术。")
    
    if st.button("🚀 生成今日专属小卷", type="primary", use_container_width=True):
        with st.spinner("🤖 AI 正在为你出题..."):
            res = generate_daily_mix_automatically()
            if res:
                st.session_state.daily_tasks = res
                st.rerun()

    if "daily_tasks" in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        for i, q in enumerate(st.session_state.daily_tasks):
            # 题目卡片
            with st.container(border=True):
                sub = q.get('subject', '综合')
                content = q.get('content') or q.get('question')
                
                # 题头
                st.markdown(f"**第 {i+1} 题** <span style='background-color:#e6f3ff; color:#0066cc; padding:2px 8px; border-radius:4px; font-size:0.8em;'>{sub}</span>", unsafe_allow_html=True)
                st.markdown(f"#### {content}")
                
                # 选项
                if q.get('options'): 
                    st.radio("请选择：", q['options'], key=f"d_o_{i}", index=None)
                
                # 操作栏
                st.markdown("---")
                c_1, c_2 = st.columns([1, 4])
                with c_1:
                    if st.button("💾 存入错题本", key=f"d_s_{i}"):
                        if save_mistake(q): st.success("已保存")
                        else: st.warning("已存在")
                with c_2:
                    with st.expander("🔍 查看答案与解析"):
                        st.markdown(f"**正确答案：** `{q.get('answer')}`")
                        st.info(f"**解析：** {q.get('analysis')}")

elif menu == "🤖 定向特训":
    st.title("🤖 AI 定向特训")
    
    # 控制面板卡片
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        sub = c1.selectbox("📚 选择科目", ["数学", "英语", "物理", "化学", "语文"])
        typ = c2.selectbox("📌 选择题型", ["选择题", "填空题", "简答题"])
        c3.write("") # 占位
        c3.write("") # 占位
        if c3.button("✨ 生成题目", type="primary", use_container_width=True):
            with st.spinner("AI 思考中..."):
                st.session_state.ai_qs = generate_questions_batch(sub, typ, 3)

    if "ai_qs" in st.session_state:
        st.markdown("### 📝 练习开始")
        for i, q in enumerate(st.session_state.ai_qs):
            with st.container(border=True):
                st.write(q.get('content'))
                if q.get('options'): st.radio("选项", q['options'], key=f"ai_o_{i}")
                
                # 操作区
                col_act1, col_act2 = st.columns([1, 5])
                with col_act1:
                     if st.button("💾 存错题", key=f"ai_s_{i}"):
                        q['subject'] = sub
                        save_mistake(q)
                        st.toast("✅ 已加入错题本")
                with col_act2:
                    with st.expander("👀 偷看答案"):
                        st.write(f"答案：{q.get('answer')}")
                        st.caption(f"解析：{q.get('analysis')}")

elif menu == "📸 错题录入":
    st.title("📸 拍照错题归档")
    st.caption("学校试卷、练习册错题，拍个照永久保存，系统自动安排复习。")
    
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            up_sub = st.selectbox("归属科目", ["数学", "物理", "化学", "英语", "语文"])
            up_file = st.file_uploader("📤 上传题目照片", type=['jpg', 'png'])
        with col2:
            up_note = st.text_area("📝 错因/备注", height=150, placeholder="例如：公式记反了，需要重背...")
            st.write("")
            if up_file and st.button("☁️ 上传到云端数据库", type="primary", use_container_width=True):
                with st.spinner("压缩上传中..."):
                    b64 = image_to_base64(up_file)
                    if b64:
                        if save_mistake({"subject":up_sub, "content":"📸 [图片题]", "analysis":up_note, "is_image_upload":True, "image_base64":b64}):
                            st.success("✅ 上传成功！")
                            time.sleep(1)
                            st.rerun()

elif menu == "📓 云端错题本":
    st.title("📓 云端智能错题本")
    
    mistakes = load_mistakes()
    
    if not mistakes:
        st.info("🍃 错题本空空如也，去刷几道题吧！")
    else:
        # 分类逻辑
        urgent_review = []
        all_records = []
        for m in mistakes:
            status, msg, color = get_review_status(m['added_date'])
            # 包装一下数据，方便渲染
            m['status_label'] = msg
            m['status_color'] = color
            if status: urgent_review.append(m)
            all_records.append(m)

        tab1, tab2 = st.tabs([f"🔥 今日急需复习 ({len(urgent_review)})", f"🗂️ 全部档案 ({len(all_records)})"])
        
        def render_mistake_card(m):
            # 卡片容器
            with st.container(border=True):
                # 标题栏：科目 + 状态标签
                col_head1, col_head2 = st.columns([4, 2])
                with col_head1:
                    st.markdown(f"**[{m['subject']}]** <small style='color:gray'>{m['added_date']} 录入</small>", unsafe_allow_html=True)
                with col_head2:
                    # 彩色标签
                    st.markdown(f"<div style='text-align:right;'><span style='background-color:{m['status_color']}; color:white; padding:2px 8px; border-radius:10px; font-size:0.8em;'>{m['status_label']}</span></div>", unsafe_allow_html=True)
                
                # 内容区
                if m.get('is_image_upload'):
                    # 图片题
                    try:
                        img_data = base64.b64decode(m.get('image_base64', ''))
                        st.image(img_data, width=400)
                    except:
                        st.error("图片加载失败")
                    st.info(f"**你的备注：** {m.get('analysis')}")
                else:
                    # 文字题
                    st.write(m.get('content'))
                    with st.expander("🔻 查看答案"):
                        st.markdown(f"**答案：** `{m.get('answer')}`")
                        st.markdown(f"**解析：** {m.get('analysis')}")

        with tab1:
            if not urgent_review:
                st.balloons()
                st.success("🎉 太棒了！今日复习任务已清空！")
            else:
                for m in urgent_review:
                    render_mistake_card(m)
        
        with tab2:
            for m in all_records:
                render_mistake_card(m)
