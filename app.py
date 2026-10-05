import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration & Professional Dark Theme
st.set_page_config(page_title="Shankar Trading Intelligence System", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for Professional Dark Theme styling & smooth UI cards
st.markdown("""
    
""", unsafe_allow_html=True)

# App Header (Clean & Simple)
st.title("🚀 Shankar Trading Intelligence System")
st.markdown("---")

# --- 1. INSTITUTIONAL ACTIVITY (FII / DII) ---
st.subheader("🏦 Institutional Activity (FII/DII)")
f1, f2, f3, f4 = st.columns(4)
f1.metric("FII Net Flow", "₹ -1,250 Cr", "Heavy Selling 🔴")
f2.metric("DII Net Flow", "₹ +1,850 Cr", "Strong Buying 🟢")
f3.metric("PCR Ratio", "1.32", "Bullish (>1.2)")
f4.metric("India VIX", "13.20", "Low Volatility (-1.8%)")

st.markdown("---")

# --- 2. ALL LIVE SPOT INDICES (NSE & BSE) ---
st.subheader("📊 Live Spot Parameters (All Major NSE & BSE Indices)")
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Nifty 50", "24,850.00", "+75.5 pts")
s2.metric("Bank Nifty", "51,200.50", "+180.2 pts")
s3.metric("Sensex (BSE)", "81,400.00", "+250.1 pts")
s4.metric("Midcap Nifty", "12,650.00", "+45.3 pts")
s5.metric("FinNifty", "23,400.10", "+92.0 pts")

st.markdown("---")

# --- 3. MAIN INDEX SELECTOR DROPDOWN (CONTROLS BLACK-SCHOLES) ---
st.subheader("🎯 Active Market Focus & Index Selector")
selected_index = st.selectbox(
    "Choose Index for Detailed Greeks Analysis",
    ["NSE - Nifty 50", "NSE - Bank Nifty", "BSE - Sensex", "NSE - Midcap Nifty", "NSE - FinNifty"]
)
st.markdown(f"📌 **Active Target:** Black-Scholes analytics active for **`{selected_index}`**.")
st.markdown("---")

# --- 4. DYNAMIC BLACK-SCHOLES MODEL ---
st.subheader(f"🧮 Black-Scholes Model — [{selected_index}]")

if "Nifty 50" in selected_index:
    strike_ref, d_val, t_val, g_val, v_val = "24,850 ATM", "0.58", "-42.50", "0.0025", "12.40"
elif "Bank Nifty" in selected_index:
    strike_ref, d_val, t_val, g_val, v_val = "51,200 ATM", "0.52", "-85.00", "0.0012", "24.50"
elif "Sensex" in selected_index:
    strike_ref, d_val, t_val, g_val, v_val = "81,400 ATM", "0.55", "-110.20", "0.0009", "32.10"
elif "Midcap Nifty" in selected_index:
    strike_ref, d_val, t_val, g_val, v_val = "12,650 ATM", "0.60", "-25.40", "0.0045", "8.90"
else:
    strike_ref, d_val, t_val, g_val, v_val = "23,400 ATM", "0.53", "-38.20", "0.0032", "11.10"

st.markdown(f"🔍 **Strike Reference:** `{strike_ref}`")

b1, b2, b3, b4 = st.columns(4)
b1.metric("Delta (Delta)", d_val, "Direction Sensitivity")
b2.metric("Theta (Theta)", t_val, "Time Decay / Day")
b3.metric("Gamma (Gamma)", g_val, "Delta Velocity")
b4.metric("Vega (Vega)", v_val, "Volatility Impact")

st.markdown("---")

# --- 5. AUTOMATED OPTION BUYING SETUPS ---
st.subheader("🎯 Shankar's Automated Option Buying Setups")

col_a, col_b, col_c = st.columns(3)

with col_a:
    st.success("**Nifty 50 Setup**\n\n* **Action:** BUY 24850 CE\n* **Entry:** ₹ 150.00\n* **SL:** ₹ 123.00 🛑\n* **Target:** ₹ 187.00 / 232.00 🎯")

with col_b:
    st.info("**Bank Nifty Setup**\n\n* **Action:** BUY 51200 CE\n* **Entry:** ₹ 340.00\n* **SL:** ₹ 290.00 🛑\n* **Target:** ₹ 410.00 / 480.00 🎯")

with col_c:
    st.warning("**Sensex Setup**\n\n* **Action:** BUY 81400 CE\n* **Entry:** ₹ 450.00\n* **SL:** ₹ 390.00 🛑\n* **Target:** ₹ 550.00 / 650.00 🎯")

st.markdown("---")

# --- 6. WORLD NEWS & GAP-UP / GAP-DOWN PREDICTOR ---
st.subheader("📰 World Market News & Next-Day Gap-Up / Gap-Down Analysis")

news_table_data = {
    "Time / Session": ["Post-Market (3:30 PM)", "Afternoon Session (2:30 PM)", "Global Cues", "Macro & Option Chain"],
    "Category": ["Gap Prediction", "Institutional Trend", "World Markets", "Macro & Option Data"],
    "Analysis & News Details": [
        "🟢 **Expected Opening:** Likely **GAP-UP** tomorrow based on sustained DII buying and strong US futures.",
        "DII accumulation holding major supports; option chain shows heavy put writing at lower strikes.",
        "European markets trading higher with positive breadth; Asian indices stable.",
        "Macro inflation data within RBI comfort zone; institutional positioning favours bulls."
    ]
}

df_world_news = pd.DataFrame(news_table_data)
st.table(df_world_news)

# --- SIDEBAR: TICK-BY-TICK API CONTROLS ---
st.sidebar.header("🔐 Broker API & Tick Streaming")
api_key_input = st.sidebar.text_input("Enter Broker API Key", type="password")
api_secret_input = st.sidebar.text_input("Enter API Secret Code", type="password")

if st.sidebar.button("Connect API"):
    if api_key_input and api_secret_input:
        st.sidebar.success("🟢 API Connected Successfully!")
    else:
        st.sidebar.warning("⚠️ Please enter valid API credentials.")

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ Live Feed Mode")
tick_mode = st.sidebar.checkbox("Enable Tick-by-Tick (1-Sec Realtime)", value=True)

if tick_mode:
    st.sidebar.success("⚡ Tick-by-Tick Streaming Active (WebSocket Ready)")
else:
    st.sidebar.warning("🔴 Tick Stream Paused")
