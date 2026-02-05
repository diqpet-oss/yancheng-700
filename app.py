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

# 读取 Key (优先从 Secrets 读取，如果没有则用本地占位符)
if "DEEPSEEK_API_KEY" in st.secrets:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    # 🔴 🔴 🔴 如果你在本地运行，请在这里填入你的真实 Key
    DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

BASE_URL = "https://api.deepseek.com"

st.set_page_config(
    page_title="盐城中考智700·云端Pro",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 建立 Google Sheets 连接
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except:
    pass # 防止本地未配置 secrets 报错

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ================= 2. 核心功能函数 =================

def get_countdown():
    exam_date = datetime.date(2026, 6, 16)
    today = datetime.date.today()
    return (exam_date - today).days

# --- ☁️ 云端数据库操作 ---

def load_mistakes():
    """从 Google Sheets 读取错题"""
    try:
        df = conn.read(ttl=0)
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        # 如果连接失败，返回空列表，不阻断程序
        return []

def save_mistake(question_data):
    """保存错题到 Google Sheets"""
    try:
        existing_data = conn.read(ttl=0)
        
        # 确保 question_data 中的字段完整
        new_row = {
            "subject": question_data.get("subject", "综合"),
            "content": question_data.get("content") or question_data.get("question") or "题目内容缺失",
            "options": str(question_data.get("options", [])),
            "answer": question_data.get("answer", ""),
            "analysis": question_data.get("analysis", ""),
            "function_formula": question_data.get("function_formula", ""),
            "added_date": str(datetime.date.today()),
            "review_count": 0,
            "is_image_upload": question_data.get("is_image_upload", False),
            "image_base64": question_data.get("image_base64", "")
        }
        
        # 简单查重
        if not new_row["is_image_upload"]:
            if not existing_data.empty and "content" in existing_data.columns:
                if new_row["content"] in existing_data["content"].values:
                    return False

        new_df = pd.DataFrame([new_row])
        updated_df = pd.concat([existing_data, new_df], ignore_index=True)
        conn.update(data=updated_df)
        return True
        
    except Exception as e:
        st.error(f"保存云端失败: {e}")
        return False

def image_to_base64(uploaded_file):
    try:
        bytes_data = uploaded_file.getvalue()
        img = Image.open(BytesIO(bytes_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, int(img.height * ratio)))
        
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=60)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return img_str
    except:
        return ""

def get_review_status(added_date_str):
    try:
        added_date = datetime.datetime.strptime(str(added_date_str), "%Y-%m-%d").date()
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

# --- AI 生成相关 (已修复 None 问题) ---
def generate_questions_batch(subject, type_choice, count=3):
    no_image_instruction = ""
    if subject in ["数学", "物理"]:
        no_image_instruction = "严禁出识图题。几何题请文字描述。函数题请含function_formula。"
    
    prompt = f"""
    你是盐城中考出题专家。出 {count} 道【{subject}】【{type_choice}】。
    要求：难度中考冲刺级。{no_image_instruction}
    格式：严格返回 JSON Array，每个对象包含字段：content(题目文本), options(数组), answer, analysis。
    示例：[{{ "content": "...", "options": ["A","B"], "answer": "A", "analysis": "..." }}]
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "You must return a valid JSON Array."}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        return json.loads(content)
    except Exception as e:
        st.error(f"AI 连接出错: {e}")
        return []

def generate_daily_mix_automatically():
    # 修改了 Prompt，强制要求 content 字段
    prompt = """
    生成一份“盐城中考晨测”，包含3道题：
    1. 数学 (填空或计算)
    2. 英语 (单选)
    3. 物理 (选择或简答)
    
    【重要】：
    - 返回纯 JSON Array。
    - 题目内容字段名必须是 "content"。
    - 包含字段: subject, content, options, answer, analysis。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "Output valid JSON Array only. Key 'content' is mandatory."}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        data = json.loads(content)
        return data
    except Exception as e:
        # 如果出错，打印出来方便调试
        st.error(f"生成失败，AI 返回了无法解析的内容: {e}")
        return []

def plot_function(formula_str):
    try:
        if not formula_str or pd.isna(formula_str): return
        x = np.linspace(-5, 5, 100)
        safe_dict = {"x": x, "np": np, "sin": np.sin, "cos": np.cos, "abs": np.abs}
        formula_py = formula_str.replace("^", "**")
        y = eval(formula_py, {"__builtins__": None}, safe_dict)
        st.line_chart(pd.DataFrame({"x": x, "y": y}), x="x", y="y", height=200)
    except:
        pass

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.title("☁️ 全能提分系统")
    menu = st.radio("功能模块：", ["🏠 冲刺作战室", "📅 今日专属日报", "🤖 定向刷题", "📸 错题录入", "📓 云端错题本"], index=1)
    st.markdown("---")
    st.metric("中考倒计时", f"{get_countdown()} 天")
    
    # 状态检查
    if "gsheets" in st.secrets:
        st.success("数据库状态：已连接 Google Sheets ✅")
    else:
        st.warning("⚠️ 未连接云端数据库 (本地模式)")

# ================= 4. 主页面 =================

if menu == "🏠 冲刺作战室":
    st.title("🎓 盐城中考智700 · 作战大屏")
    
    mistakes = load_mistakes()
    col1, col2, col3 = st.columns(3)
    col1.metric("🎯 目标总分", "710 分")
    col2.metric("🌍 地生得分", "38.5")
    col3.metric("📓 云端错题", f"{len(mistakes)} 题")

    st.markdown("---")
    st.subheader("📊 实时学科状态")
    
    subjects_data = {
        "数学": {"p": 0.6, "g": 145}, "英语": {"p": 0.9, "g": 140},
        "语文": {"p": 0.85, "g": 130}, "物理": {"p": 0.7, "g": 95},
        "化学": {"p": 0.8, "g": 68}
    }
    for sub, data in subjects_data.items():
        st.write(f"**{sub}** (目标 {data['g']}分)")
        st.progress(data['p'])

elif menu == "📅 今日专属日报":
    st.title("📅 今日智能日报")
    
    if st.button("🚀 生成今日任务 (点击一次即可)", type="primary"):
        with st.spinner("AI 正在云端出题 (约5-10秒)..."):
            res = generate_daily_mix_automatically()
            if res:
                st.session_state.daily_tasks = res
                st.rerun()
            
    if "daily_tasks" in st.session_state and st.session_state.daily_tasks:
        for i, q in enumerate(st.session_state.daily_tasks):
            with st.container(border=True):
                # 【关键修复】兼容多种字段名，防止 None
                content = q.get('content') or q.get('question') or q.get('title') or "⚠️ 题目生成格式异常，请重试"
                sub = q.get('subject', '综合')
                
                st.markdown(f"**第 {i+1} 题 [{sub}]**")
                st.markdown(f"##### {content}") # 使用 Markdown 渲染题目，更清晰
                
                if q.get('options'): 
                    st.radio("选项", q['options'], key=f"d_opt_{i}")
                
                c1, c2 = st.columns([1,1])
                if c1.button("👀 看答案", key=f"d_ans_{i}"):
                    st.session_state[f"d_show_{i}"] = True
                if c2.button("💾 保存到云端", key=f"d_s_{i}"):
                    if save_mistake(q): st.success("✅ 已同步至 Google Sheets")
                    else: st.warning("⚠️ 保存失败，可能已存在")
                    
                if st.session_state.get(f"d_show_{i}"):
                    st.info(f"答案：{q.get('answer')}")
                    st.caption(f"解析：{q.get('analysis')}")

elif menu == "🤖 定向刷题":
    st.title("🤖 AI 定向特训")
    c1, c2, c3 = st.columns(3)
    subject = c1.selectbox("科目", ["数学", "英语", "物理", "化学"])
    q_type = c2.selectbox("题型", ["选择题", "填空题"])
    if c3.button("生成"):
        with st.spinner("生成中..."):
            st.session_state.ai_qs = generate_questions_batch(subject, q_type, 3)
            
    if "ai_qs" in st.session_state:
        for i, q in enumerate(st.session_state.ai_qs):
            with st.expander(f"题目 {i+1}", expanded=True):
                # 同样的兼容修复
                content = q.get('content') or q.get('question') or "⚠️ 内容缺失"
                st.write(content)
                if q.get('options'): st.radio("选项", q['options'], key=f"aq_{i}")
                if st.button(f"💾 存入云端", key=f"ai_s_{i}"):
                    q['subject'] = subject
                    save_mistake(q)
                    st.toast("保存成功")
                with st.expander("查看解析"):
                    st.write(q.get('answer'))
                    st.write(q.get('analysis'))

elif menu == "📸 错题录入":
    st.title("📸 拍照错题上传 (云端版)")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        up_subject = c1.selectbox("科目", ["数学", "物理", "化学", "英语", "语文"])
        up_note = c2.text_area("备注")
        uploaded_file = st.file_uploader("上传照片", type=['jpg', 'jpeg', 'png'])
        
        if uploaded_file and st.button("☁️ 上传到云端数据库", type="primary"):
            with st.spinner("正在压缩并上传..."):
                img_str = image_to_base64(uploaded_file)
                if img_str:
                    data = {
                        "subject": up_subject,
                        "content": "📸 [图片题]",
                        "analysis": up_note,
                        "is_image_upload": True,
                        "image_base64": img_str
                    }
                    if save_mistake(data):
                        st.success("✅ 上传成功！")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("上传失败。")

elif menu == "📓 云端错题本":
    st.title("📓 云端错题本")
    mistakes = load_mistakes()
    
    if not mistakes:
        st.info("云端数据库是空的，快去刷题吧！")
    else:
        review_list = []
        for m in mistakes:
            if get_review_status(m['added_date'])[0]:
                review_list.append(m)
        
        tab1, tab2 = st.tabs([f"🔥 急需复习 ({len(review_list)})", f"🗂️ 所有记录 ({len(mistakes)})"])
        
        def render_cloud_card(m):
            status = get_review_status(m['added_date'])[1]
            st.caption(f"[{m['subject']}] {status}")
            with st.expander(f"查看详情...", expanded=False):
                if m.get('is_image_upload'):
                    try:
                        img_data = base64.b64decode(m.get('image_base64', ''))
                        st.image(img_data)
                    except:
                        st.error("图片加载失败")
                    st.write(f"备注：{m.get('analysis')}")
                else:
                    st.write(m.get('content'))
                    st.markdown(f"**答案：** {m.get('answer')}")
                    st.markdown(f"**解析：** {m.get('analysis')}")
        
        with tab1:
            for m in review_list:
                render_cloud_card(m)
        with tab2:
            st.dataframe(pd.DataFrame(mistakes)[['subject', 'added_date', 'content']], use_container_width=True)
            for m in mistakes:
                render_cloud_card(m)
