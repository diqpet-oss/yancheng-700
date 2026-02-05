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

# 读取 Key
if "DEEPSEEK_API_KEY" in st.secrets:
    DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxx" # 本地测试用

BASE_URL = "https://api.deepseek.com"

st.set_page_config(
    page_title="盐城中考智700·云端Pro",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 建立 Google Sheets 连接
conn = st.connection("gsheets", type=GSheetsConnection)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ================= 2. 核心功能函数 =================

def get_countdown():
    exam_date = datetime.date(2026, 6, 16)
    today = datetime.date.today()
    return (exam_date - today).days

# --- ☁️ 云端数据库操作 (核心修改) ---

def load_mistakes():
    """从 Google Sheets 读取错题"""
    try:
        # ttl=0 表示不缓存，每次强制读取最新数据
        df = conn.read(ttl=0)
        # 填充空值，防止报错
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        st.error(f"连接数据库失败，请检查 Secrets 配置: {e}")
        return []

def save_mistake(question_data):
    """保存错题到 Google Sheets"""
    try:
        # 1. 读取现有数据
        existing_data = conn.read(ttl=0)
        
        # 2. 准备新数据行
        new_row = {
            "subject": question_data.get("subject", "综合"),
            "content": question_data.get("content", ""),
            # 选项如果是列表，转成字符串存
            "options": str(question_data.get("options", [])),
            "answer": question_data.get("answer", ""),
            "analysis": question_data.get("analysis", ""),
            "function_formula": question_data.get("function_formula", ""),
            "added_date": str(datetime.date.today()),
            "review_count": 0,
            "is_image_upload": question_data.get("is_image_upload", False),
            "image_base64": question_data.get("image_base64", "") # 图片转码
        }
        
        # 3. 查重 (简单的内容查重)
        if not new_row["is_image_upload"]:
            if not existing_data.empty and new_row["content"] in existing_data["content"].values:
                return False

        # 4. 追加数据
        new_df = pd.DataFrame([new_row])
        updated_df = pd.concat([existing_data, new_df], ignore_index=True)
        
        # 5. 写回 Google Sheets
        conn.update(data=updated_df)
        return True
        
    except Exception as e:
        st.error(f"保存失败: {e}")
        return False

# 图片转 Base64 字符串 (为了存入表格)
def image_to_base64(uploaded_file):
    try:
        bytes_data = uploaded_file.getvalue()
        # 压缩图片以适应表格限制
        img = Image.open(BytesIO(bytes_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        # 限制大小，宽最多800
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, int(img.height * ratio)))
        
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=60) # 降低质量压缩
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

def generate_daily_mix_automatically():
    prompt = """
    请为盐城初三学生生成一份“今日晨测”小卷，包含3道题：
    1. 数学题 (压轴题或填空题)
    2. 英语题 (单选或填空)
    3. 物理题 (计算或简答)
    严禁出识图题。严格返回 JSON List。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "JSON Array Only"}, {"role": "user", "content": prompt}],
            stream=False
        )
        content = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content)
        data = json.loads(content)
        # 日报不存表格，只存在 Session State 里，除非用户点保存
        return data
    except Exception as e:
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
    menu = st.radio("功能模块：", ["🏠 冲刺作战室", "📅 今日专属日报", "🤖 定向刷题", "📸 错题录入", "📓 云端错题本"], index=0)
    st.markdown("---")
    st.metric("中考倒计时", f"{get_countdown()} 天")
    st.success("数据库状态：已连接 Google Sheets ✅")

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
    if st.button("🚀 生成今日任务"):
        with st.spinner("AI 正在云端出题..."):
            res = generate_daily_mix_automatically()
            st.session_state.daily_tasks = res
            
    if "daily_tasks" in st.session_state and st.session_state.daily_tasks:
        for i, q in enumerate(st.session_state.daily_tasks):
            with st.container(border=True):
                st.write(q.get('content'))
                if st.button(f"💾 保存到云端", key=f"d_s_{i}"):
                    if save_mistake(q): st.success("已同步至 Google Sheets")
                    else: st.warning("保存失败或已存在")

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
                st.write(q.get('content'))
                if st.button(f"💾 存入云端错题本", key=f"ai_s_{i}"):
                    q['subject'] = subject
                    save_mistake(q)
                    st.toast("保存成功")

elif menu == "📸 错题录入":
    st.title("📸 拍照错题上传 (云端版)")
    st.info("⚠️ 注意：图片会压缩存储到表格中，请尽量上传清晰的小图。")
    
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
                        st.success("✅ 上传成功！图片已存入 Google Sheets。")
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
        # 过滤需要复习的
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
                    # 解码图片
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
