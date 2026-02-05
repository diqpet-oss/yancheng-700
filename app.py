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

# ================= 1. 配置与初始化 =================

# 🔴 🔴 🔴 务必填入你的 Key 🔴 🔴 🔴
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
BASE_URL = "https://api.deepseek.com"

st.set_page_config(
    page_title="盐城中考智700·Pro",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 文件配置
MISTAKES_FILE = "mistakes.json"
IMAGE_DIR = "uploaded_images"
DAILY_CACHE_DIR = "daily_cache" # 新增：存放每日日报的文件夹

# 自动创建文件夹
for folder in [IMAGE_DIR, DAILY_CACHE_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ================= 2. 核心功能函数 =================

def get_countdown():
    exam_date = datetime.date(2026, 6, 16)
    today = datetime.date.today()
    return (exam_date - today).days

# --- 错题本相关 ---
def load_mistakes():
    if not os.path.exists(MISTAKES_FILE):
        return []
    try:
        with open(MISTAKES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_mistake(question_data):
    mistakes = load_mistakes()
    if not question_data.get('is_image_upload'):
        for m in mistakes:
            if m.get('content') == question_data.get('content'):
                return False 
    
    question_data['added_date'] = str(datetime.date.today())
    question_data['review_count'] = 0
    mistakes.append(question_data)
    
    with open(MISTAKES_FILE, "w", encoding="utf-8") as f:
        json.dump(mistakes, f, ensure_ascii=False, indent=2)
    return True

def save_uploaded_image(uploaded_file):
    try:
        file_path = os.path.join(IMAGE_DIR, uploaded_file.name)
        if os.path.exists(file_path):
            timestamp = int(datetime.datetime.now().timestamp())
            file_path = os.path.join(IMAGE_DIR, f"{timestamp}_{uploaded_file.name}")
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return file_path
    except Exception as e:
        st.error(f"保存失败: {e}")
        return None

def get_review_status(added_date_str):
    try:
        added_date = datetime.datetime.strptime(added_date_str, "%Y-%m-%d").date()
    except:
        return False, "日期错误"

    today = datetime.date.today()
    days_diff = (today - added_date).days
    
    review_intervals = [1, 3, 7, 15, 30]
    
    if days_diff in review_intervals:
        return True, f"⚠️ 遗忘临界点 (第{days_diff}天)"
    elif days_diff == 0:
        return False, "🆕 今日新题"
    elif days_diff > 30:
        return True, "📅 长期复习"
    else:
        return False, f"✅ 记忆保鲜中 (已过{days_diff}天)"

# --- AI 生成相关 ---
def generate_questions_batch(subject, type_choice, count=3):
    no_image_instruction = ""
    if subject in ["数学", "物理"]:
        no_image_instruction = "严禁出识图题。几何题请文字描述。函数题请含function_formula。"
    
    prompt = f"""
    你是盐城中考出题专家。出 {count} 道【{subject}】【{type_choice}】。
    要求：难度中考冲刺级。{no_image_instruction}
    格式：JSON List:
    [{{ "content": "内容", "options": [], "answer": "答案", "analysis": "解析", "function_formula": null }}]
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "JSON Array Only"}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        return json.loads(content)
    except Exception as e:
        st.error(f"AI 连接出错: {e}")
        return []

# --- 日报自动生成逻辑 (新功能) ---
def get_daily_cache_path():
    today_str = str(datetime.date.today())
    return os.path.join(DAILY_CACHE_DIR, f"daily_tasks_{today_str}.json")

def load_daily_tasks():
    path = get_daily_cache_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def generate_daily_mix_automatically():
    """自动生成一套混合试卷：1数学+1英语+1物理"""
    prompt = """
    请为盐城初三学生生成一份“今日晨测”小卷，包含3道题：
    1. 数学题 (压轴题或填空题，带难度)
    2. 英语题 (单项选择或语法填空)
    3. 物理题 (电学或力学计算)
    
    要求：
    - 严禁出识图题。
    - 严格返回 JSON List 格式。
    - 包含字段: content, options, answer, analysis, subject(标明科目), function_formula(如有)
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "JSON Array Only"}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        data = json.loads(content)
        
        # 保存到本地缓存
        with open(get_daily_cache_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return data
    except Exception as e:
        st.error(f"日报生成失败: {e}")
        return []

def plot_function(formula_str):
    try:
        x = np.linspace(-5, 5, 100)
        safe_dict = {"x": x, "np": np, "sin": np.sin, "cos": np.cos, "abs": np.abs}
        formula_py = formula_str.replace("^", "**")
        y = eval(formula_py, {"__builtins__": None}, safe_dict)
        st.line_chart(pd.DataFrame({"x": x, "y": y}), x="x", y="y", height=200)
    except:
        pass

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=80)
    st.title("🚀 全能提分系统")
    # 调整菜单顺序，把日报放在第二位
    menu = st.radio("功能模块：", ["🏠 冲刺作战室", "📅 今日专属日报(新)", "🤖 定向刷题", "📸 错题录入", "📓 智能错题本"], index=0)
    st.markdown("---")
    st.metric("中考倒计时", f"{get_countdown()} 天")

# ================= 4. 主页面 =================

# --- 首页 ---
if menu == "🏠 冲刺作战室":
    st.title("🎓 盐城中考智700 · 作战大屏")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("🎯 目标总分", "710 分")
    col2.metric("🌍 地生得分", "38.5")
    col3.metric("📓 错题库存", f"{len(load_mistakes())} 题")

    st.markdown("---")
    st.subheader("📊 全科精细化进度表")
    
    subjects_data = {
        "语文": {"progress": 0.85, "goal": 130, "note": "古诗文默写满分，阅读理解待加强"},
        "数学": {"progress": 0.60, "goal": 145, "note": "⚡ 重点突破：二次函数、圆的证明"},
        "英语": {"progress": 0.90, "goal": 140, "note": "完形填空稳定，作文注意书写"},
        "物理": {"progress": 0.70, "goal": 95, "note": "电学实验题需专项训练"},
        "化学": {"progress": 0.80, "goal": 68, "note": "酸碱盐推断题熟练度提升"},
        "历史": {"progress": 0.95, "goal": 48, "note": "知识点背诵完成，刷真题"},
        "政治": {"progress": 0.95, "goal": 48, "note": "时事热点已整理"}
    }
    
    c1, c2 = st.columns(2)
    with c1:
        st.info("🧬 理科攻坚区")
        for sub in ["数学", "物理", "化学"]:
            data = subjects_data[sub]
            title_str = sub + " (目标 " + str(data['goal']) + "分)"
            st.write(f"**{title_str}**")
            st.progress(data['progress'])
            st.caption(f"📌 {data['note']}")
            st.write("---")
    with c2:
        st.success("📚 文科积累区")
        for sub in ["语文", "英语", "历史", "政治"]:
            data = subjects_data[sub]
            title_str = sub + " (目标 " + str(data['goal']) + "分)"
            st.write(f"**{title_str}**")
            st.progress(data['progress'])
            st.caption(f"📌 {data['note']}")
            st.write("---")

# --- 📅 今日专属日报 (全自动) ---
elif menu == "📅 今日专属日报(新)":
    st.title("📅 今日智能日报")
    st.caption(f"日期：{datetime.date.today()} | 每日一练，保持手感")
    
    # 1. 检查今日是否已生成
    daily_questions = load_daily_tasks()
    
    if daily_questions:
        st.success("✅ 今日任务已准备就绪！无需等待，直接开始！")
    else:
        st.warning("⚡ 又是元气满满的一天！系统正在为你生成今天的专属题目...")
        with st.spinner("🤖 AI 正在出题 (数学+英语+物理)..."):
            daily_questions = generate_daily_mix_automatically()
            st.rerun() # 生成完自动刷新
            
    # 2. 展示题目
    if daily_questions:
        for i, q in enumerate(daily_questions):
            sub = q.get('subject', '综合')
            content = q.get('content', '')
            
            with st.container(border=True):
                st.markdown(f"**第 {i+1} 题 [{sub}]**")
                st.write(content)
                
                if q.get('function_formula'): plot_function(q['function_formula'])
                if q.get('options'): st.radio("选项", q['options'], key=f"d_opt_{i}")
                
                c1, c2 = st.columns([1,1])
                if c1.button("👀 看答案", key=f"d_ans_{i}"):
                    st.session_state[f"d_show_{i}"] = True
                if c2.button("💾 存错题", key=f"d_save_{i}"):
                    save_mistake(q)
                    st.toast("已加入错题本")
                    
                if st.session_state.get(f"d_show_{i}"):
                    st.info(f"答案：{q.get('answer')}")
                    st.caption(f"解析：{q.get('analysis')}")

# --- 🤖 定向刷题 (原 AI 刷题) ---
elif menu == "🤖 定向刷题":
    st.title("🤖 AI 定向特训")
    st.caption("针对薄弱项，手动选择生成")
    
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2,2,2,2])
        subject = c1.selectbox("科目", ["数学", "物理", "化学", "英语", "语文"])
        q_type = c2.selectbox("题型", ["选择题", "填空题", "简答题"])
        q_count = c3.number_input("数量", 1, 5, 3)
        if c4.button("✨ 生成", type="primary", use_container_width=True):
            with st.spinner("生成中..."):
                res = generate_questions_batch(subject, q_type, q_count)
                if res:
                    st.session_state.questions_list = res
                    st.rerun()

    if "questions_list" in st.session_state:
        for i, q in enumerate(st.session_state.questions_list):
            q_content = q.get('content', '')
            label = "第 " + str(i+1) + " 题：" + str(q_content)[:20] + "..."
            with st.expander(label, expanded=True):
                st.write(q_content)
                if q.get('function_formula'): plot_function(q['function_formula'])
                if q.get('options'): st.radio("选项", q['options'], key=f"o_{i}")
                
                c1, c2 = st.columns([1,1])
                if c1.button("👀 答案", key=f"a_{i}"): st.session_state[f"show_{i}"] = True
                if c2.button("💾 存错题", key=f"s_{i}"):
                    q['subject'] = subject
                    save_mistake(q)
                    st.toast("已保存")
                
                if st.session_state.get(f"show_{i}"):
                    st.info(f"答案：{q.get('answer')}")
                    st.caption(f"解析：{q.get('analysis')}")

# --- 错题录入 ---
elif menu == "📸 错题录入":
    st.title("📸 试卷错题归档")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        up_subject = c1.selectbox("科目", ["数学", "物理", "化学", "英语", "语文"])
        up_source = c1.text_input("题目来源", placeholder="如：一模卷第10题")
        up_note = c2.text_area("错因备注", placeholder="如：计算错误")
        
        uploaded_file = st.file_uploader("上传照片", type=['png', 'jpg', 'jpeg'])
        if uploaded_file and st.button("💾 保存", type="primary"):
            path = save_uploaded_image(uploaded_file)
            if path:
                data = {
                    "subject": up_subject,
                    "content": f"📸 {up_source}",
                    "image_path": path,
                    "answer": "见图",
                    "analysis": up_note,
                    "is_image_upload": True
                }
                save_mistake(data)
                st.success("保存成功！")
                time.sleep(1)
                st.rerun()

# --- 错题本 ---
elif menu == "📓 智能错题本":
    st.title("📓 智能错题本")
    mistakes = load_mistakes()
    if not mistakes:
        st.info("暂无错题")
    else:
        today_list = [m for m in mistakes if get_review_status(m['added_date'])[0]]
        
        tab1, tab2 = st.tabs([f"🔥 待复习 ({len(today_list)})", f"🗂️ 全部 ({len(mistakes)})"])
        
        def render_card_safe(m):
            sub = m.get('subject', '未知')
            content = m.get('content', '')
            status_msg = get_review_status(m['added_date'])[1]
            st.caption(f"[{sub}] {status_msg}")
            with st.expander(f"{content[:30]}...", expanded=False):
                if m.get('is_image_upload'):
                    img_path = m.get('image_path')
                    if img_path and os.path.exists(img_path):
                        st.image(img_path)
                    else:
                        st.error("图片丢失")
                    st.write(f"**备注：** {m.get('analysis')}")
                else:
                    st.markdown("**题目：**")
                    st.write(content)
                    st.markdown("**答案：**")
                    st.write(m.get('answer'))
                    st.markdown("**解析：**")
                    st.write(m.get('analysis'))
                st.caption(f"录入时间：{m['added_date']}")

        with tab1:
            for m in today_list:
                render_card_safe(m)
                st.markdown("---")
        with tab2:
            for m in mistakes:
                render_card_safe(m)
                st.markdown("---")