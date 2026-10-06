import os
import math
import json
import time
import struct
import threading
from datetime import datetime

import pandas as pd
import streamlit as st
import websocket  # pip install websocket-client

# ---------------------------------------------------------------
# Page config
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Shankar Trading Intelligence System (Live Pro)",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* अपनी dark theme CSS यहाँ डालें */
</style>
""", unsafe_allow_html=True)

st.title("🚀 Shankar Trading Intelligence System (Live Tick Feed)")
st.markdown("📌 *Dhan WebSocket Market Feed - NSE, BSE, MCX*")
st.markdown("---")

# ---------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------
# Segment codes (Dhan binary header): IDX_I=0, NSE_EQ=1, NSE_FNO=2, BSE_EQ=4, MCX_COMM=5
SEG_CODE = {"IDX_I": 0, "NSE_EQ": 1, "NSE_FNO": 2, "BSE_EQ": 4, "MCX_COMM": 5}

# name: (segment, security_id, strike_step)
INDICES = {
    "Nifty 50":     ("IDX_I", 13, 50),
    "Bank Nifty":   ("IDX_I", 25, 100),
    "Sensex":       ("IDX_I", 51, 100),
    "Midcap Nifty": ("IDX_I", 442, 25),
    "FinNifty":     ("IDX_I", 27, 50),
}
VIX = ("IDX_I", 21)

# MCX futures ke security id har mahine badalte hain (expiry ke saath),
# isliye scrip master se nearest expiry auto-pick hoti hai.
MCX_PREFIX = {
    "Gold (MCX)":   ("GOLD", 100),
    "Silver (MCX)": ("SILVER", 500),
    "Crude Oil":    ("CRUDEOIL", 50),
    "Natural Gas":  ("NATURALGAS", 2.5),
}

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_mcx_front_month():
    """Nearest-expiry MCX futures ke security IDs scrip master se."""
    out = {}
    try:
        df = pd.read_csv(SCRIP_MASTER_URL, low_memory=False)
        df = df[(df["SEM_EXM_EXCH_ID"] == "MCX") & (df["SEM_INSTRUMENT_NAME"] == "FUTCOM")].copy()
        df["exp"] = pd.to_datetime(df["SEM_EXPIRY_DATE"], errors="coerce")
        df = df[df["exp"] >= pd.Timestamp.now().normalize()]
        for name, (prefix, _) in MCX_PREFIX.items():
            sub = df[df["SEM_TRADING_SYMBOL"].astype(str).str.startswith(prefix + "-")]
            if not sub.empty:
                row = sub.sort_values("exp").iloc[0]
                out[name] = int(row["SEM_SMST_SECURITY_ID"])
    except Exception as e:  # noqa
        st.sidebar.warning(f"MCX auto-lookup fail: {e}. Neeche manual ID daalein.")
    return out


# ---------------------------------------------------------------
# Binary packet parser (Dhan Market Feed v2, little endian)
# ---------------------------------------------------------------
def parse_packet(data: bytes):
    if len(data) < 8:
        return None
    code = data[0]
    seg = data[3]
    secid = struct.unpack_from("<i", data, 4)[0]
    out = {}
    if code == 2 and len(data) >= 16:            # Ticker
        out["ltp"] = struct.unpack_from("<f", data, 8)[0]
        out["ltt"] = struct.unpack_from("<i", data, 12)[0]
    elif code == 4 and len(data) >= 50:          # Quote
        out["ltp"] = struct.unpack_from("<f", data, 8)[0]
        out["ltt"] = struct.unpack_from("<i", data, 14)[0]
        out["volume"] = struct.unpack_from("<i", data, 22)[0]
        out["open"] = struct.unpack_from("<f", data, 34)[0]
        out["close"] = struct.unpack_from("<f", data, 38)[0]
        out["high"] = struct.unpack_from("<f", data, 42)[0]
        out["low"] = struct.unpack_from("<f", data, 46)[0]
    elif code == 8 and len(data) >= 62:          # Full
        out["ltp"] = struct.unpack_from("<f", data, 8)[0]
        out["ltt"] = struct.unpack_from("<i", data, 14)[0]
        out["volume"] = struct.unpack_from("<i", data, 22)[0]
        out["oi"] = struct.unpack_from("<i", data, 34)[0]
        out["open"] = struct.unpack_from("<f", data, 46)[0]
        out["close"] = struct.unpack_from("<f", data, 50)[0]
        out["high"] = struct.unpack_from("<f", data, 54)[0]
        out["low"] = struct.unpack_from("<f", data, 58)[0]
    elif code == 6 and len(data) >= 12:          # Previous close
        out["prev_close"] = struct.unpack_from("<f", data, 8)[0]
    elif code == 50 and len(data) >= 10:         # Disconnect
        out["disconnect"] = struct.unpack_from("<h", data, 8)[0]
    else:
        return None
    return code, seg, secid, out


DISCONNECT_MSG = {
    805: "Bahut zyada connections (max 5 WebSocket)",
    806: "Data API subscription active nahi hai",
    807: "Access token expire ho gaya - naya token banayein",
    808: "Authentication fail (Client ID / token galat)",
    809: "Access token invalid",
}


# ---------------------------------------------------------------
# Background WebSocket manager (ek hi connection, saare sessions share)
# ---------------------------------------------------------------
class FeedManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.ticks = {}          # (seg_code, secid) -> dict
        self.status = "Not started"
        self.error = ""
        self.last_msg = 0.0
        self.key = None
        self.ws = None

    def ensure(self, client_id, token, instruments):
        key = (client_id, token, tuple(instruments))
        if self.key == key:
            return
        old_ws = self.ws
        self.key = key
        if old_ws is not None:
            try:
                old_ws.close()
            except Exception:
                pass
        with self.lock:
            self.ticks = {}
        self.error = ""
        threading.Thread(
            target=self._run, args=(key, client_id, token, list(instruments)), daemon=True
        ).start()

    def _run(self, key, client_id, token, instruments):
        url = (f"wss://api-feed.dhan.co?version=2&token={token}"
               f"&clientId={client_id}&authType=2")

        def on_open(ws):
            self.status = "Connected"
            # Indices -> Ticker (15), MCX -> Quote (17)
            groups = {15: [], 17: []}
            for seg, secid in instruments:
                groups[15 if seg == "IDX_I" else 17].append(
                    {"ExchangeSegment": seg, "SecurityId": str(secid)})
            for req, lst in groups.items():
                for i in range(0, len(lst), 100):
                    chunk = lst[i:i + 100]
                    ws.send(json.dumps({
                        "RequestCode": req,
                        "InstrumentCount": len(chunk),
                        "InstrumentList": chunk,
                    }))

        def on_message(ws, msg):
            if not isinstance(msg, (bytes, bytearray)):
                return
            res = parse_packet(bytes(msg))
            if not res:
                return
            code, seg, secid, out = res
            self.last_msg = time.time()
            if "disconnect" in out:
                self.error = DISCONNECT_MSG.get(out["disconnect"], f"Disconnect code {out['disconnect']}")
                return
            with self.lock:
                self.ticks.setdefault((seg, secid), {}).update(out)

        def on_error(ws, err):
            self.error = str(err)

        def on_close(ws, code, reason):
            self.status = "Disconnected"

        while self.key == key:
            self.status = "Connecting"
            ws = websocket.WebSocketApp(
                url, on_open=on_open, on_message=on_message,
                on_error=on_error, on_close=on_close)
            self.ws = ws
            ws.run_forever()
            if self.key != key:
                break
            self.status = "Reconnecting"
            time.sleep(5)

    def snapshot(self):
        with self.lock:
            return {k: dict(v) for k, v in self.ticks.items()}


@st.cache_resource
def get_manager():
    return FeedManager()


# ---------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------
st.sidebar.header("🔐 Dhan API")
client_id = st.sidebar.text_input("Dhan Client ID", value=os.getenv("DHAN_CLIENT_ID", ""))
access_token = st.sidebar.text_input("Dhan Access Token", value=os.getenv("DHAN_ACCESS_TOKEN", ""), type="password")

st.sidebar.markdown("---")
st.sidebar.subheader("MCX Security ID (optional override)")
mcx_auto = load_mcx_front_month()
mcx_ids = {}
for name in MCX_PREFIX:
    default = mcx_auto.get(name, 0)
    val = st.sidebar.number_input(f"{name}", value=int(default), step=1, format="%d")
    if val:
        mcx_ids[name] = int(val)

st.sidebar.markdown("---")
st.sidebar.subheader("Black-Scholes inputs")
iv_input = st.sidebar.number_input("IV % (0 = India VIX use karo)", value=0.0, step=0.5)
dte = st.sidebar.number_input("Expiry me bache din", value=5, min_value=1, step=1)
rate = st.sidebar.number_input("Risk-free rate %", value=6.5, step=0.1)

# ---------------------------------------------------------------
# Start feed
# ---------------------------------------------------------------
manager = get_manager()
instruments = [(INDICES[n][0], INDICES[n][1]) for n in INDICES] + [VIX]
instruments += [("MCX_COMM", sid) for sid in mcx_ids.values()]

if client_id and access_token:
    manager.ensure(client_id, access_token, instruments)
else:
    st.warning("👈 Sidebar me Dhan Client ID aur Access Token daalein. Token 24 ghante me expire hota hai.")


def quote_for(snap, name):
    """(ltp, change_pts, change_pct) ya None."""
    if name in INDICES:
        seg, sid = INDICES[name][0], INDICES[name][1]
    elif name in mcx_ids:
        seg, sid = "MCX_COMM", mcx_ids[name]
    else:
        return None
    t = snap.get((SEG_CODE[seg], sid))
    if not t or "ltp" not in t:
        return None
    ltp = t["ltp"]
    pc = t.get("prev_close") or t.get("close")
    if pc:
        chg = ltp - pc
        return ltp, chg, chg / pc * 100
    return ltp, None, None


def show_metric(col, label, q):
    if q is None:
        col.metric(label, "—", "waiting...")
        return
    ltp, chg, pct = q
    delta = f"{chg:+,.2f} pts ({pct:+.2f}%)" if chg is not None else None
    col.metric(label, f"₹ {ltp:,.2f}", delta)


# ---------------------------------------------------------------
# Black-Scholes (call, ATM) - real greeks, hardcoded nahi
# ---------------------------------------------------------------
def bs_call_greeks(S, K, T, r, sigma):
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / sq
    d2 = d1 - sq
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    delta = N(d1)
    gamma = pdf / (S * sq)
    vega = S * pdf * math.sqrt(T) / 100            # per 1% IV
    theta = (-(S * pdf * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N(d2)) / 365
    return delta, theta, gamma, vega


# ---------------------------------------------------------------
# Static (EOD) section - ye abhi bhi manual hai
# ---------------------------------------------------------------
st.subheader("🏦 Institutional Activity (EOD - manual values)")
f1, f2, f3 = st.columns(3)
f1.metric("FII Net Flow", "₹ -1,350 Cr", "FII Short Accumulation 🔴")
f2.metric("DII Net Flow", "₹ +2,210 Cr", "Strong Institutional Support 🟢")
f3.metric("PCR Ratio", "1.36", "Bullish Sentiment (>1.2)")
st.markdown("---")

selected_target = st.selectbox(
    "Black-Scholes Analysis ke liye instrument chunein",
    ["Nifty 50", "Bank Nifty", "Sensex", "Midcap Nifty", "FinNifty",
     "Gold (MCX)", "Silver (MCX)", "Crude Oil", "Natural Gas"],
)


# ---------------------------------------------------------------
# LIVE PANEL - har 1 second me refresh (sirf ye hissa)
# ---------------------------------------------------------------
@st.fragment(run_every=1)
def live_panel():
    snap = manager.snapshot()
    age = time.time() - manager.last_msg if manager.last_msg else None
    icon = "🟢" if (age is not None and age < 5) else "🟡" if manager.status == "Connected" else "🔴"
    status = f"{icon} Feed: **{manager.status}**"
    if age is not None:
        status += f" | last tick {age:.0f}s pehle | {datetime.now():%H:%M:%S}"
    if manager.error:
        status += f" | ⚠️ {manager.error}"
    st.markdown(status)

    # VIX
    vix_t = snap.get((SEG_CODE[VIX[0]], VIX[1]))
    vix_val = vix_t["ltp"] if vix_t and "ltp" in vix_t else None

    st.subheader("📈 NSE & BSE Indices (Live)")
    cols = st.columns(6)
    show_metric(cols[0], "Nifty 50 (NSE)", quote_for(snap, "Nifty 50"))
    show_metric(cols[1], "Bank Nifty (NSE)", quote_for(snap, "Bank Nifty"))
    show_metric(cols[2], "Sensex (BSE)", quote_for(snap, "Sensex"))
    show_metric(cols[3], "Midcap Nifty (NSE)", quote_for(snap, "Midcap Nifty"))
    show_metric(cols[4], "FinNifty (NSE)", quote_for(snap, "FinNifty"))
    cols[5].metric("India VIX", f"{vix_val:.2f}" if vix_val else "—")

    st.markdown("---")
    st.subheader("🛢️ MCX Commodities (Live)")
    m = st.columns(4)
    show_metric(m[0], "Gold (MCX)", quote_for(snap, "Gold (MCX)"))
    show_metric(m[1], "Silver (MCX)", quote_for(snap, "Silver (MCX)"))
    show_metric(m[2], "Crude Oil (MCX)", quote_for(snap, "Crude Oil"))
    show_metric(m[3], "Natural Gas (MCX)", quote_for(snap, "Natural Gas"))

    st.markdown("---")
    st.subheader(f"🧮 Black-Scholes & Greeks - [{selected_target}]")
    q = quote_for(snap, selected_target)
    if q is None:
        st.info("Spot price ka intezaar hai...")
    else:
        spot = q[0]
        step = INDICES[selected_target][2] if selected_target in INDICES else MCX_PREFIX[selected_target][1]
        atm = round(spot / step) * step
        iv = iv_input if iv_input > 0 else (vix_val or 15.0)
        T = dte / 365
        d, th, g, v = bs_call_greeks(spot, atm, T, rate / 100, iv / 100)
        st.markdown(f"🔍 **Live Spot:** `{spot:,.2f}` | **ATM Strike:** `{atm:g}` | **IV:** `{iv:.2f}%` | **DTE:** `{dte}`")
        b = st.columns(4)
        b[0].metric("Delta (Δ)", f"{d:.3f}", "Direction Sensitivity")
        b[1].metric("Theta (Θ)", f"{th:.2f}", "Time Decay / Day")
        b[2].metric("Gamma (Γ)", f"{g:.5f}", "Delta Velocity")
        b[3].metric("Vega (ν)", f"{v:.2f}", "per 1% IV")

    st.markdown("---")
    st.subheader("🎯 Shankar's Option & Commodity Buying Setups")

    def atm_of(name, step):
        qq = quote_for(snap, name)
        return (int(round(qq[0] / step) * step), qq[0]) if qq else (None, None)

    n_atm, n_sp = atm_of("Nifty 50", 50)
    b_atm, b_sp = atm_of("Bank Nifty", 100)
    g_atm, g_sp = atm_of("Gold (MCX)", 100)
    c_atm, c_sp = atm_of("Crude Oil", 50)

    # NOTE: Entry/SL/Target abhi manual hain. Yahan apni strategy ka logic lagega.
    a, b_, c_, d_ = st.columns(4)
    a.success(f"**Nifty 50 Setup**\n\n* **Action:** BUY `{n_atm} CE`\n* **Live Spot:** {n_sp}\n* **Entry:** ₹ 145.00\n* **SL:** ₹ 118.00 🛑\n* **Target:** ₹ 190.00 / 240.00 🎯")
    b_.info(f"**Bank Nifty Setup**\n\n* **Action:** BUY `{b_atm} CE`\n* **Live Spot:** {b_sp}\n* **Entry:** ₹ 335.00\n* **SL:** ₹ 280.00 🛑\n* **Target:** ₹ 420.00 / 500.00 🎯")
    c_.warning(f"**Gold (MCX) Setup**\n\n* **Action:** BUY `{g_atm} CE`\n* **Live Spot:** {g_sp}\n* **Entry:** ₹ 450.00\n* **SL:** ₹ 390.00 🛑\n* **Target:** ₹ 550.00 / 650.00 🎯")
    d_.error(f"**Crude Oil Setup**\n\n* **Action:** BUY `{c_atm} PE`\n* **Live Spot:** {c_sp}\n* **Entry:** ₹ 125.00\n* **SL:** ₹ 98.00 🛑\n* **Target:** ₹ 165.00 / 210.00 🎯")


live_panel()

st.markdown("---")
st.subheader("📰 Market Intelligence (manual notes)")
df_news = pd.DataFrame({
    "Session / Time": ["Evening MCX (4:00 PM)", "Afternoon Close (3:30 PM)", "Global Cues", "Option Chain Action"],
    "Market Segment": ["Bullion & Energy", "Equity Indices", "US / European Futures", "Derivatives Data"],
    "Analysis": [
        "🟢 Gold & Silver: Positive momentum holding near highs due to safe-haven buying.",
        "🟢 Indices Outlook: Strong DII buying pointing to steady continuation.",
        "European markets positive bias; US futures pointing green.",
        "Heavy put writing at lower strikes across Nifty and MCX contracts supporting bulls.",
    ],
})
st.table(df_news)
