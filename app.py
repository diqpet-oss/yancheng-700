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

# 读取 DeepSeek Key
if "DEEPSEEK_API_KEY" in st.secrets:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    # 🔴 本地运行时，请确保这里填的是你的真实 Key
    DEEPSEEK_API_KEY = "sk-4db012ee3d684f76ac67fa943c636cc2"

BASE_URL = "https://api.deepseek.com"

st.set_page_config(
    page_title="盐城中考智700·云端Pro",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 尝试建立 Google Sheets 连接
conn = None
try:
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        conn = st.connection("gsheets", type=GSheetsConnection)
except:
    pass 

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ================= 2. 核心功能函数 =================

def get_countdown():
    exam_date = datetime.date(2026, 6, 16)
    today = datetime.date.today()
    return (exam_date - today).days

# --- ☁️ 云端数据库操作 ---

def load_mistakes():
    """从 Google Sheets 读取错题"""
    if conn is None:
        return [] # 没连接就返回空
    try:
        df = conn.read(ttl=0)
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        return []

def save_mistake(question_data):
    """保存错题到 Google Sheets"""
    if conn is None:
        st.error("❌ 未连接云端数据库，无法保存！请检查配置。")
        return False
        
    try:
        existing_data = conn.read(ttl=0)
        
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
        if img.mode != 'RGB': img = img.convert('RGB')
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, int(img.height * ratio)))
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=60)
        return base64.b64encode(buffered.getvalue()).decode()
    except:
        return ""

def get_review_status(added_date_str):
    try:
        added_date = datetime.datetime.strptime(str(added_date_str), "%Y-%m-%d").date()
    except:
        return False, "日期错误"
    days_diff = (datetime.date.today() - added_date).days
    if days_diff in [1, 3, 7, 15, 30]: return True, f"⚠️ 遗忘临界点 ({days_diff}天)"
    elif days_diff == 0: return False, "🆕 今日新题"
    elif days_diff > 30: return True, "📅 长期复习"
    return False, f"✅ 保鲜中 ({days_diff}天)"

# --- AI 生成 ---
def generate_questions_batch(subject, type_choice, count=3):
    prompt = f"""
    你是盐城中考出题专家。出 {count} 道【{subject}】【{type_choice}】。
    要求：难度中考冲刺级。严禁出识图题。
    格式：严格返回 JSON Array，含 content, options, answer, analysis。
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

def generate_daily_mix_automatically():
    prompt = """
    生成“盐城中考晨测”3道题：1.数学 2.英语 3.物理。
    要求：返回纯 JSON Array。必须包含 key: "content"。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "Output valid JSON Array. 'content' key is mandatory."}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        return json.loads(content)
    except:
        return []

def plot_function(formula_str):
    try:
        if not formula_str or pd.isna(formula_str): return
        x = np.linspace(-5, 5, 100)
        y = eval(formula_str.replace("^", "**"), {"__builtins__": None}, {"x": x, "np": np, "sin": np.sin, "cos": np.cos, "abs": np.abs})
        st.line_chart(pd.DataFrame({"x": x, "y": y}), x="x", y="y", height=200)
    except: pass

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.title("☁️ 全能提分系统")
    menu = st.radio("功能模块：", ["🏠 冲刺作战室", "📅 今日专属日报", "🤖 定向刷题", "📸 错题录入", "📓 云端错题本"], index=1)
    st.markdown("---")
    st.metric("倒计时", f"{get_countdown()} 天")
    
    # 【修复后的状态检查】
    if conn:
        st.success("数据库状态：已连接 Google Sheets ✅")
    else:
        st.warning("⚠️ 未连接云端数据库 (本地模式)")
        st.caption("提示：在本地运行需要配置 .streamlit/secrets.toml 文件")

# ================= 4. 主页面 =================

if menu == "🏠 冲刺作战室":
    st.title("🎓 盐城中考智700 · 作战大屏")
    mistakes = load_mistakes()
    c1, c2, c3 = st.columns(3)
    c1.metric("🎯 目标总分", "710"); c2.metric("🌍 地生", "38.5"); c3.metric("📓 云端错题", f"{len(mistakes)}")
    st.markdown("---")
    st.write("📊 **实时状态**")
    st.progress(0.7)

elif menu == "📅 今日专属日报":
    st.title("📅 今日智能日报")
    if st.button("🚀 生成今日任务", type="primary"):
        with st.spinner("AI 出题中..."):
            res = generate_daily_mix_automatically()
            if res:
                st.session_state.daily_tasks = res
                st.rerun()
    
    if "daily_tasks" in st.session_state:
        for i, q in enumerate(st.session_state.daily_tasks):
            with st.container(border=True):
                content = q.get('content') or q.get('question') or "题目内容缺失"
                st.markdown(f"**第 {i+1} 题**")
                st.markdown(f"##### {content}")
                if q.get('options'): st.radio("选项", q['options'], key=f"d_o_{i}")
                c1, c2 = st.columns([1,1])
                if c1.button("👀 答案", key=f"d_a_{i}"): st.session_state[f"show_{i}"] = True
                if c2.button("💾 保存到云端", key=f"d_s_{i}"):
                    if save_mistake(q): st.success("已同步")
                if st.session_state.get(f"show_{i}"):
                    st.info(q.get('answer')); st.caption(q.get('analysis'))

elif menu == "🤖 定向刷题":
    st.title("🤖 AI 定向特训")
    c1,c2,c3 = st.columns(3)
    sub = c1.selectbox("科目", ["数学","英语","物理","化学"])
    typ = c2.selectbox("题型", ["选择","填空"])
    if c3.button("生成"):
        st.session_state.ai_qs = generate_questions_batch(sub, typ, 3)
    if "ai_qs" in st.session_state:
        for i, q in enumerate(st.session_state.ai_qs):
            with st.expander(f"题目 {i+1}", expanded=True):
                st.write(q.get('content') or q.get('question'))
                if q.get('options'): st.radio("选项", q['options'], key=f"aq_{i}")
                if st.button("💾 存云端", key=f"as_{i}"): save_mistake(q); st.toast("已保存")
                st.caption(f"答案：{q.get('answer')}")

elif menu == "📸 错题录入":
    st.title("📸 拍照上传 (云端)")
    c1, c2 = st.columns(2)
    sub = c1.selectbox("科目", ["数学","物理","英语","语文","化学"])
    note = c2.text_area("备注")
    up = st.file_uploader("传图", type=['jpg','png'])
    if up and st.button("☁️ 上传"):
        b64 = image_to_base64(up)
        if save_mistake({"subject":sub, "content":"📸 [图片]", "analysis":note, "is_image_upload":True, "image_base64":b64}):
            st.success("成功！"); time.sleep(1); st.rerun()

elif menu == "📓 云端错题本":
    st.title("📓 云端错题本")
    data = load_mistakes()
    if not data: st.info("云端暂无数据，或未连接数据库。")
    else:
        for m in data:
            with st.expander(f"[{m['subject']}] {m['content'][:20]}..."):
                if m.get('is_image_upload'):
                    try: st.image(base64.b64decode(m['image_base64']))
                    except: st.error("图片错误")
                else:
                    st.write(m['content']); st.write(f"答案：{m['answer']}")
                st.caption(f"备注：{m['analysis']}")
